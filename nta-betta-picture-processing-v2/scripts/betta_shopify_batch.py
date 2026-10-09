#!/usr/bin/env python3
"""Generic, resumable Shopify uploader for approved NTA Betta batches.

Dry-run is the default. Live writes require a hash-locked owner-approved manifest,
an explicit --live flag, and the manifest SHA-256 repeated on the command line.
Every mutation intent is journalled before the authenticated Shopify bridge is
called. An uncertain write is reconciled from fresh Shopify state and is never
automatically replayed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

MANIFEST_SCHEMA = "nta-betta-shopify-batch-v1"
STATE_SCHEMA = "nta-betta-shopify-batch-state-v1"
REPORT_SCHEMA = "nta-betta-shopify-batch-report-v1"
FINAL_RECEIPT_SCHEMA = "nta-betta-shopify-final-receipt-v1"

TANK_RE = re.compile(r"^[1-9]\d*BT[1-9]\d*$")
BATCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
GIDS = {
    "product_id": re.compile(r"^gid://shopify/Product/[1-9]\d*$"),
    "variant_id": re.compile(r"^gid://shopify/ProductVariant/[1-9]\d*$"),
    "inventory_item_id": re.compile(r"^gid://shopify/InventoryItem/[1-9]\d*$"),
    "location_id": re.compile(r"^gid://shopify/Location/[1-9]\d*$"),
    "media_id": re.compile(r"^gid://shopify/MediaImage/[1-9]\d*$"),
}
REQUIRED_EVIDENCE = {
    "approval_plan", "protected_snapshot", "shopify_details",
    "labels", "new_fish_authority",
}
PROTECTED_FIELDS = (
    "description_html", "price", "cost", "vendor",
    "product_type", "handle", "status",
)
WRITE_OPERATIONS = {
    "betta_batch_stage_images", "betta_batch_add_images",
    "betta_batch_reorder_media", "betta_batch_delete_media",
    "betta_batch_update_details", "betta_batch_set_inventory",
}
STAGE_ORDER = {
    "NEW": 0,
    "PREFLIGHTED": 1,
    "STAGING_ALLOCATED": 2,
    "STAGED": 3,
    "MEDIA_ATTACH_REQUESTED": 4,
    "MEDIA_READY": 5,
    "MEDIA_ORDERED": 6,
    "OLD_MEDIA_DELETED": 7,
    "DETAILS_UPDATED": 8,
    "INVENTORY_UPDATED": 9,
    "VERIFIED": 10,
    "COMPLETED_VERIFIED": 10,
}


class BatchError(RuntimeError):
    pass


class ManifestError(BatchError):
    pass


class ShopifyReadError(BatchError):
    pass


class ShopifyWriteRejected(BatchError):
    pass


class UncertainWriteError(BatchError):
    pass


class DeferredError(BatchError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise ManifestError(f"file missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"invalid JSON: {path}: {exc}") from exc


def fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_json(path: Path, value: Any, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
        fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json_exclusive(path: Path, value: Any, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    fsync_directory(path.parent)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestError(message)


def resolve_path(base: Path, value: Any, label: str) -> Path:
    require(isinstance(value, str) and value.strip(), f"{label}: path required")
    candidate = Path(os.path.expanduser(value.strip()))
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


def require_sha(value: Any, label: str) -> str:
    require(isinstance(value, str) and SHA_RE.fullmatch(value) is not None,
            f"{label}: lowercase SHA-256 required")
    return value


def require_gid(value: Any, kind: str, label: str) -> str:
    require(isinstance(value, str) and GIDS[kind].fullmatch(value) is not None,
            f"{label}: invalid Shopify GID")
    return value


def parse_date(value: Any, label: str) -> str:
    require(isinstance(value, str), f"{label}: YYYY-MM-DD required")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ManifestError(f"{label}: invalid calendar date") from exc
    return value


def numeric_equal(left: Any, right: Any) -> bool:
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, TypeError, ValueError):
        return False


def index_unique(records: Iterable[Mapping[str, Any]], key: str, label: str) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for record in records:
        value = record.get(key)
        require(isinstance(value, str) and value, f"{label}: missing {key}")
        require(value not in result, f"{label}: duplicate {key}: {value}")
        result[value] = record
    return result


def media_alt(batch_id: str, tank_id: str, role: str, digest: str) -> str:
    return f"NTA|{batch_id}|{tank_id}|{role}|sha256={digest}"


@dataclass(frozen=True)
class Evidence:
    name: str
    path: Path
    sha256: str
    data: Any


@dataclass
class ItemContext:
    bundle: "ManifestBundle"
    raw: dict[str, Any]
    approval: Mapping[str, Any]
    protected_record: Mapping[str, Any]
    details: Mapping[str, Any]
    label: Mapping[str, Any]
    authority: Mapping[str, Any]
    qa: Mapping[str, Any]
    qa_sha256: str
    protected: dict[str, Any]
    baseline: dict[str, Any]
    completion: dict[str, Any] | None

    @property
    def tank_id(self) -> str:
        return self.raw["tank_id"]

    @property
    def product_id(self) -> str:
        return self.raw["product_id"]

    @property
    def variant_id(self) -> str:
        return self.raw["variant_id"]

    @property
    def inventory_item_id(self) -> str:
        return self.raw["inventory_item_id"]

    @property
    def location_id(self) -> str:
        return self.raw["location_id"]

    @property
    def title(self) -> str:
        return self.raw["approved_title"]

    @property
    def arrival_date(self) -> str:
        return self.raw["arrival_date"]

    @property
    def quantity(self) -> int:
        return self.raw["quantity"]

    def asset(self, role: str) -> dict[str, Any]:
        return self.raw[role]

    def expected_alt(self, role: str) -> str:
        return media_alt(
            self.bundle.batch_id, self.tank_id, role.upper(), self.asset(role)["sha256"]
        )


class ManifestBundle:
    """Hash-locked manifest plus its required evidence sidecars."""

    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()
        require(self.path.is_file(), f"manifest missing: {self.path}")
        self.sha256 = sha256_file(self.path)
        self.raw = read_json(self.path)
        require(isinstance(self.raw, dict), "manifest root must be an object")
        require(self.raw.get("schema") == MANIFEST_SCHEMA,
                f"manifest schema must be {MANIFEST_SCHEMA}")
        self.batch_id = self.raw.get("batch_id")
        require(isinstance(self.batch_id, str) and BATCH_RE.fullmatch(self.batch_id) is not None,
                "manifest batch_id is invalid")
        require(isinstance(self.raw.get("shopify_write_authorised"), bool),
                "shopify_write_authorised must be boolean")
        require(isinstance(self.raw.get("items"), list) and self.raw["items"],
                "manifest items must be a non-empty list")
        self.evidence = self._load_evidence()
        self.contexts: dict[str, ItemContext] = {}
        self._validate_items()
        configured_state = self.raw.get("state_dir")
        self.state_dir = (
            resolve_path(self.path.parent, configured_state, "state_dir")
            if configured_state
            else (self.path.parent / ".betta-shopify-state" /
                  self.batch_id / self.sha256[:12]).resolve()
        )
        configured_report = self.raw.get("report_dir")
        self.report_dir = (
            resolve_path(self.path.parent, configured_report, "report_dir")
            if configured_report else self.state_dir / "reports"
        )

    def _load_evidence(self) -> dict[str, Evidence]:
        records = self.raw.get("evidence")
        require(isinstance(records, dict), "manifest evidence object required")
        missing = REQUIRED_EVIDENCE - set(records)
        require(not missing, "manifest missing evidence: " + ", ".join(sorted(missing)))
        result: dict[str, Evidence] = {}
        for name, record in records.items():
            require(isinstance(record, dict), f"evidence {name}: object required")
            path = resolve_path(self.path.parent, record.get("path"), f"evidence {name}")
            digest = require_sha(record.get("sha256"), f"evidence {name}")
            require(path.is_file(), f"evidence {name}: file missing")
            require(sha256_file(path) == digest, f"evidence {name}: hash mismatch")
            result[name] = Evidence(name, path, digest, read_json(path))
        return result

    def _validate_items(self) -> None:
        approval = index_unique(
            self.evidence["approval_plan"].data.get("items", []), "tank_id", "approval plan")
        snapshot = index_unique(
            self.evidence["protected_snapshot"].data.get("records", []), "tank_id", "snapshot")
        details = index_unique(
            self.evidence["shopify_details"].data.get("items", []), "tank_id", "details")
        labels = index_unique(
            self.evidence["labels"].data.get("items", []), "tank_id", "labels")
        authority = index_unique(
            self.evidence["new_fish_authority"].data.get("items", []), "tank_id", "authority")

        seen: dict[str, set[str]] = {
            "tank": set(), "product": set(), "variant": set(),
            "inventory": set(), "source": set(),
        }
        for raw in self.raw["items"]:
            require(isinstance(raw, dict), "manifest item must be an object")
            tank = raw.get("tank_id")
            require(isinstance(tank, str) and TANK_RE.fullmatch(tank) is not None,
                    f"invalid tank_id: {tank!r}")
            require(tank not in seen["tank"], f"duplicate tank_id: {tank}")
            seen["tank"].add(tank)
            for field in ("product_id", "variant_id", "inventory_item_id", "location_id"):
                require_gid(raw.get(field), field, f"{tank} {field}")
            for field, bucket in (
                ("product_id", "product"), ("variant_id", "variant"),
                ("inventory_item_id", "inventory"),
            ):
                require(raw[field] not in seen[bucket], f"duplicate {field}: {raw[field]}")
                seen[bucket].add(raw[field])
            require(isinstance(raw.get("approved_title"), str) and
                    raw["approved_title"].startswith(f"{tank} - "),
                    f"{tank}: approved title must retain exact tank prefix")
            parse_date(raw.get("arrival_date"), f"{tank} arrival_date")
            require(raw.get("quantity") == 1 and not isinstance(raw.get("quantity"), bool),
                    f"{tank}: quantity must be exactly 1")
            require(raw.get("inventory_reason") in {"received", "correction"},
                    f"{tank}: inventory_reason must be received or correction")
            require(isinstance(raw.get("write_authorised"), bool),
                    f"{tank}: write_authorised must be boolean")
            for role in ("hero", "original"):
                asset = raw.get(role)
                require(isinstance(asset, dict), f"{tank} {role}: asset object required")
                path = resolve_path(self.path.parent, asset.get("path"), f"{tank} {role}")
                digest = require_sha(asset.get("sha256"), f"{tank} {role}")
                require(asset.get("mime_type") in {"image/png", "image/jpeg"},
                        f"{tank} {role}: unsupported MIME type")
                require(path.is_file(), f"{tank} {role}: file missing")
                require(sha256_file(path) == digest, f"{tank} {role}: hash mismatch")
                asset["path"] = str(path)
            source_hash = raw["original"]["sha256"]
            require(source_hash not in seen["source"], f"duplicate source hash: {source_hash}")
            seen["source"].add(source_hash)
            for label, index in (
                ("approval", approval), ("snapshot", snapshot), ("details", details),
                ("label", labels), ("authority", authority),
            ):
                require(tank in index, f"{tank}: {label} evidence missing")
            self.contexts[tank] = self._build_context(
                raw, approval[tank], snapshot[tank], details[tank],
                labels[tank], authority[tank],
            )

    def _build_context(
        self,
        raw: dict[str, Any],
        approval: Mapping[str, Any],
        snapshot: Mapping[str, Any],
        details: Mapping[str, Any],
        label: Mapping[str, Any],
        authority: Mapping[str, Any],
    ) -> ItemContext:
        tank = raw["tank_id"]
        for manifest_key, approval_key in {
            "product_id": "product_id",
            "variant_id": "variant_id",
            "inventory_item_id": "inventory_item_id",
            "approved_title": "proposed_title",
            "arrival_date": "proposed_arrival_date",
            "quantity": "proposed_inventory",
        }.items():
            require(raw[manifest_key] == approval.get(approval_key),
                    f"{tank}: manifest/{approval_key} mismatch")
        for role in ("hero", "original"):
            require(raw[role]["sha256"] == approval.get(f"{role}_sha256"),
                    f"{tank}: {role} hash differs from approval")
            require(Path(raw[role]["path"]).resolve() ==
                    Path(approval.get(f"{role}_path", "")).resolve(),
                    f"{tank}: {role} path differs from approval")

        require(label.get("source_sha256") == raw["original"]["sha256"],
                f"{tank}: label/source hash mismatch")
        require(Path(label.get("source_path", "")).resolve() ==
                Path(raw["original"]["path"]).resolve(),
                f"{tank}: label/source path mismatch")
        require(label.get("photo_date") == raw["arrival_date"] and
                label.get("status") == "RECONCILED",
                f"{tank}: label date is not reconciled")

        require(authority.get("new_fish_authorised") is True and
                authority.get("intake_confirmed") is True,
                f"{tank}: new-fish authority missing")
        require(authority.get("source_sha256") == raw["original"]["sha256"],
                f"{tank}: authority hash mismatch")
        require(authority.get("source_reference") == raw.get("source_reference") ==
                approval.get("source_reference"),
                f"{tank}: authority reference mismatch")

        product = snapshot.get("product")
        require(isinstance(product, dict) and snapshot.get("status") == "PREFLIGHT_PASS",
                f"{tank}: protected snapshot did not pass")
        require(product.get("id") == raw["product_id"],
                f"{tank}: protected product ID mismatch")
        variants_connection = product.get("variants", {})
        variants = variants_connection.get("nodes", [])
        require(variants_connection.get("pageInfo", {}).get("hasNextPage") is False and
                len(variants) == 1, f"{tank}: protected variant is ambiguous/truncated")
        variant = variants[0]
        item = variant.get("inventoryItem") or {}
        require(variant.get("id") == raw["variant_id"],
                f"{tank}: protected variant ID mismatch")
        require(item.get("id") == raw["inventory_item_id"],
                f"{tank}: protected inventory-item ID mismatch")
        levels_connection = item.get("inventoryLevels", {})
        levels = levels_connection.get("nodes", [])
        require(levels_connection.get("pageInfo", {}).get("hasNextPage") is False,
                f"{tank}: protected inventory levels truncated")
        matched_levels = [
            level for level in levels
            if level.get("location", {}).get("id") == raw["location_id"]
        ]
        require(len(matched_levels) == 1 and
                snapshot.get("inventory_location", {}).get("id") == raw["location_id"],
                f"{tank}: exact inventory location missing/ambiguous")
        require(variant.get("inventoryPolicy") == "DENY" and item.get("tracked") is True,
                f"{tank}: inventory must be tracked with DENY policy")

        require(details.get("product_id") == raw["product_id"] and
                details.get("variant_id") == raw["variant_id"] and
                details.get("inventory_item_id") == raw["inventory_item_id"],
                f"{tank}: Shopify details identity mismatch")
        require(details.get("product_status") == product.get("status") == "ACTIVE",
                f"{tank}: product must be ACTIVE")
        require(numeric_equal(details.get("retail_price"), variant.get("price")) and
                numeric_equal(approval.get("retail_price_preserved"), variant.get("price")),
                f"{tank}: protected retail price mismatch")
        cost = item.get("unitCost") or {}
        require(numeric_equal(details.get("cost"), cost.get("amount")) and
                numeric_equal(approval.get("cost_preserved"), cost.get("amount")),
                f"{tank}: protected cost mismatch")

        media_connection = product.get("media", {})
        require(media_connection.get("pageInfo", {}).get("hasNextPage") is False,
                f"{tank}: protected media truncated")
        old_media_ids = [node.get("id") for node in media_connection.get("nodes", [])]
        require(all(GIDS["media_id"].fullmatch(value or "") for value in old_media_ids),
                f"{tank}: invalid protected media ID")
        quantities = {
            value.get("name"): value.get("quantity")
            for value in matched_levels[0].get("quantities", [])
        }
        require(quantities.get("available") == approval.get("existing_inventory"),
                f"{tank}: baseline quantity differs from approval")

        qa_record = raw.get("image_qa")
        require(isinstance(qa_record, dict), f"{tank}: image_qa object required")
        qa_path = resolve_path(self.path.parent, qa_record.get("path"), f"{tank} image QA")
        qa_digest = require_sha(qa_record.get("sha256"), f"{tank} image QA")
        require(qa_path.is_file() and sha256_file(qa_path) == qa_digest,
                f"{tank}: image-QA receipt missing/hash mismatch")
        qa = read_json(qa_path)
        require(qa.get("input_hashes") == [
            raw["original"]["sha256"], raw["hero"]["sha256"], raw["original"]["sha256"]
        ], f"{tank}: image-QA hashes do not bind source/hero/original")
        self._validate_qa(tank, qa, qa_digest, qa_record.get("exception"))

        protected = {
            "description_html": product.get("descriptionHtml"),
            "price": variant.get("price"),
            "cost": cost.get("amount"),
            "cost_currency": cost.get("currencyCode"),
            "vendor": details.get("vendor"),
            "product_type": details.get("product_type"),
            "handle": details.get("handle"),
            "status": product.get("status"),
            "inventory_policy": variant.get("inventoryPolicy"),
            "tracked": item.get("tracked"),
        }
        require(all(protected.get(field) is not None for field in PROTECTED_FIELDS),
                f"{tank}: incomplete protected-field evidence")
        baseline = {
            "title": approval.get("existing_title"),
            "arrival_date": approval.get("existing_arrival_date"),
            "available": approval.get("existing_inventory"),
            "old_media_ids": old_media_ids,
        }
        completion = self._validate_completion(raw, qa_digest)
        return ItemContext(
            self, raw, approval, snapshot, details, label, authority,
            qa, qa_digest, protected, baseline, completion,
        )

    @staticmethod
    def _validate_qa(tank: str, qa: Mapping[str, Any], digest: str, exception: Any) -> None:
        output = qa.get("output") or {}
        assertions = output.get("assertions") or {}
        require(isinstance(assertions, dict) and assertions,
                f"{tank}: image-QA assertions missing")
        if output.get("overall") == "PASS":
            require(all(value == "PASS" for value in assertions.values()),
                    f"{tank}: QA PASS conflicts with assertions")
            require(exception in (None, {}), f"{tank}: passing QA carries an exception")
            return
        require(output.get("overall") == "FAIL",
                f"{tank}: QA outcome must be PASS or explicit FAIL")
        require(isinstance(exception, dict) and exception.get("accepted") is True,
                f"{tank}: failed QA lacks explicit owner exception")
        require(exception.get("accepted_by") == "owner" and
                isinstance(exception.get("source_reference"), str) and
                exception["source_reference"],
                f"{tank}: QA exception authority/reference missing")
        require(exception.get("qa_receipt_sha256") == digest,
                f"{tank}: QA exception is not bound to its receipt")
        failed = sorted(key for key, value in assertions.items() if value == "FAIL")
        require(sorted(exception.get("failed_assertions", [])) == failed,
                f"{tank}: QA exception failed-assertion history mismatch")
        require(exception.get("original_reasons") == output.get("reasons", []),
                f"{tank}: QA exception reason history mismatch")

    def _validate_completion(self, raw: Mapping[str, Any], qa_digest: str) -> dict[str, Any] | None:
        completion = raw.get("completion_evidence")
        if completion is None:
            return None
        tank = raw["tank_id"]
        require(isinstance(completion, dict) and
                completion.get("status") == "FINAL_SHOPIFY_READBACK_PASS",
                f"{tank}: completion evidence is not final")
        media_ids = completion.get("media_ids")
        media_alts = completion.get("media_alts")
        require(isinstance(media_ids, list) and len(media_ids) == 2 and
                all(GIDS["media_id"].fullmatch(value or "") for value in media_ids),
                f"{tank}: completion requires exactly two valid media IDs")
        require(isinstance(media_alts, list) and len(media_alts) == 2 and
                all(isinstance(value, str) and value for value in media_alts),
                f"{tank}: completion requires exactly two media alts")
        receipts = completion.get("receipts")
        require(isinstance(receipts, list) and receipts,
                f"{tank}: completion receipts required")
        loaded: dict[str, Any] = {}
        for receipt in receipts:
            require(isinstance(receipt, dict), f"{tank}: invalid completion receipt")
            role = receipt.get("role")
            require(isinstance(role, str) and role and role not in loaded,
                    f"{tank}: duplicate/invalid completion role")
            path = resolve_path(self.path.parent, receipt.get("path"), f"{tank} {role}")
            digest = require_sha(receipt.get("sha256"), f"{tank} {role}")
            require(path.is_file() and sha256_file(path) == digest,
                    f"{tank}: completion receipt missing/hash mismatch: {role}")
            loaded[role] = read_json(path)
        require({"attachment", "reorder", "media", "details", "stock"} <= set(loaded),
                f"{tank}: incomplete final receipt set")
        require(loaded["attachment"].get("status") == "ATTACHMENT_REQUEST_ACCEPTED" and
                [entry.get("sha256") for entry in
                 loaded["attachment"].get("staged_hashes", [])] ==
                [raw["hero"]["sha256"], raw["original"]["sha256"]],
                f"{tank}: attachment receipt mismatch")
        require(loaded["reorder"].get("status") == "REORDER_REQUEST_ACCEPTED" and
                loaded["reorder"].get("expected_after", [])[:2] == media_ids,
                f"{tank}: reorder receipt mismatch")
        require(loaded["media"].get("status") == "FINAL_MEDIA_PASS" and
                loaded["media"].get("remaining_media_ids") == media_ids,
                f"{tank}: final media receipt mismatch")
        require(loaded["details"].get("status") == "DETAILS_READBACK_PASS" and
                loaded["details"].get("readback_title") == raw["approved_title"] and
                loaded["details"].get("readback_arrival_date") == raw["arrival_date"],
                f"{tank}: final details receipt mismatch")
        require(loaded["stock"].get("status") == "FINAL_SHOPIFY_READBACK_PASS" and
                loaded["stock"].get("product_id") == raw["product_id"] and
                loaded["stock"].get("inventory_item_id") == raw["inventory_item_id"] and
                loaded["stock"].get("location_id") == raw["location_id"] and
                loaded["stock"].get("final_available_quantity") == raw["quantity"],
                f"{tank}: final inventory receipt mismatch")
        return {**completion, "loaded_receipts": loaded, "qa_receipt_sha256": qa_digest}

    def select(self, tanks: Iterable[str] | None = None) -> list[ItemContext]:
        if not tanks:
            return [self.contexts[key] for key in sorted(self.contexts)]
        result: list[ItemContext] = []
        seen: set[str] = set()
        for group in tanks:
            for raw in str(group).split(","):
                tank = raw.strip().upper()
                require(tank in self.contexts, f"unknown --tank: {tank}")
                if tank not in seen:
                    result.append(self.contexts[tank])
                    seen.add(tank)
        return result


class StateStore:
    """Atomic working checkpoint plus immutable event/receipt files."""

    def __init__(self, bundle: ManifestBundle):
        self.bundle = bundle
        self.root = bundle.state_dir
        self.path = self.root / "state.json"
        self.events_dir = self.root / "events"
        self.receipts_dir = self.root / "receipts"
        self.secrets_dir = self.root / "secrets"
        for directory in (
            self.root, self.events_dir, self.receipts_dir,
            self.secrets_dir, bundle.report_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(directory, 0o700)
            except OSError:
                pass
        if self.path.exists():
            self.data = read_json(self.path)
            self._validate_existing()
        else:
            created = utc_now()
            self.data = {
                "schema": STATE_SCHEMA,
                "batch_id": bundle.batch_id,
                "manifest_path": str(bundle.path),
                "manifest_sha256": bundle.sha256,
                "created_at": created,
                "updated_at": created,
                "event_seq": 0,
                "items": {
                    tank: {
                        "stage": "NEW",
                        "status": "PENDING",
                        "history": [{"stage": "NEW", "at": created}],
                        "mutation_history": [],
                        "pending_mutation": None,
                        "pending_transfer": None,
                        "telemetry": {
                            "started_at": created,
                            "completed_at": None,
                            "read_calls": 0,
                            "write_calls": 0,
                            "write_rejections": 0,
                            "uncertain_writes": 0,
                            "media_poll_reads": 0,
                        },
                    }
                    for tank in bundle.contexts
                },
            }
            atomic_write_json(self.path, self.data)

    def _validate_existing(self) -> None:
        require(self.data.get("schema") == STATE_SCHEMA, "state schema mismatch")
        require(self.data.get("batch_id") == self.bundle.batch_id,
                "state batch_id mismatch")
        require(self.data.get("manifest_sha256") == self.bundle.sha256,
                "state belongs to a different manifest digest")
        require(Path(self.data.get("manifest_path", "")).resolve() == self.bundle.path,
                "state manifest path mismatch")
        require(set(self.data.get("items", {})) == set(self.bundle.contexts),
                "state/manifest tank set mismatch")
        events = sorted(self.events_dir.glob("*.json"))
        if events:
            match = re.match(r"^(\d+)-", events[-1].name)
            require(match is not None and
                    int(match.group(1)) == self.data.get("event_seq"),
                    "state/event journal divergence; inspect before continuing")

    def item(self, tank: str) -> dict[str, Any]:
        return self.data["items"][tank]

    def _commit(
        self, tank: str, event_type: str,
        details: Mapping[str, Any] | None = None,
    ) -> Path:
        self.data["event_seq"] += 1
        self.data["updated_at"] = utc_now()
        sequence = self.data["event_seq"]
        event = {
            "schema": "nta-betta-shopify-event-v1",
            "sequence": sequence,
            "at": self.data["updated_at"],
            "batch_id": self.bundle.batch_id,
            "manifest_sha256": self.bundle.sha256,
            "tank_id": tank,
            "event": event_type,
            "details": dict(details or {}),
        }
        safe_type = re.sub(r"[^a-z0-9_-]+", "-", event_type.lower()).strip("-")
        path = self.events_dir / (
            f"{sequence:06d}-{safe_timestamp()}-{safe_type}.json"
        )
        write_json_exclusive(path, event)
        atomic_write_json(self.path, self.data)
        return path

    def transition(
        self, tank: str, target: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        record = self.item(tank)
        current = record["stage"]
        if current == "BLOCKED":
            raise BatchError(f"{tank}: blocked state cannot advance automatically")
        require(target in STAGE_ORDER, f"{tank}: unknown target stage {target}")
        if current in STAGE_ORDER:
            require(STAGE_ORDER[target] >= STAGE_ORDER[current],
                    f"{tank}: illegal state regression {current} -> {target}")
        if target == current:
            return
        timestamp = utc_now()
        record["stage"] = target
        record["status"] = (
            "COMPLETE" if target in {"VERIFIED", "COMPLETED_VERIFIED"}
            else "IN_PROGRESS"
        )
        record["history"].append({"stage": target, "at": timestamp})
        if target in {"VERIFIED", "COMPLETED_VERIFIED"}:
            record["telemetry"]["completed_at"] = timestamp
        self._commit(
            tank, "state_transition",
            {"from": current, "to": target, **dict(details or {})},
        )

    def record_preflight(self, tank: str, snapshot: Mapping[str, Any]) -> None:
        self.item(tank)["preflight"] = dict(snapshot)
        self._commit(tank, "preflight_captured", {
            "product_id": snapshot.get("product_id"),
            "variant_id": snapshot.get("variant_id"),
            "inventory_item_id": snapshot.get("inventory_item_id"),
            "location_id": snapshot.get("location_id"),
            "available": snapshot.get("available"),
            "old_media_ids": snapshot.get("old_media_ids", []),
            "protected_sha256": snapshot.get("protected_sha256"),
        })
        self.transition(tank, "PREFLIGHTED")

    def increment_read(self, tank: str, media_poll: bool = False) -> None:
        telemetry = self.item(tank)["telemetry"]
        telemetry["read_calls"] += 1
        if media_poll:
            telemetry["media_poll_reads"] += 1
        atomic_write_json(self.path, self.data)

    def set_fields(self, tank: str, event: str, **fields: Any) -> None:
        record = self.item(tank)
        record.update(fields)
        details = {
            key: value for key, value in fields.items()
            if key not in {"staging_secret"}
        }
        self._commit(tank, event, details)

    def record_intent(
        self,
        tank: str,
        operation: str,
        variables: Mapping[str, Any],
        guard: Mapping[str, Any] | None = None,
    ) -> str:
        require(operation in WRITE_OPERATIONS,
                f"{tank}: unsupported mutation operation")
        record = self.item(tank)
        require(record.get("pending_mutation") is None,
                f"{tank}: unresolved mutation intent already exists")
        intent_id = str(uuid.uuid4())
        pending = {
            "intent_id": intent_id,
            "operation": operation,
            "variables_sha256": json_sha256(variables),
            "recorded_at": utc_now(),
            "status": "INTENT_RECORDED",
            "guard": dict(guard or {}),
        }
        record["pending_mutation"] = pending
        record["telemetry"]["write_calls"] += 1
        self._commit(tank, "mutation_intent", {
            "intent_id": intent_id,
            "operation": operation,
            "variables_sha256": pending["variables_sha256"],
        })
        return intent_id

    def complete_intent(
        self, tank: str, outcome: str,
        summary: Mapping[str, Any] | None = None,
    ) -> None:
        record = self.item(tank)
        pending = record.get("pending_mutation")
        require(isinstance(pending, dict),
                f"{tank}: no mutation intent to complete")
        completed = {
            **pending,
            "status": outcome,
            "completed_at": utc_now(),
            "summary": dict(summary or {}),
        }
        record["mutation_history"].append(completed)
        record["pending_mutation"] = None
        if outcome == "REJECTED":
            record["telemetry"]["write_rejections"] += 1
        self._commit(tank, "mutation_outcome", {
            "intent_id": completed["intent_id"],
            "operation": completed["operation"],
            "outcome": outcome,
            "summary": dict(summary or {}),
        })

    def mark_uncertain(self, tank: str, reason: str) -> None:
        record = self.item(tank)
        pending = record.get("pending_mutation")
        require(isinstance(pending, dict),
                f"{tank}: no mutation intent to mark uncertain")
        pending.update({
            "status": "UNCERTAIN",
            "uncertain_at": utc_now(),
            "reason": reason,
        })
        record["status"] = "UNCERTAIN"
        record["telemetry"]["uncertain_writes"] += 1
        self._commit(tank, "mutation_uncertain", {
            "intent_id": pending["intent_id"],
            "operation": pending["operation"],
            "reason": reason,
        })

    def start_transfer(self, tank: str, role: str, digest: str) -> None:
        record = self.item(tank)
        require(record.get("pending_transfer") is None,
                f"{tank}: unresolved staged transfer exists")
        record["pending_transfer"] = {
            "role": role,
            "sha256": digest,
            "started_at": utc_now(),
            "status": "UNCERTAIN_UNTIL_ACKNOWLEDGED",
        }
        self._commit(tank, "staged_transfer_intent", {
            "role": role, "sha256": digest,
        })

    def finish_transfer(self, tank: str, role: str) -> None:
        record = self.item(tank)
        pending = record.get("pending_transfer")
        require(isinstance(pending, dict) and pending.get("role") == role,
                f"{tank}: staged-transfer intent mismatch")
        transferred = list(record.get("staged_transfers", []))
        if role not in transferred:
            transferred.append(role)
        record["staged_transfers"] = transferred
        record["pending_transfer"] = None
        self._commit(tank, "staged_transfer_complete", {"role": role})

    def block(self, tank: str, reason: str) -> None:
        record = self.item(tank)
        if record["stage"] in {"VERIFIED", "COMPLETED_VERIFIED"}:
            return
        previous = record["stage"]
        record.update({
            "stage": "BLOCKED",
            "status": "BLOCKED",
            "last_error": reason,
        })
        record["history"].append({
            "stage": "BLOCKED", "at": utc_now(), "reason": reason,
        })
        self._commit(tank, "blocked", {"from": previous, "reason": reason})

    def write_secret(self, tank: str, intent_id: str, value: Any) -> Path:
        path = self.secrets_dir / f"{tank}-{intent_id}.json"
        write_json_exclusive(path, value, 0o600)
        return path

    def write_receipt(self, tank: str, value: Any) -> Path:
        path = self.receipts_dir / f"{tank}-{safe_timestamp()}-final.json"
        write_json_exclusive(path, value)
        return path

    def write_report(self, command: str, value: Any) -> Path:
        path = self.bundle.report_dir / (
            f"{self.bundle.batch_id}-{safe_timestamp()}-{command}.json"
        )
        write_json_exclusive(path, value)
        return path


class ShopifyGateway(Protocol):
    def read_product(self, product_id: str, location_id: str) -> dict[str, Any]: ...

    def write(
        self,
        operation: str,
        variables: Mapping[str, Any],
        approval: Mapping[str, Any],
    ) -> dict[str, Any]: ...


def normalize_shopify_product(
    data: Mapping[str, Any], location_id: str,
) -> dict[str, Any]:
    product = data.get("product")
    if not isinstance(product, dict):
        raise ShopifyReadError("Shopify product was not found")
    variants_connection = product.get("variants") or {}
    variants = variants_connection.get("nodes", [])
    if variants_connection.get("pageInfo", {}).get("hasNextPage") is not False:
        raise ShopifyReadError("Shopify variant read is truncated")
    if len(variants) != 1:
        raise ShopifyReadError("individual Betta must have exactly one variant")
    variant = variants[0]
    inventory_item = variant.get("inventoryItem") or {}
    levels_connection = inventory_item.get("inventoryLevels") or {}
    if levels_connection.get("pageInfo", {}).get("hasNextPage") is not False:
        raise ShopifyReadError("Shopify inventory-level read is truncated")
    levels = [
        level for level in levels_connection.get("nodes", [])
        if level.get("location", {}).get("id") == location_id
    ]
    if len(levels) != 1:
        raise ShopifyReadError("exact inventory location is missing/ambiguous")
    quantities = {
        value.get("name"): value.get("quantity")
        for value in levels[0].get("quantities", [])
    }
    media_connection = product.get("media") or {}
    if media_connection.get("pageInfo", {}).get("hasNextPage") is not False:
        raise ShopifyReadError("Shopify media read is truncated")
    media = [{
        "id": node.get("id"),
        "alt": node.get("alt"),
        "status": node.get("status"),
        "media_content_type": node.get("mediaContentType"),
        "url": (node.get("image") or {}).get("url"),
    } for node in media_connection.get("nodes", [])]
    description = product.get("descriptionHtml")
    if not isinstance(description, str):
        raise ShopifyReadError("Shopify descriptionHtml is missing")
    cost = inventory_item.get("unitCost") or {}
    metafield = product.get("metafield") or {}
    return {
        "read_at": utc_now(),
        "source": "FRESH_SHOPIFY_READ",
        "product_id": product.get("id"),
        "title": product.get("title"),
        "status": product.get("status"),
        "description_html": description,
        "description_sha256": hashlib.sha256(description.encode()).hexdigest(),
        "handle": product.get("handle"),
        "vendor": product.get("vendor"),
        "product_type": product.get("productType"),
        "arrival_date": metafield.get("value"),
        "arrival_date_type": metafield.get("type"),
        "media": media,
        "variant_id": variant.get("id"),
        "price": variant.get("price"),
        "inventory_quantity": variant.get("inventoryQuantity"),
        "inventory_policy": variant.get("inventoryPolicy"),
        "inventory_item_id": inventory_item.get("id"),
        "tracked": inventory_item.get("tracked"),
        "cost": cost.get("amount"),
        "cost_currency": cost.get("currencyCode"),
        "location_id": levels[0].get("location", {}).get("id"),
        "location_name": levels[0].get("location", {}).get("name"),
        "available": quantities.get("available"),
        "on_hand": quantities.get("on_hand"),
        "committed": quantities.get("committed"),
    }


def load_dotenv(path: Path, environment: dict[str, str]) -> None:
    """Load dotenv values without printing or returning secrets."""
    if not path.is_file():
        raise BatchError(f"environment file missing: {path}")
    for number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise BatchError(f"invalid environment-file line {number}")
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise BatchError(f"invalid environment name on line {number}")
        value = raw_value.strip()
        if value:
            try:
                parsed = shlex.split(value, posix=True)
            except ValueError as exc:
                raise BatchError(
                    f"invalid quoted environment value on line {number}"
                ) from exc
            value = parsed[0] if len(parsed) == 1 else value
        environment.setdefault(key, value)


def resolve_node_binary(explicit: str | None = None) -> str:
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    if os.environ.get("NTA_SHOPIFY_NODE"):
        candidates.append(os.environ["NTA_SHOPIFY_NODE"])
    if shutil.which("node"):
        candidates.append(shutil.which("node") or "")
    candidates.extend(["/opt/homebrew/bin/node", "/usr/local/bin/node"])
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            result = subprocess.run(
                [candidate, "--version"], text=True, capture_output=True,
                timeout=5, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        match = re.search(r"v(\d+)", result.stdout)
        if result.returncode == 0 and match and int(match.group(1)) >= 18:
            return candidate
    raise BatchError("Node.js 18+ is required for the Shopify bridge")


class BridgeClient:
    RETRYABLE_READ_ERRORS = {
        "offline_refresh_in_progress", "offline_refresh_retryable",
    }

    def __init__(
        self,
        bridge_path: Path,
        node_binary: str,
        environment: Mapping[str, str] | None = None,
        read_attempts: int = 4,
        sleep: Callable[[float], None] = time.sleep,
        live: bool = False,
        approved_manifest: Path | None = None,
        approved_sha256: str | None = None,
    ):
        self.bridge_path = bridge_path.expanduser().resolve()
        if not self.bridge_path.is_file():
            raise BatchError(f"Shopify bridge missing: {self.bridge_path}")
        self.node_binary = node_binary
        self.environment = dict(os.environ)
        self.environment.update(environment or {})
        self.read_attempts = max(1, int(read_attempts))
        self.sleep = sleep
        self.live = live
        if live:
            require(approved_manifest is not None and approved_sha256 is not None,
                    "live bridge requires manifest binding")
            self.environment["NTA_BETTA_BATCH_WRITE_ENABLED"] = "true"
            self.environment["NTA_BETTA_BATCH_APPROVED_MANIFEST"] = str(
                approved_manifest
            )
            self.environment["NTA_BETTA_BATCH_APPROVED_SHA256"] = approved_sha256
        else:
            for key in (
                "NTA_BETTA_BATCH_WRITE_ENABLED",
                "NTA_BETTA_BATCH_APPROVED_MANIFEST",
                "NTA_BETTA_BATCH_APPROVED_SHA256",
            ):
                self.environment.pop(key, None)

    def _invoke(
        self,
        operation: str,
        variables: Mapping[str, Any],
        approval: Mapping[str, Any] | None,
        write: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "operation": operation, "variables": dict(variables),
        }
        if approval is not None:
            payload["approval"] = dict(approval)
        attempts = 1 if write else self.read_attempts
        last_errors: list[str] = []
        for attempt in range(attempts):
            try:
                completed = subprocess.run(
                    [self.node_binary, str(self.bridge_path)],
                    input=json.dumps(payload),
                    text=True,
                    capture_output=True,
                    timeout=60 if write else 35,
                    cwd=self.bridge_path.parent.parent,
                    env=self.environment,
                    check=False,
                )
            except (subprocess.TimeoutExpired, OSError) as exc:
                if write:
                    raise UncertainWriteError(
                        f"{operation}: bridge transport outcome is uncertain"
                    ) from exc
                last_errors = ["bridge_transport_failed"]
            else:
                try:
                    response = json.loads(completed.stdout)
                except json.JSONDecodeError as exc:
                    if write:
                        raise UncertainWriteError(
                            f"{operation}: bridge returned no safe receipt"
                        ) from exc
                    response = {
                        "ok": False, "errors": ["bridge_response_invalid"],
                    }
                if response.get("ok") is True:
                    return response
                last_errors = [
                    str(value) for value in response.get("errors", [])
                ] or ["bridge_failed"]
                retryable = any(
                    error in self.RETRYABLE_READ_ERRORS or
                    error == "http:429" or error.startswith("http:5")
                    for error in last_errors
                )
                if write:
                    known = all(
                        error.startswith("betta_batch_") and any(
                            token in error for token in (
                                "disabled", "invalid", "not_authorised", "scope",
                            )
                        )
                        for error in last_errors
                    )
                    if known:
                        raise ShopifyWriteRejected(
                            f"{operation}: {', '.join(last_errors)}"
                        )
                    raise UncertainWriteError(
                        f"{operation}: Shopify outcome is uncertain"
                    )
                if not retryable:
                    break
            if attempt + 1 < attempts:
                self.sleep(min(2 ** attempt, 8))
        raise ShopifyReadError(f"{operation}: {', '.join(last_errors)}")

    def read_product(self, product_id: str, location_id: str) -> dict[str, Any]:
        response = self._invoke(
            "betta_batch_product", {"id": product_id}, None, False,
        )
        return normalize_shopify_product(
            response.get("data") or {}, location_id,
        )

    def write(
        self,
        operation: str,
        variables: Mapping[str, Any],
        approval: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not self.live:
            raise ShopifyWriteRejected("live Shopify writes are disabled")
        response = self._invoke(operation, variables, approval, True)
        return response.get("data") or {}


def upload_staged_file(
    target: Mapping[str, Any], asset: Mapping[str, Any],
) -> None:
    """POST one staged upload without logging signed parameters or URLs."""
    target_url = target.get("url")
    resource_url = target.get("resourceUrl")
    parameters = target.get("parameters")
    if not isinstance(target_url, str) or (
        urllib.parse.urlparse(target_url).scheme != "https"
    ):
        raise DeferredError("invalid Shopify staged-upload target")
    if not isinstance(resource_url, str) or (
        urllib.parse.urlparse(resource_url).scheme != "https"
    ):
        raise DeferredError("invalid Shopify staged resource URL")
    if not isinstance(parameters, list):
        raise DeferredError("missing Shopify staged-upload parameters")
    file_path = Path(asset["path"])
    boundary = f"----nta-betta-{uuid.uuid4().hex}"
    body = bytearray()
    for parameter in parameters:
        name = parameter.get("name")
        value = parameter.get("value")
        if not isinstance(name, str) or not isinstance(value, str):
            raise DeferredError("invalid staged-upload parameter")
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        )
        body.extend(value.encode())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}\r\n".encode())
    body.extend((
        f'Content-Disposition: form-data; name="file"; '
        f'filename="{file_path.name}"\r\n'
    ).encode())
    body.extend(f"Content-Type: {asset['mime_type']}\r\n\r\n".encode())
    body.extend(file_path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        target_url,
        data=bytes(body),
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            if not 200 <= response.status < 300:
                raise DeferredError(
                    f"staged upload returned HTTP {response.status}"
                )
    except (urllib.error.URLError, TimeoutError) as exc:
        raise DeferredError(
            "staged upload outcome is uncertain; do not replay automatically"
        ) from exc


def protected_fingerprint(ctx: ItemContext, live: Mapping[str, Any]) -> str:
    return json_sha256({
        "description_sha256": live.get("description_sha256"),
        "price": str(live.get("price")),
        "cost": str(live.get("cost")),
        "cost_currency": live.get("cost_currency"),
        "vendor": live.get("vendor"),
        "product_type": live.get("product_type"),
        "handle": live.get("handle"),
        "status": live.get("status"),
        "inventory_policy": live.get("inventory_policy"),
        "tracked": live.get("tracked"),
    })


def assert_identity_and_protected(
    ctx: ItemContext, live: Mapping[str, Any],
) -> None:
    tank = ctx.tank_id
    expected_ids = {
        "product_id": ctx.product_id,
        "variant_id": ctx.variant_id,
        "inventory_item_id": ctx.inventory_item_id,
        "location_id": ctx.location_id,
    }
    for field, expected in expected_ids.items():
        if live.get(field) != expected:
            raise BatchError(
                f"{tank}: fresh Shopify {field} mismatch "
                f"(expected {expected}, got {live.get(field)})"
            )
    expected = ctx.protected
    if live.get("description_html") != expected["description_html"]:
        raise BatchError(f"{tank}: protected description changed")
    for field in ("price", "cost"):
        if not numeric_equal(live.get(field), expected[field]):
            raise BatchError(f"{tank}: protected {field} changed")
    for field in ("cost_currency", "vendor", "product_type", "handle", "status"):
        if live.get(field) != expected[field]:
            raise BatchError(f"{tank}: protected {field} changed")
    if live.get("inventory_policy") != "DENY":
        raise BatchError(f"{tank}: inventory policy is no longer DENY")
    if live.get("tracked") is not True:
        raise BatchError(f"{tank}: inventory tracking is no longer enabled")
    if live.get("status") != "ACTIVE":
        raise BatchError(f"{tank}: product is no longer ACTIVE")


def final_assertions(
    ctx: ItemContext,
    live: Mapping[str, Any],
    state_item: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    checks: dict[str, tuple[bool, Any, Any]] = {}

    def add(name: str, passed: bool, expected: Any, actual: Any) -> None:
        checks[name] = (bool(passed), expected, actual)

    add("fresh_source", live.get("source") == "FRESH_SHOPIFY_READ",
        "FRESH_SHOPIFY_READ", live.get("source"))
    for field, expected in (
        ("product_id", ctx.product_id),
        ("variant_id", ctx.variant_id),
        ("inventory_item_id", ctx.inventory_item_id),
        ("location_id", ctx.location_id),
    ):
        add(field, live.get(field) == expected, expected, live.get(field))
    add("title", live.get("title") == ctx.title, ctx.title, live.get("title"))
    add("arrival_date", live.get("arrival_date") == ctx.arrival_date,
        ctx.arrival_date, live.get("arrival_date"))
    add("arrival_date_type", live.get("arrival_date_type") == "date",
        "date", live.get("arrival_date_type"))
    add("available_inventory", live.get("available") == ctx.quantity,
        ctx.quantity, live.get("available"))
    add("aggregate_inventory", live.get("inventory_quantity") == ctx.quantity,
        ctx.quantity, live.get("inventory_quantity"))
    add("inventory_policy", live.get("inventory_policy") == "DENY",
        "DENY", live.get("inventory_policy"))
    add("inventory_tracking", live.get("tracked") is True,
        True, live.get("tracked"))
    add("status", live.get("status") == ctx.protected["status"],
        ctx.protected["status"], live.get("status"))
    add("description", live.get("description_html") == ctx.protected["description_html"],
        hashlib.sha256(ctx.protected["description_html"].encode()).hexdigest(),
        live.get("description_sha256"))
    for field in ("price", "cost"):
        add(field, numeric_equal(live.get(field), ctx.protected[field]),
            str(ctx.protected[field]), str(live.get(field)))
    for field in ("cost_currency", "vendor", "product_type", "handle"):
        add(field, live.get(field) == ctx.protected[field],
            ctx.protected[field], live.get(field))

    for role in ("hero", "original"):
        asset = ctx.asset(role)
        path = Path(asset["path"])
        actual_hash = sha256_file(path) if path.is_file() else None
        add(f"{role}_local_hash", actual_hash == asset["sha256"],
            asset["sha256"], actual_hash)

    media = live.get("media", [])
    if ctx.completion and state_item.get("stage") == "COMPLETED_VERIFIED":
        expected_ids = ctx.completion["media_ids"]
        expected_alts = ctx.completion["media_alts"]
    elif ctx.completion and not state_item.get("uploaded_media"):
        expected_ids = ctx.completion["media_ids"]
        expected_alts = ctx.completion["media_alts"]
    else:
        uploaded = state_item.get("uploaded_media") or {}
        expected_ids = [
            uploaded.get("hero", {}).get("id"),
            uploaded.get("original", {}).get("id"),
        ]
        expected_alts = [ctx.expected_alt("hero"), ctx.expected_alt("original")]
    actual_ids = [value.get("id") for value in media]
    actual_alts = [value.get("alt") for value in media]
    actual_statuses = [value.get("status") for value in media]
    add("media_count", len(media) == 2, 2, len(media))
    add("media_order", actual_ids == expected_ids, expected_ids, actual_ids)
    add("media_identity", actual_alts == expected_alts, expected_alts, actual_alts)
    add("media_ready", actual_statuses == ["READY", "READY"],
        ["READY", "READY"], actual_statuses)

    result: dict[str, dict[str, Any]] = {}
    for name, (passed, expected, actual) in checks.items():
        result[name] = {
            "status": "PASS" if passed else "FAIL",
            "expected": expected,
            "actual": actual,
        }
    return result


def assertions_pass(assertions: Mapping[str, Mapping[str, Any]]) -> bool:
    return bool(assertions) and all(
        value.get("status") == "PASS" for value in assertions.values()
    )


def receipt_user_errors(node: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(node, dict):
        return [{"field": [], "message": "mutation response missing"}]
    errors = node.get(field)
    return errors if isinstance(errors, list) else [
        {"field": [], "message": f"{field} missing from mutation response"}
    ]


class BatchUploader:
    def __init__(
        self,
        bundle: ManifestBundle,
        gateway: ShopifyGateway,
        state: StateStore,
        sleep: Callable[[float], None] = time.sleep,
        upload: Callable[[Mapping[str, Any], Mapping[str, Any]], None] = upload_staged_file,
        poll_attempts: int = 30,
        poll_interval: float = 2.0,
    ):
        self.bundle = bundle
        self.gateway = gateway
        self.state = state
        self.sleep = sleep
        self.upload = upload
        self.poll_attempts = max(1, int(poll_attempts))
        self.poll_interval = max(0.0, float(poll_interval))

    def _read(self, ctx: ItemContext, media_poll: bool = False) -> dict[str, Any]:
        live = self.gateway.read_product(ctx.product_id, ctx.location_id)
        self.state.increment_read(ctx.tank_id, media_poll)
        assert_identity_and_protected(ctx, live)
        return live

    def _approval(self, ctx: ItemContext) -> dict[str, Any]:
        return {
            "manifestPath": str(self.bundle.path),
            "manifestSha256": self.bundle.sha256,
            "statePath": str(self.state.path),
            "stateSha256": sha256_file(self.state.path),
            "batchId": self.bundle.batch_id,
            "tankId": ctx.tank_id,
        }

    def _write(
        self,
        ctx: ItemContext,
        operation: str,
        variables: Mapping[str, Any],
        payload_key: str,
        error_field: str,
        guard: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        intent_id = self.state.record_intent(
            ctx.tank_id, operation, variables, guard,
        )
        try:
            data = self.gateway.write(
                operation, variables, self._approval(ctx),
            )
        except ShopifyWriteRejected as exc:
            self.state.complete_intent(
                ctx.tank_id, "REJECTED", {"error": str(exc)},
            )
            raise
        except UncertainWriteError as exc:
            self.state.mark_uncertain(ctx.tank_id, str(exc))
            raise
        node = data.get(payload_key)
        if not isinstance(node, dict):
            self.state.mark_uncertain(
                ctx.tank_id, f"{operation}: mutation receipt missing",
            )
            raise UncertainWriteError(
                f"{ctx.tank_id}: {operation} returned no mutation receipt"
            )
        errors = receipt_user_errors(node, error_field)
        if errors:
            messages = [
                str(error.get("message", "Shopify user error"))
                for error in errors
            ]
            self.state.complete_intent(
                ctx.tank_id, "REJECTED",
                {"user_errors": messages},
            )
            raise ShopifyWriteRejected(
                f"{ctx.tank_id}: {operation} rejected: {'; '.join(messages)}"
            )
        self.state.complete_intent(
            ctx.tank_id, "ACCEPTED",
            {"payload": payload_key},
        )
        return node, intent_id

    def _preflight_snapshot(
        self, ctx: ItemContext, live: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "captured_at": utc_now(),
            "source": "FRESH_SHOPIFY_READ",
            "product_id": live["product_id"],
            "variant_id": live["variant_id"],
            "inventory_item_id": live["inventory_item_id"],
            "location_id": live["location_id"],
            "title": live["title"],
            "arrival_date": live["arrival_date"],
            "available": live["available"],
            "inventory_quantity": live["inventory_quantity"],
            "old_media_ids": [value["id"] for value in live["media"]],
            "protected_sha256": protected_fingerprint(ctx, live),
            "description_sha256": live["description_sha256"],
            "price": live["price"],
            "cost": live["cost"],
            "inventory_policy": live["inventory_policy"],
            "tracked": live["tracked"],
        }

    def _assert_initial_baseline(
        self, ctx: ItemContext, live: Mapping[str, Any],
    ) -> None:
        expected = ctx.baseline
        if live.get("title") != expected["title"]:
            raise BatchError(f"{ctx.tank_id}: title changed since approval")
        if live.get("arrival_date") != expected["arrival_date"]:
            raise BatchError(
                f"{ctx.tank_id}: arrival date changed since approval"
            )
        if live.get("available") != expected["available"]:
            raise BatchError(
                f"{ctx.tank_id}: stock changed since approval "
                f"({expected['available']} -> {live.get('available')})"
            )
        if live.get("inventory_quantity") != expected["available"]:
            raise BatchError(
                f"{ctx.tank_id}: aggregate stock changed since approval "
                f"({expected['available']} -> "
                f"{live.get('inventory_quantity')})"
            )
        current_media = [value.get("id") for value in live.get("media", [])]
        if current_media != expected["old_media_ids"]:
            raise BatchError(
                f"{ctx.tank_id}: media changed since protected preflight"
            )

    def preflight_one(self, ctx: ItemContext) -> dict[str, Any]:
        record = self.state.item(ctx.tank_id)
        live = self._read(ctx)
        if ctx.completion:
            assertions = final_assertions(ctx, live, record)
            if assertions_pass(assertions):
                if record["stage"] == "NEW":
                    self.state.record_preflight(
                        ctx.tank_id, self._preflight_snapshot(ctx, live),
                    )
                if self.state.item(ctx.tank_id)["stage"] != "COMPLETED_VERIFIED":
                    self.state.transition(
                        ctx.tank_id, "COMPLETED_VERIFIED",
                        {"completion_evidence": "independently_reverified"},
                    )
                self._write_final_receipt(
                    ctx, live, assertions, "COMPLETED_VERIFIED",
                )
                return {
                    "tank_id": ctx.tank_id,
                    "status": "COMPLETED_VERIFIED",
                    "shopify_writes": 0,
                    "assertions": assertions,
                }
            raise BatchError(
                f"{ctx.tank_id}: completed receipt exists but fresh final "
                "Shopify readback does not pass"
            )

        if record["stage"] in {"VERIFIED", "COMPLETED_VERIFIED"}:
            assertions = final_assertions(ctx, live, record)
            if not assertions_pass(assertions):
                raise BatchError(
                    f"{ctx.tank_id}: prior completion no longer verifies"
                )
            return {
                "tank_id": ctx.tank_id,
                "status": record["stage"],
                "shopify_writes": 0,
                "assertions": assertions,
            }

        if record["stage"] == "NEW":
            self._assert_initial_baseline(ctx, live)
            self.state.record_preflight(
                ctx.tank_id, self._preflight_snapshot(ctx, live),
            )
        elif record["stage"] != "BLOCKED":
            if record["stage"] == "PREFLIGHTED":
                self._assert_initial_baseline(ctx, live)
            preflight = record.get("preflight") or {}
            for field, expected in (
                ("product_id", ctx.product_id),
                ("variant_id", ctx.variant_id),
                ("inventory_item_id", ctx.inventory_item_id),
                ("location_id", ctx.location_id),
            ):
                if preflight.get(field) != expected:
                    raise BatchError(
                        f"{ctx.tank_id}: persisted preflight {field} mismatch"
                    )
        return {
            "tank_id": ctx.tank_id,
            "status": self.state.item(ctx.tank_id)["stage"],
            "shopify_writes": 0,
            "live": {
                "title": live["title"],
                "arrival_date": live["arrival_date"],
                "available": live["available"],
                "media_ids": [value["id"] for value in live["media"]],
            },
        }

    def preflight_all(
        self, contexts: Iterable[ItemContext],
    ) -> list[dict[str, Any]]:
        results = []
        for ctx in contexts:
            try:
                results.append(self.preflight_one(ctx))
            except BatchError as exc:
                self.state.block(ctx.tank_id, str(exc))
                results.append({
                    "tank_id": ctx.tank_id,
                    "status": "BLOCKED",
                    "error": str(exc),
                    "shopify_writes": 0,
                })
        return results

    def proposed_change(self, ctx: ItemContext) -> dict[str, Any]:
        record = self.state.item(ctx.tank_id)
        exception = (ctx.raw.get("image_qa") or {}).get("exception")
        if record["stage"] == "COMPLETED_VERIFIED":
            return {
                "tank_id": ctx.tank_id,
                "action": "SKIP_ALREADY_COMPLETED",
                "completion_status": "FINAL_SHOPIFY_READBACK_PASS",
                "verified_live": True,
                "writes": [],
                "qa_exception": exception,
            }
        preflight = record.get("preflight") or {}
        return {
            "tank_id": ctx.tank_id,
            "action": "PROPOSED_LIVE_UPDATE",
            "product_id": ctx.product_id,
            "variant_id": ctx.variant_id,
            "inventory_item_id": ctx.inventory_item_id,
            "location_id": ctx.location_id,
            "title": {
                "from": preflight.get("title", ctx.baseline["title"]),
                "to": ctx.title,
            },
            "arrival_date": {
                "from": preflight.get(
                    "arrival_date", ctx.baseline["arrival_date"]
                ),
                "to": ctx.arrival_date,
            },
            "available_inventory": {
                "from": preflight.get(
                    "available", ctx.baseline["available"]
                ),
                "to": ctx.quantity,
                "compare_and_set": True,
            },
            "media": {
                "delete_only_preflight_ids": preflight.get(
                    "old_media_ids", ctx.baseline["old_media_ids"]
                ),
                "new_order": [
                    {
                        "role": "HERO",
                        "path": ctx.asset("hero")["path"],
                        "sha256": ctx.asset("hero")["sha256"],
                    },
                    {
                        "role": "ORIGINAL",
                        "path": ctx.asset("original")["path"],
                        "sha256": ctx.asset("original")["sha256"],
                    },
                ],
            },
            "protected_fields": "UNCHANGED",
            "qa_exception": exception,
        }

    def dry_run(
        self, contexts: list[ItemContext], command: str = "dry-run",
    ) -> dict[str, Any]:
        results = self.preflight_all(contexts)
        proposals = [
            self.proposed_change(ctx)
            for ctx in contexts
            if self.state.item(ctx.tank_id)["stage"] != "BLOCKED"
        ]
        blocked = [
            result for result in results if result["status"] == "BLOCKED"
        ]
        report = {
            "schema": REPORT_SCHEMA,
            "command": command,
            "mode": "DRY_RUN",
            "batch_id": self.bundle.batch_id,
            "manifest_path": str(self.bundle.path),
            "manifest_sha256": self.bundle.sha256,
            "created_at": utc_now(),
            "shopify_writes_performed": False,
            "selected_count": len(contexts),
            "completed_verified_count": sum(
                value["action"] == "SKIP_ALREADY_COMPLETED"
                for value in proposals
            ),
            "proposed_update_count": sum(
                value["action"] == "PROPOSED_LIVE_UPDATE"
                for value in proposals
            ),
            "blocked_count": len(blocked),
            "items": results,
            "proposed_live_changes": proposals,
        }
        path = self.state.write_report(command, report)
        report["report_path"] = str(path)
        return report

    @staticmethod
    def _tagged_media(
        ctx: ItemContext, live: Mapping[str, Any],
    ) -> dict[str, dict[str, Any]] | None:
        result: dict[str, dict[str, Any]] = {}
        for role in ("hero", "original"):
            matches = [
                value for value in live.get("media", [])
                if value.get("alt") == ctx.expected_alt(role)
            ]
            if len(matches) > 1:
                raise BatchError(
                    f"{ctx.tank_id}: duplicate uploaded {role} media"
                )
            if matches:
                result[role] = matches[0]
        if not result:
            return None
        if set(result) != {"hero", "original"}:
            raise BatchError(
                f"{ctx.tank_id}: partial uploaded-media set is ambiguous"
            )
        if result["hero"]["id"] == result["original"]["id"]:
            raise BatchError(f"{ctx.tank_id}: uploaded media IDs collide")
        return result

    def _remember_uploaded_media(
        self, ctx: ItemContext, tagged: Mapping[str, Mapping[str, Any]],
    ) -> None:
        uploaded = {
            role: {
                "id": tagged[role]["id"],
                "alt": tagged[role]["alt"],
                "status": tagged[role]["status"],
            }
            for role in ("hero", "original")
        }
        self.state.set_fields(
            ctx.tank_id, "uploaded_media_identified",
            uploaded_media=uploaded,
        )

    def _allocate_and_transfer(self, ctx: ItemContext) -> None:
        record = self.state.item(ctx.tank_id)
        if record["stage"] == "PREFLIGHTED":
            inputs = []
            for role in ("hero", "original"):
                asset = ctx.asset(role)
                inputs.append({
                    "filename": Path(asset["path"]).name,
                    "mimeType": asset["mime_type"],
                    "fileSize": str(Path(asset["path"]).stat().st_size),
                    "resource": "PRODUCT_IMAGE",
                    "httpMethod": "POST",
                })
            variables = {"input": inputs}
            node, intent_id = self._write(
                ctx, "betta_batch_stage_images", variables,
                "stagedUploadsCreate", "userErrors",
            )
            targets = node.get("stagedTargets")
            if not isinstance(targets, list) or len(targets) != 2:
                raise DeferredError(
                    f"{ctx.tank_id}: Shopify did not return two staging targets"
                )
            for target in targets:
                if not isinstance(target, dict):
                    raise DeferredError(
                        f"{ctx.tank_id}: invalid Shopify staging target"
                    )
            secret_path = self.state.write_secret(
                ctx.tank_id, intent_id, {
                    "schema": "nta-betta-staging-secrets-v1",
                    "created_at": utc_now(),
                    "targets": targets,
                },
            )
            self.state.set_fields(
                ctx.tank_id, "staging_targets_secured",
                staging_secret=str(secret_path),
                staged_transfers=[],
            )
            self.state.transition(ctx.tank_id, "STAGING_ALLOCATED")

        record = self.state.item(ctx.tank_id)
        if record["stage"] != "STAGING_ALLOCATED":
            return
        if record.get("pending_transfer"):
            raise DeferredError(
                f"{ctx.tank_id}: staged transfer has uncertain outcome; "
                "reconcile explicitly before retry"
            )
        secret = read_json(Path(record["staging_secret"]))
        targets = secret.get("targets", [])
        if len(targets) != 2:
            raise DeferredError(f"{ctx.tank_id}: secure staging targets missing")
        completed = set(record.get("staged_transfers", []))
        for index, role in enumerate(("hero", "original")):
            if role in completed:
                continue
            asset = ctx.asset(role)
            self.state.start_transfer(ctx.tank_id, role, asset["sha256"])
            self.upload(targets[index], asset)
            self.state.finish_transfer(ctx.tank_id, role)
        self.state.transition(ctx.tank_id, "STAGED")

    def _attach_media(self, ctx: ItemContext) -> None:
        live = self._read(ctx)
        tagged = self._tagged_media(ctx, live)
        if tagged:
            self._remember_uploaded_media(ctx, tagged)
            self.state.transition(
                ctx.tank_id, "MEDIA_ATTACH_REQUESTED",
                {"recovered_existing_approved_media": True},
            )
            return
        record = self.state.item(ctx.tank_id)
        secret = read_json(Path(record["staging_secret"]))
        targets = secret.get("targets", [])
        if len(targets) != 2:
            raise DeferredError(f"{ctx.tank_id}: staging secret incomplete")
        variables = {
            "product": {"id": ctx.product_id},
            "media": [
                {
                    "mediaContentType": "IMAGE",
                    "originalSource": targets[0]["resourceUrl"],
                    "alt": ctx.expected_alt("hero"),
                },
                {
                    "mediaContentType": "IMAGE",
                    "originalSource": targets[1]["resourceUrl"],
                    "alt": ctx.expected_alt("original"),
                },
            ],
        }
        self._write(
            ctx, "betta_batch_add_images", variables,
            "productUpdate", "userErrors",
        )
        self.state.transition(ctx.tank_id, "MEDIA_ATTACH_REQUESTED")

    def _poll_media_ready(self, ctx: ItemContext) -> dict[str, Any]:
        last_status: list[str | None] = []
        for attempt in range(self.poll_attempts):
            live = self._read(ctx, media_poll=True)
            tagged = self._tagged_media(ctx, live)
            if tagged:
                last_status = [
                    tagged["hero"].get("status"),
                    tagged["original"].get("status"),
                ]
                if any(status in {"FAILED", "CANCELED"} for status in last_status):
                    raise BatchError(
                        f"{ctx.tank_id}: Shopify media processing failed"
                    )
                if last_status == ["READY", "READY"]:
                    self._remember_uploaded_media(ctx, tagged)
                    self.state.transition(ctx.tank_id, "MEDIA_READY")
                    return live
            if attempt + 1 < self.poll_attempts:
                self.sleep(self.poll_interval)
        raise DeferredError(
            f"{ctx.tank_id}: media not READY after polling; "
            f"last statuses={last_status or ['NOT_VISIBLE']}"
        )

    def _reorder_media(self, ctx: ItemContext) -> None:
        live = self._read(ctx)
        uploaded = self.state.item(ctx.tank_id)["uploaded_media"]
        desired = [uploaded["hero"]["id"], uploaded["original"]["id"]]
        current = [value["id"] for value in live["media"]]
        if current[:2] != desired:
            variables = {
                "id": ctx.product_id,
                "moves": [
                    {"id": desired[0], "newPosition": "0"},
                    {"id": desired[1], "newPosition": "1"},
                ],
            }
            self._write(
                ctx, "betta_batch_reorder_media", variables,
                "productReorderMedia", "mediaUserErrors",
            )
            for attempt in range(self.poll_attempts):
                live = self._read(ctx, media_poll=True)
                if [value["id"] for value in live["media"]][:2] == desired:
                    break
                if attempt + 1 < self.poll_attempts:
                    self.sleep(self.poll_interval)
            else:
                raise DeferredError(
                    f"{ctx.tank_id}: Shopify media reorder is still pending"
                )
        self.state.transition(ctx.tank_id, "MEDIA_ORDERED")

    def _delete_old_media(self, ctx: ItemContext) -> None:
        record = self.state.item(ctx.tank_id)
        live = self._read(ctx)
        uploaded = record["uploaded_media"]
        desired = [uploaded["hero"]["id"], uploaded["original"]["id"]]
        current = [value["id"] for value in live["media"]]
        if current[:2] != desired:
            raise BatchError(
                f"{ctx.tank_id}: replacements are not first before deletion"
            )
        old_ids = list(record["preflight"]["old_media_ids"])
        allowed = set(old_ids) | set(desired)
        unexpected = [value for value in current if value not in allowed]
        if unexpected:
            raise BatchError(
                f"{ctx.tank_id}: unknown media appeared; refusing deletion"
            )
        remaining_old = [value for value in old_ids if value in current]
        if remaining_old:
            if remaining_old != old_ids:
                raise BatchError(
                    f"{ctx.tank_id}: partial old-media deletion is ambiguous"
                )
            variables = {
                "productId": ctx.product_id,
                "mediaIds": old_ids,
            }
            self._write(
                ctx, "betta_batch_delete_media", variables,
                "productDeleteMedia", "mediaUserErrors",
            )
            for attempt in range(self.poll_attempts):
                live = self._read(ctx, media_poll=True)
                if [value["id"] for value in live["media"]] == desired:
                    break
                if attempt + 1 < self.poll_attempts:
                    self.sleep(self.poll_interval)
            else:
                raise DeferredError(
                    f"{ctx.tank_id}: old media deletion not yet verified"
                )
        elif current != desired:
            raise BatchError(
                f"{ctx.tank_id}: media set is not exactly the approved pair"
            )
        self.state.transition(ctx.tank_id, "OLD_MEDIA_DELETED")

    def _update_details(self, ctx: ItemContext) -> None:
        live = self._read(ctx)
        desired = (
            live.get("title") == ctx.title and
            live.get("arrival_date") == ctx.arrival_date
        )
        if not desired:
            preflight = self.state.item(ctx.tank_id)["preflight"]
            if (
                live.get("title") != preflight["title"] or
                live.get("arrival_date") != preflight["arrival_date"]
            ):
                raise BatchError(
                    f"{ctx.tank_id}: title/date changed during processing"
                )
            variables = {
                "product": {
                    "id": ctx.product_id,
                    "title": ctx.title,
                    "metafields": [{
                        "namespace": "custom",
                        "key": "arrival_date",
                        "type": "date",
                        "value": ctx.arrival_date,
                    }],
                },
            }
            self._write(
                ctx, "betta_batch_update_details", variables,
                "productUpdate", "userErrors",
            )
            live = self._read(ctx)
            if (
                live.get("title") != ctx.title or
                live.get("arrival_date") != ctx.arrival_date
            ):
                raise BatchError(
                    f"{ctx.tank_id}: details mutation failed fresh readback"
                )
        self.state.transition(ctx.tank_id, "DETAILS_UPDATED")

    def _set_inventory(self, ctx: ItemContext) -> None:
        record = self.state.item(ctx.tank_id)
        live = self._read(ctx)
        baseline = record["preflight"]["available"]
        if live.get("available") == ctx.quantity:
            if live.get("inventory_quantity") != ctx.quantity:
                raise BatchError(
                    f"{ctx.tank_id}: aggregate stock does not match the "
                    "target quantity"
                )
            accepted = any(
                value.get("operation") == "betta_batch_set_inventory" and
                value.get("status") in {"ACCEPTED", "RECONCILED_APPLIED"} and
                value.get("guard", {}).get("idempotency_key") ==
                record.get("inventory_idempotency_key")
                for value in record.get("mutation_history", [])
            )
            if baseline != ctx.quantity and not accepted:
                raise BatchError(
                    f"{ctx.tank_id}: stock changed before uploader CAS"
                )
            self.state.transition(ctx.tank_id, "INVENTORY_UPDATED")
            return
        if live.get("available") != baseline:
            raise BatchError(
                f"{ctx.tank_id}: stock changed during processing "
                f"({baseline} -> {live.get('available')})"
            )
        if live.get("inventory_quantity") != baseline:
            raise BatchError(
                f"{ctx.tank_id}: aggregate stock changed during processing "
                f"({baseline} -> {live.get('inventory_quantity')})"
            )
        key = record.get("inventory_idempotency_key")
        if key is None:
            key = str(uuid.uuid4())
            self.state.set_fields(
                ctx.tank_id, "inventory_idempotency_key_created",
                inventory_idempotency_key=key,
            )
            record = self.state.item(ctx.tank_id)
        batch_component = urllib.parse.quote(
            self.bundle.batch_id, safe="-._",
        )
        reference = (
            f"gid://nta-betta/Batch/{batch_component}/"
            f"{ctx.tank_id}/{key}"
        )
        guard = {
            "change_from_quantity": live["available"],
            "idempotency_key": key,
            "reference_document_uri": reference,
        }
        self.state.set_fields(
            ctx.tank_id, "inventory_compare_and_set_prepared",
            inventory_intent=guard,
        )
        variables = {
            "input": {
                "name": "available",
                "reason": ctx.raw["inventory_reason"],
                "referenceDocumentUri": reference,
                "quantities": [{
                    "inventoryItemId": ctx.inventory_item_id,
                    "locationId": ctx.location_id,
                    "quantity": ctx.quantity,
                    "changeFromQuantity": live["available"],
                }],
            },
            "idempotencyKey": key,
        }
        self._write(
            ctx, "betta_batch_set_inventory", variables,
            "inventorySetQuantities", "userErrors", guard,
        )
        live = self._read(ctx)
        if live.get("available") != ctx.quantity:
            raise BatchError(
                f"{ctx.tank_id}: inventory mutation failed fresh readback"
            )
        self.state.transition(ctx.tank_id, "INVENTORY_UPDATED")

    def _write_final_receipt(
        self,
        ctx: ItemContext,
        live: Mapping[str, Any],
        assertions: Mapping[str, Any],
        status: str,
    ) -> Path | None:
        record = self.state.item(ctx.tank_id)
        prior = record.get("final_receipt")
        if prior and Path(prior).is_file():
            return Path(prior)
        receipt = {
            "schema": FINAL_RECEIPT_SCHEMA,
            "status": status,
            "batch_id": self.bundle.batch_id,
            "manifest_path": str(self.bundle.path),
            "manifest_sha256": self.bundle.sha256,
            "tank_id": ctx.tank_id,
            "product_id": ctx.product_id,
            "variant_id": ctx.variant_id,
            "inventory_item_id": ctx.inventory_item_id,
            "location_id": ctx.location_id,
            "verified_at": utc_now(),
            "source": "FRESH_SHOPIFY_READ",
            "assertions": assertions,
            "final": {
                "title": live.get("title"),
                "arrival_date": live.get("arrival_date"),
                "available": live.get("available"),
                "media_ids": [
                    value.get("id") for value in live.get("media", [])
                ],
                "media_alts": [
                    value.get("alt") for value in live.get("media", [])
                ],
                "price": live.get("price"),
                "cost": live.get("cost"),
                "description_sha256": live.get("description_sha256"),
                "inventory_policy": live.get("inventory_policy"),
                "tracked": live.get("tracked"),
            },
            "qa": {
                "receipt_sha256": ctx.qa_sha256,
                "exception": (ctx.raw.get("image_qa") or {}).get("exception"),
            },
            "telemetry": record.get("telemetry"),
            "inventory_idempotency_key": record.get(
                "inventory_idempotency_key"
            ),
            "mutation_history": record.get("mutation_history", []),
        }
        path = self.state.write_receipt(ctx.tank_id, receipt)
        self.state.set_fields(
            ctx.tank_id, "final_receipt_written",
            final_receipt=str(path),
        )
        return path

    def _verify_and_finish(self, ctx: ItemContext) -> dict[str, Any]:
        live = self._read(ctx)
        assertions = final_assertions(
            ctx, live, self.state.item(ctx.tank_id),
        )
        if not assertions_pass(assertions):
            failures = [
                name for name, value in assertions.items()
                if value["status"] != "PASS"
            ]
            raise BatchError(
                f"{ctx.tank_id}: final verification failed: "
                f"{', '.join(failures)}"
            )
        self.state.transition(ctx.tank_id, "VERIFIED")
        receipt = self._write_final_receipt(
            ctx, live, assertions, "FINAL_SHOPIFY_READBACK_PASS",
        )
        return {
            "tank_id": ctx.tank_id,
            "status": "FINAL_SHOPIFY_READBACK_PASS",
            "receipt": str(receipt),
            "assertions": assertions,
        }

    def process_item(self, ctx: ItemContext) -> dict[str, Any]:
        while True:
            record = self.state.item(ctx.tank_id)
            stage = record["stage"]
            if stage in {"VERIFIED", "COMPLETED_VERIFIED"}:
                return {
                    "tank_id": ctx.tank_id,
                    "status": stage,
                    "receipt": record.get("final_receipt"),
                }
            if stage == "BLOCKED":
                raise BatchError(
                    f"{ctx.tank_id}: state is BLOCKED; inspect before resume"
                )
            if record.get("pending_mutation"):
                raise DeferredError(
                    f"{ctx.tank_id}: unresolved mutation outcome; run resume "
                    "for reconciliation"
                )
            if record.get("pending_transfer"):
                raise DeferredError(
                    f"{ctx.tank_id}: unresolved staged transfer; run resume"
                )
            if stage == "PREFLIGHTED":
                live = self._read(ctx)
                self._assert_initial_baseline(ctx, live)
                tagged = self._tagged_media(ctx, live)
                if tagged:
                    self._remember_uploaded_media(ctx, tagged)
                    self.state.transition(
                        ctx.tank_id, "MEDIA_ATTACH_REQUESTED",
                        {"recovered_existing_approved_media": True},
                    )
                else:
                    self._allocate_and_transfer(ctx)
            elif stage == "STAGING_ALLOCATED":
                self._allocate_and_transfer(ctx)
            elif stage == "STAGED":
                self._attach_media(ctx)
            elif stage == "MEDIA_ATTACH_REQUESTED":
                self._poll_media_ready(ctx)
            elif stage == "MEDIA_READY":
                self._reorder_media(ctx)
            elif stage == "MEDIA_ORDERED":
                self._delete_old_media(ctx)
            elif stage == "OLD_MEDIA_DELETED":
                self._update_details(ctx)
            elif stage == "DETAILS_UPDATED":
                self._set_inventory(ctx)
            elif stage == "INVENTORY_UPDATED":
                return self._verify_and_finish(ctx)
            else:
                raise BatchError(
                    f"{ctx.tank_id}: unsupported processing stage {stage}"
                )

    def execute(self, contexts: list[ItemContext]) -> dict[str, Any]:
        preflight = self.preflight_all(contexts)
        results: list[dict[str, Any]] = []
        for ctx in contexts:
            record = self.state.item(ctx.tank_id)
            if record["stage"] == "BLOCKED":
                results.append({
                    "tank_id": ctx.tank_id,
                    "status": "BLOCKED",
                    "error": record.get("last_error"),
                })
                continue
            if record["stage"] == "COMPLETED_VERIFIED":
                results.append({
                    "tank_id": ctx.tank_id,
                    "status": "SKIPPED_ALREADY_COMPLETED",
                    "receipt": record.get("final_receipt"),
                })
                continue
            try:
                results.append(self.process_item(ctx))
            except (UncertainWriteError, DeferredError) as exc:
                results.append({
                    "tank_id": ctx.tank_id,
                    "status": "PENDING_RECONCILIATION",
                    "error": str(exc),
                })
            except BatchError as exc:
                self.state.block(ctx.tank_id, str(exc))
                results.append({
                    "tank_id": ctx.tank_id,
                    "status": "BLOCKED",
                    "error": str(exc),
                })
        report = {
            "schema": REPORT_SCHEMA,
            "command": "execute",
            "mode": "LIVE",
            "batch_id": self.bundle.batch_id,
            "manifest_path": str(self.bundle.path),
            "manifest_sha256": self.bundle.sha256,
            "created_at": utc_now(),
            "shopify_writes_performed": any(
                self.state.item(ctx.tank_id)["telemetry"]["write_calls"] > 0
                for ctx in contexts
            ),
            "preflight": preflight,
            "items": results,
            "verified_count": sum(
                value["status"] in {
                    "FINAL_SHOPIFY_READBACK_PASS",
                    "SKIPPED_ALREADY_COMPLETED",
                }
                for value in results
            ),
            "blocked_count": sum(
                value["status"] == "BLOCKED" for value in results
            ),
            "pending_count": sum(
                value["status"] == "PENDING_RECONCILIATION"
                for value in results
            ),
        }
        path = self.state.write_report("execute", report)
        report["report_path"] = str(path)
        return report

    def _pending_applied(
        self, ctx: ItemContext, operation: str, live: Mapping[str, Any],
    ) -> tuple[bool, str | None]:
        record = self.state.item(ctx.tank_id)
        if operation == "betta_batch_stage_images":
            return False, None
        if operation == "betta_batch_add_images":
            tagged = self._tagged_media(ctx, live)
            if tagged:
                self._remember_uploaded_media(ctx, tagged)
                return True, "MEDIA_ATTACH_REQUESTED"
            return False, None
        uploaded = record.get("uploaded_media") or {}
        desired_media = [
            uploaded.get("hero", {}).get("id"),
            uploaded.get("original", {}).get("id"),
        ]
        live_media = [value.get("id") for value in live.get("media", [])]
        if operation == "betta_batch_reorder_media":
            return live_media[:2] == desired_media, "MEDIA_ORDERED"
        if operation == "betta_batch_delete_media":
            return live_media == desired_media, "OLD_MEDIA_DELETED"
        if operation == "betta_batch_update_details":
            return (
                live.get("title") == ctx.title and
                live.get("arrival_date") == ctx.arrival_date
            ), "DETAILS_UPDATED"
        if operation == "betta_batch_set_inventory":
            return live.get("available") == ctx.quantity, "INVENTORY_UPDATED"
        return False, None

    def reconcile_pending(
        self, ctx: ItemContext, resolve_not_applied: bool = False,
    ) -> dict[str, Any] | None:
        record = self.state.item(ctx.tank_id)
        transfer = record.get("pending_transfer")
        if transfer:
            if not resolve_not_applied:
                return {
                    "tank_id": ctx.tank_id,
                    "status": "UNCERTAIN_TRANSFER_REQUIRES_DECISION",
                    "role": transfer.get("role"),
                }
            self.state.set_fields(
                ctx.tank_id, "operator_resolved_transfer_not_applied",
                pending_transfer=None,
            )
            return {
                "tank_id": ctx.tank_id,
                "status": "OPERATOR_CONFIRMED_TRANSFER_NOT_APPLIED",
            }

        pending = record.get("pending_mutation")
        if not pending:
            return None
        live = self._read(ctx)
        applied, target = self._pending_applied(
            ctx, pending["operation"], live,
        )
        if applied:
            operation = pending["operation"]
            self.state.complete_intent(
                ctx.tank_id, "RECONCILED_APPLIED",
                {"fresh_readback": True},
            )
            if operation == "betta_batch_add_images":
                target = "MEDIA_ATTACH_REQUESTED"
            if target and self.state.item(ctx.tank_id)["stage"] != target:
                self.state.transition(
                    ctx.tank_id, target,
                    {"reconciled_intent": pending["intent_id"]},
                )
            return {
                "tank_id": ctx.tank_id,
                "status": "RECONCILED_APPLIED",
                "operation": operation,
            }
        if resolve_not_applied:
            operation = pending["operation"]
            self.state.complete_intent(
                ctx.tank_id, "OPERATOR_CONFIRMED_NOT_APPLIED",
                {"fresh_readback": True},
            )
            return {
                "tank_id": ctx.tank_id,
                "status": "OPERATOR_CONFIRMED_NOT_APPLIED",
                "operation": operation,
            }
        self.state.set_fields(
            ctx.tank_id, "uncertain_intent_reconciled_not_proven",
            last_reconciliation={
                "at": utc_now(),
                "operation": pending["operation"],
                "result": "NOT_PROVEN_APPLIED",
            },
        )
        return {
            "tank_id": ctx.tank_id,
            "status": "UNCERTAIN_REQUIRES_DECISION",
            "operation": pending["operation"],
            "intent_id": pending["intent_id"],
        }

    def resume(
        self,
        contexts: list[ItemContext],
        live_enabled: bool,
        resolve_not_applied: bool = False,
    ) -> dict[str, Any]:
        reconciled: list[dict[str, Any]] = []
        had_pending = False
        for ctx in contexts:
            record = self.state.item(ctx.tank_id)
            if record.get("pending_mutation") or record.get("pending_transfer"):
                had_pending = True
                result = self.reconcile_pending(
                    ctx, resolve_not_applied=resolve_not_applied,
                )
                if result:
                    reconciled.append(result)
        if had_pending:
            report = {
                "schema": REPORT_SCHEMA,
                "command": "resume",
                "mode": "RECONCILE_ONLY",
                "batch_id": self.bundle.batch_id,
                "manifest_sha256": self.bundle.sha256,
                "created_at": utc_now(),
                "shopify_writes_performed": False,
                "items": reconciled,
                "next_action": (
                    "Run resume again after reviewing reconciliation; "
                    "no uncertain mutation was replayed."
                ),
            }
            path = self.state.write_report("resume-reconcile", report)
            report["report_path"] = str(path)
            return report
        if not live_enabled:
            return self.dry_run(contexts, command="resume")
        return self.execute(contexts)

    def verify(self, contexts: list[ItemContext]) -> dict[str, Any]:
        results = []
        for ctx in contexts:
            try:
                live = self._read(ctx)
                assertions = final_assertions(
                    ctx, live, self.state.item(ctx.tank_id),
                )
                status = (
                    "FINAL_SHOPIFY_READBACK_PASS"
                    if assertions_pass(assertions)
                    else "FINAL_SHOPIFY_READBACK_FAIL"
                )
                results.append({
                    "tank_id": ctx.tank_id,
                    "status": status,
                    "assertions": assertions,
                })
            except BatchError as exc:
                results.append({
                    "tank_id": ctx.tank_id,
                    "status": "FINAL_SHOPIFY_READBACK_FAIL",
                    "error": str(exc),
                })
        report = {
            "schema": REPORT_SCHEMA,
            "command": "verify",
            "mode": "READ_ONLY",
            "batch_id": self.bundle.batch_id,
            "manifest_sha256": self.bundle.sha256,
            "created_at": utc_now(),
            "shopify_writes_performed": False,
            "items": results,
            "pass_count": sum(
                value["status"] == "FINAL_SHOPIFY_READBACK_PASS"
                for value in results
            ),
            "fail_count": sum(
                value["status"] != "FINAL_SHOPIFY_READBACK_PASS"
                for value in results
            ),
        }
        path = self.state.write_report("verify", report)
        report["report_path"] = str(path)
        return report

    def status(self, contexts: list[ItemContext]) -> dict[str, Any]:
        items = []
        for ctx in contexts:
            record = self.state.item(ctx.tank_id)
            pending = record.get("pending_mutation")
            items.append({
                "tank_id": ctx.tank_id,
                "stage": record["stage"],
                "status": record["status"],
                "pending_operation": (
                    pending.get("operation") if isinstance(pending, dict)
                    else None
                ),
                "pending_intent_id": (
                    pending.get("intent_id") if isinstance(pending, dict)
                    else None
                ),
                "pending_transfer_role": (
                    (record.get("pending_transfer") or {}).get("role")
                ),
                "final_receipt": record.get("final_receipt"),
                "last_error": record.get("last_error"),
                "telemetry": record.get("telemetry"),
            })
        return {
            "schema": REPORT_SCHEMA,
            "command": "status",
            "mode": "LOCAL_STATE_ONLY",
            "batch_id": self.bundle.batch_id,
            "manifest_path": str(self.bundle.path),
            "manifest_sha256": self.bundle.sha256,
            "state_path": str(self.state.path),
            "created_at": utc_now(),
            "shopify_writes_performed": False,
            "items": items,
        }


def add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--tank", action="append",
        help="one tank ID; repeat or provide comma-separated IDs",
    )
    parser.add_argument("--bridge", type=Path)
    parser.add_argument("--node")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--poll-attempts", type=int, default=30)
    parser.add_argument("--poll-interval", type=float, default=2.0)


def add_live_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--live", action="store_true",
        help="enable manifest-scoped live writes; otherwise dry-run",
    )
    parser.add_argument(
        "--confirm-manifest-sha256",
        help="must exactly match the manifest used for a live run",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generic resumable NTA Betta Shopify batch uploader"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "dry-run", "status", "verify"):
        child = sub.add_parser(name)
        add_common_options(child)
    execute = sub.add_parser("execute")
    add_common_options(execute)
    add_live_options(execute)
    resume = sub.add_parser("resume")
    add_common_options(resume)
    add_live_options(resume)
    resume.add_argument(
        "--resolve-uncertain-not-applied",
        action="store_true",
        help=(
            "after fresh readback, explicitly mark a still-unproven intent "
            "not applied; this invocation never replays it"
        ),
    )
    return parser


def bridge_configuration(
    args: argparse.Namespace, bundle: ManifestBundle, live: bool,
) -> BridgeClient:
    config = bundle.raw.get("shopify_bridge") or {}
    bridge_value = (
        args.bridge or config.get("path") or
        os.environ.get("NTA_SHOPIFY_BRIDGE")
    )
    if not bridge_value:
        raise BatchError(
            "Shopify bridge path required via manifest, --bridge, "
            "or NTA_SHOPIFY_BRIDGE"
        )
    bridge = resolve_path(
        bundle.path.parent, str(bridge_value), "Shopify bridge",
    )
    environment = dict(os.environ)
    env_file = args.env_file or config.get("environment_file")
    if env_file:
        env_path = resolve_path(
            bundle.path.parent, str(env_file), "Shopify environment file",
        )
        load_dotenv(env_path, environment)
    node = resolve_node_binary(args.node or config.get("node"))
    return BridgeClient(
        bridge,
        node,
        environment=environment,
        live=live,
        approved_manifest=bundle.path if live else None,
        approved_sha256=bundle.sha256 if live else None,
    )


def require_live_authority(
    bundle: ManifestBundle,
    contexts: Iterable[ItemContext],
    supplied_digest: str | None,
) -> None:
    require(bundle.raw.get("shopify_write_authorised") is True,
            "batch Shopify write authority is false")
    require(all(ctx.raw.get("write_authorised") is True for ctx in contexts),
            "one or more selected items are not write-authorised")
    require(supplied_digest == bundle.sha256,
            "live confirmation must equal the exact manifest SHA-256")


def concise_output(report: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "command": report.get("command"),
        "mode": report.get("mode"),
        "batch_id": report.get("batch_id"),
        "manifest_sha256": report.get("manifest_sha256"),
        "shopify_writes_performed": report.get(
            "shopify_writes_performed", False
        ),
        "report_path": report.get("report_path"),
    }
    for key in (
        "selected_count", "completed_verified_count",
        "proposed_update_count", "blocked_count",
        "verified_count", "pending_count", "pass_count", "fail_count",
    ):
        if key in report:
            result[key] = report[key]
    result["items"] = [{
        key: value for key, value in item.items()
        if key in {
            "tank_id", "status", "stage", "error",
            "pending_operation", "receipt",
        }
    } for item in report.get("items", [])]
    return result


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    commands = {"preflight", "dry-run", "execute", "status", "resume", "verify"}
    if raw_args and raw_args[0] in {"-h", "--help"}:
        pass
    elif not raw_args or raw_args[0] not in commands:
        raw_args.insert(0, "dry-run")
    parser = build_parser()
    args = parser.parse_args(raw_args)
    try:
        bundle = ManifestBundle(args.manifest)
        contexts = bundle.select(args.tank)
        state = StateStore(bundle)
        if args.command == "status":
            report = BatchUploader(
                bundle, gateway=None, state=state  # type: ignore[arg-type]
            ).status(contexts)
            print(json.dumps(concise_output(report), indent=2))
            return 0

        requested_live = bool(
            args.command in {"execute", "resume"} and args.live
        )
        if requested_live:
            require_live_authority(
                bundle, contexts, args.confirm_manifest_sha256,
            )
        gateway = bridge_configuration(args, bundle, requested_live)
        uploader = BatchUploader(
            bundle,
            gateway,
            state,
            poll_attempts=args.poll_attempts,
            poll_interval=args.poll_interval,
        )

        if args.command == "preflight":
            report = uploader.dry_run(contexts, command="preflight")
        elif args.command == "dry-run":
            report = uploader.dry_run(contexts)
        elif args.command == "execute":
            report = (
                uploader.execute(contexts) if requested_live
                else uploader.dry_run(contexts, command="execute")
            )
        elif args.command == "resume":
            report = uploader.resume(
                contexts,
                live_enabled=requested_live,
                resolve_not_applied=args.resolve_uncertain_not_applied,
            )
        else:
            report = uploader.verify(contexts)

        print(json.dumps(concise_output(report), indent=2))
        blocked = (
            report.get("blocked_count", 0) or
            report.get("fail_count", 0) or
            report.get("pending_count", 0)
        )
        return 3 if blocked else 0
    except (BatchError, ManifestError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
