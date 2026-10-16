#!/usr/bin/env python3
"""Trusted Shopify write-boundary core for the NTA Betta P1 follow-up (H1).

This module is the validation and authorisation core used by the root-owned
write daemon (``betta_write_daemon.py``). It is deliberately stdlib-only and
Python 3.9-compatible so the production daemon can run on Apple's
``/usr/bin/python3``.

Boundary guarantees implemented here:

- policy and credentials are read ONLY from root-owned files under the daemon's
  ``--state-dir``; environment variables never influence any decision;
- every write request is validated fail-closed through the pinned pipeline
  (peer uid -> schema -> disabled flag -> operation policy -> replay ->
  authorisation -> evidence -> operation caps/budgets -> fresh baseline/CAS ->
  apply), each refusal with a distinct deterministic error code;
- owner authorisation records (``nta-betta-write-authorisation-v1``) are
  root-owned, self-hashed, single-use (consumed in the ledger) and bind source
  SHA-256, tank, product, variant and field scope exactly;
- standing mode is allowed only for operations/field sets explicitly enabled
  in ``boundary-policy.json``; ``merch_update`` can never run in standing mode;
- the evidence gate mirrors the uploader identity firewall: the manifest must
  live under a policy-allowed root and hash-match its bytes, its item must bind
  the requested product/variant/source/tank, and a vision/requested tank
  difference requires a valid immutable owner-correction record;
- mutation intents are persisted BEFORE the Shopify call; an uncertain outcome
  becomes ``RECONCILIATION_REQUIRED`` and is never blindly replayed;
- receipts (``nta-betta-write-receipt-v1``) are written root-owned and
  HMAC-SHA256 signed over their canonical JSON with ``signing.key``.

The upstream design contract is
``docs/incident/TRUSTED_WRITE_BOUNDARY_BRIEF_2026-10-16.md``. Corrections reuse
the sibling ``betta_corrections.py`` module read-only via importlib; that file
is not modified by the boundary.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import re
import stat
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterable, Mapping, Optional

# ---------------------------------------------------------------------------
# Schemas, operations, error codes
# ---------------------------------------------------------------------------

REQUEST_SCHEMA = "nta-betta-write-request-v1"
RESPONSE_SCHEMA = "nta-betta-write-response-v1"
RECEIPT_SCHEMA = "nta-betta-write-receipt-v1"
AUTHORISATION_SCHEMA = "nta-betta-write-authorisation-v1"
POLICY_SCHEMA = "nta-betta-write-boundary-policy-v1"
LEDGER_SCHEMA = "nta-betta-write-ledger-v1"
MANIFEST_SCHEMA = "nta-betta-shopify-batch-v1"
DISABLED_MARKER_SCHEMA = "nta-betta-write-disabled-v1"

OP_STATUS = "status"
OP_VERIFY = "verify"
OP_UPDATE_DETAILS = "update_details"
OP_SET_INVENTORY = "set_inventory"
OP_MEDIA_APPEND = "media_append"
OP_MERCH_UPDATE = "merch_update"

OPERATIONS = (
    OP_STATUS, OP_VERIFY, OP_UPDATE_DETAILS, OP_SET_INVENTORY,
    OP_MEDIA_APPEND, OP_MERCH_UPDATE,
)
WRITE_OPERATIONS = (
    OP_UPDATE_DETAILS, OP_SET_INVENTORY, OP_MEDIA_APPEND, OP_MERCH_UPDATE,
)
# The pinned field vocabulary per operation class (used for authorisation
# scoping, policy allowlists and correction-scope checks).
OP_FIELDS = {
    OP_UPDATE_DETAILS: ("title", "arrival_date"),
    OP_SET_INVENTORY: ("inventory",),
    OP_MEDIA_APPEND: ("media",),
    OP_MERCH_UPDATE: ("vendor", "price", "cost"),
}
# Standing (autonomous) mode can never authorise these operations.
STANDING_FORBIDDEN = frozenset({OP_MERCH_UPDATE})

# Pinned pipeline error codes (order matches the validation pipeline).
ERR_PEER_NOT_ALLOWED = "peer_not_allowed"
ERR_BAD_REQUEST = "bad_request"
ERR_BOUNDARY_DISABLED = "boundary_disabled"
ERR_OPERATION_NOT_ALLOWED = "operation_not_allowed"
ERR_REPLAY_REJECTED = "replay_rejected"
ERR_DUPLICATE_OPERATION = "duplicate_operation"
ERR_AUTHORISATION_INVALID = "authorisation_invalid"
ERR_EVIDENCE_INVALID = "evidence_invalid"
ERR_CORRECTION_INVALID = "correction_invalid"
ERR_POLICY_REFUSED = "policy_refused"
ERR_BASELINE_DRIFT = "baseline_drift"
# Runtime-outcome codes (not pipeline refusals).
ERR_SHOPIFY_REJECTED = "shopify_rejected"
ERR_SHOPIFY_UNAVAILABLE = "shopify_unavailable"
ERR_RECONCILIATION_REQUIRED = "reconciliation_required"
ERR_INTERNAL_ERROR = "internal_error"

OUTCOME_APPLIED = "APPLIED"
OUTCOME_DRY_RUN = "DRY_RUN"
OUTCOME_VERIFIED = "VERIFIED"
OUTCOME_REFUSED = "REFUSED"
OUTCOME_RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
OUTCOME_STATUS = "STATUS"

STATE_MUTATING = "MUTATING"
STATE_APPLIED = "APPLIED"
STATE_DRY_RUN = "DRY_RUN"
STATE_REFUSED = "REFUSED"
STATE_VERIFIED = "VERIFIED"
STATE_RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
STATE_RECONCILED_APPLIED = "RECONCILED_APPLIED"
STATE_RECONCILED_NOT_APPLIED = "RECONCILED_NOT_APPLIED"

IDENTITY_KEYS = frozenset({
    "source_sha256", "detected_tank", "requested_tank", "accepted_tank",
    "correction_sha256",
})
# The correction scope the uploader identity gate requires; mirrored exactly.
IDENTITY_OPERATION_FIELDS = ("title", "arrival_date", "inventory", "media")

AUTHORISATION_KEYS = frozenset({
    "schema", "source_sha256", "tank", "product_id", "variant_id", "fields",
    "operation_class", "reason", "operator", "created_at", "expires_at",
    "authorisation_sha256",
})

SHA_RE = re.compile(r"^[0-9a-f]{64}$")
TANK_RE = re.compile(r"^(?:[1-9]\d*BT[1-9]\d*|APE\d+)$")
FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")
GID_RE = {
    "product_id": re.compile(r"^gid://shopify/Product/[1-9]\d*$"),
    "variant_id": re.compile(r"^gid://shopify/ProductVariant/[1-9]\d*$"),
    "inventory_item_id": re.compile(r"^gid://shopify/InventoryItem/[1-9]\d*$"),
    "location_id": re.compile(r"^gid://shopify/Location/[1-9]\d*$"),
}
TARGET_KEYS = frozenset(GID_RE)
EVIDENCE_KEYS = frozenset({
    "manifest_path", "manifest_sha256", "source_sha256", "identity",
    "correction_sha256", "qa_receipt_sha256", "idempotency_key",
})
REQUEST_KEYS = frozenset({
    "schema", "request_id", "operation", "mode", "authorisation", "target",
    "evidence", "operations",
})
RECEIPT_CORE_KEYS = (
    "schema", "request_id", "operation", "mode", "outcome", "target",
    "evidence", "authorisation", "before", "after", "checks", "created_at",
    "daemon",
)
PROTECTED_SNAPSHOT_KEYS = (
    "product_id", "variant_id", "inventory_item_id", "location_id", "title",
    "arrival_date", "available", "inventory_quantity", "status", "vendor",
    "price", "cost", "description_sha256", "inventory_policy", "tracked",
    "media",
)
MAX_JSON_LINE_BYTES = 1024 * 1024


class BoundaryRefusal(Exception):
    """A deterministic fail-closed refusal carrying a pinned error code."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class AuthorisationError(ValueError):
    """An authorisation record request is malformed."""


def refusal(code: str, detail: str) -> BoundaryRefusal:
    return BoundaryRefusal(code, detail)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def parse_iso8601(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def numeric_equal(left: Any, right: Any) -> bool:
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, TypeError, ValueError):
        return False


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
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
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


def write_json_exclusive(path: Path, value: Any, mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    fsync_directory(path.parent)
    return path


def read_json(path: Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def is_under_roots(path: Path, roots: Iterable[Path]) -> bool:
    try:
        resolved = Path(path).resolve(strict=False)
    except OSError:
        return False
    for root in roots:
        try:
            resolved.relative_to(Path(root).resolve(strict=False))
            return True
        except ValueError:
            continue
    return False


def require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise refusal(ERR_BAD_REQUEST, f"{label}: lowercase SHA-256 required")
    return value


def require_string(value: Any, label: str, *, max_length: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise refusal(ERR_BAD_REQUEST, f"{label}: non-empty string required")
    return value


def require_gid(target: Mapping[str, Any], kind: str, *, required: bool) -> Optional[str]:
    value = target.get(kind)
    if value is None:
        if required:
            raise refusal(ERR_BAD_REQUEST, f"target.{kind} is required")
        return None
    if not isinstance(value, str) or GID_RE[kind].fullmatch(value) is None:
        raise refusal(ERR_BAD_REQUEST, f"target.{kind}: invalid Shopify GID")
    return value


def detect_image_mime(path: Path) -> Optional[str]:
    """Detect png/jpeg from file bytes (never from a caller-supplied label)."""
    try:
        with Path(path).open("rb") as handle:
            head = handle.read(16)
    except OSError:
        return None
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


def media_alt(batch_id: str, tank_id: str, role: str, digest: str) -> str:
    return f"NTA|{batch_id}|{tank_id}|{role.upper()}|sha256={digest}"


# ---------------------------------------------------------------------------
# State paths
# ---------------------------------------------------------------------------


class BoundaryPaths:
    """Root-owned state layout under ``--state-dir``."""

    def __init__(self, state_dir: Path | str):
        self.state_dir = Path(state_dir).expanduser()
        self.policy_path = self.state_dir / "boundary-policy.json"
        self.shopify_env_path = self.state_dir / "shopify.env"
        self.signing_key_path = self.state_dir / "signing.key"
        self.disabled_path = self.state_dir / "disabled"
        self.authorisations_dir = self.state_dir / "authorisations"
        self.corrections_dir = self.state_dir / "corrections"
        self.ledger_dir = self.state_dir / "ledger"
        self.ledger_path = self.ledger_dir / "ledger.json"
        self.receipts_dir = self.state_dir / "receipts"

    def ensure_dirs(self) -> None:
        for directory in (
            self.state_dir, self.authorisations_dir, self.corrections_dir,
            self.ledger_dir, self.receipts_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(directory, 0o700)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Policy: load + strict validation (root-owned file only; env is ignored)
# ---------------------------------------------------------------------------


def default_policy() -> dict:
    return {
        "schema": POLICY_SCHEMA,
        "version": 1,
        "allowed_uids": [501],
        "allowed_roots": [],
        "operations": {
            OP_STATUS: {"enabled": True},
            OP_VERIFY: {"enabled": True},
            OP_UPDATE_DETAILS: {"standing": True, "fields": ["title", "arrival_date"]},
            OP_SET_INVENTORY: {
                "standing": True, "allowed_from": [0], "target": 1,
                "reasons": ["received", "correction"],
            },
            OP_MEDIA_APPEND: {
                "standing": True, "max_assets": 2, "max_bytes": 20_971_520,
                "mime_types": ["image/png", "image/jpeg"],
                "poll_attempts": 30, "poll_interval": 2.0,
            },
            OP_MERCH_UPDATE: {
                "standing": False, "fields": ["vendor", "price", "cost"],
            },
        },
        "budgets": {"max_operations_per_request": 8, "max_daily_writes": 200},
    }


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_policy(data: Any) -> Optional[str]:
    """Return a refusal reason for an unsafe/malformed policy, else ``None``."""
    if not isinstance(data, dict):
        return "policy_not_object"
    if data.get("schema") != POLICY_SCHEMA:
        return "policy_schema_mismatch"
    if not _is_int(data.get("version")) or data["version"] != 1:
        return "policy_version_mismatch"
    uids = data.get("allowed_uids")
    if (not isinstance(uids, list) or not uids or
            any(not _is_int(uid) or uid < 0 for uid in uids)):
        return "policy_allowed_uids_invalid"
    roots = data.get("allowed_roots")
    if (not isinstance(roots, list) or
            any(not isinstance(root, str) or not root or not os.path.isabs(root)
                for root in roots)):
        return "policy_allowed_roots_invalid"
    operations = data.get("operations")
    if not isinstance(operations, dict):
        return "policy_operations_invalid"
    for name, config in operations.items():
        if name not in OPERATIONS:
            return f"policy_unknown_operation:{name}"
        if not isinstance(config, dict):
            return f"policy_operation_not_object:{name}"
        if name in (OP_STATUS, OP_VERIFY):
            if not isinstance(config.get("enabled"), bool):
                return f"policy_operation_enabled_invalid:{name}"
            continue
        if not isinstance(config.get("standing"), bool):
            return f"policy_operation_standing_invalid:{name}"
        fields = config.get("fields")
        if fields is None:
            continue  # media_append / set_inventory use typed caps below
        if (not isinstance(fields, list) or not fields or
                any(not isinstance(field, str) or not FIELD_RE.fullmatch(field)
                    for field in fields)):
            return f"policy_operation_fields_invalid:{name}"
    update = operations.get(OP_UPDATE_DETAILS)
    if update is not None:
        allowed = set(OP_FIELDS[OP_UPDATE_DETAILS])
        if not set(update.get("fields", [])) or not set(update["fields"]) <= allowed:
            return "policy_update_details_fields_invalid"
    inventory = operations.get(OP_SET_INVENTORY)
    if inventory is not None:
        allowed_from = inventory.get("allowed_from")
        if (not isinstance(allowed_from, list) or not allowed_from or
                any(not _is_int(value) or value < 0 for value in allowed_from)):
            return "policy_inventory_allowed_from_invalid"
        if not _is_int(inventory.get("target")) or inventory["target"] < 0:
            return "policy_inventory_target_invalid"
        reasons = inventory.get("reasons")
        if (not isinstance(reasons, list) or not reasons or
                not set(reasons) <= {"received", "correction"}):
            return "policy_inventory_reasons_invalid"
    media = operations.get(OP_MEDIA_APPEND)
    if media is not None:
        if not _is_int(media.get("max_assets")) or not 1 <= media["max_assets"] <= 8:
            return "policy_media_max_assets_invalid"
        if not _is_int(media.get("max_bytes")) or media["max_bytes"] <= 0:
            return "policy_media_max_bytes_invalid"
        mime_types = media.get("mime_types")
        if (not isinstance(mime_types, list) or not mime_types or
                not set(mime_types) <= {"image/png", "image/jpeg"}):
            return "policy_media_mime_types_invalid"
        if not _is_int(media.get("poll_attempts")) or media["poll_attempts"] < 1:
            return "policy_media_poll_attempts_invalid"
        interval = media.get("poll_interval")
        if (isinstance(interval, bool) or not isinstance(interval, (int, float)) or
                interval < 0 or interval > 60):
            return "policy_media_poll_interval_invalid"
    merch = operations.get(OP_MERCH_UPDATE)
    if merch is not None:
        # H1: merch_update must be impossible in standing mode.
        if merch.get("standing") is not False:
            return "policy_merch_standing_forbidden"
        allowed = set(OP_FIELDS[OP_MERCH_UPDATE])
        if (not isinstance(merch.get("fields"), list) or not merch["fields"] or
                not set(merch["fields"]) <= allowed):
            return "policy_merch_fields_invalid"
    budgets = data.get("budgets")
    if not isinstance(budgets, dict):
        return "policy_budgets_invalid"
    if (not _is_int(budgets.get("max_operations_per_request")) or
            budgets["max_operations_per_request"] < 1):
        return "policy_max_operations_invalid"
    if (not _is_int(budgets.get("max_daily_writes")) or
            budgets["max_daily_writes"] < 0):
        return "policy_max_daily_writes_invalid"
    return None


def load_policy(path: Path) -> tuple[Optional[dict], Optional[str]]:
    """Load and validate the root-owned policy file; fail closed on problems."""
    try:
        data = read_json(path)
    except FileNotFoundError:
        return None, "policy_missing"
    except (OSError, json.JSONDecodeError):
        return None, "policy_unreadable"
    reason = validate_policy(data)
    if reason is not None:
        return None, reason
    return data, None


# ---------------------------------------------------------------------------
# Corrections module reuse (read-only import of the sibling module)
# ---------------------------------------------------------------------------

_CORRECTIONS: Optional[ModuleType] = None
_CORRECTIONS_PATH: Optional[Path] = None


def default_corrections_path(code_root: Optional[Path | str] = None) -> Path:
    base = Path(code_root) if code_root is not None else Path(__file__).resolve().parent
    return base / "betta_corrections.py"


def load_corrections_module(path: Optional[Path | str] = None) -> ModuleType:
    """Load ``betta_corrections.py`` read-only via importlib (no package install)."""
    global _CORRECTIONS, _CORRECTIONS_PATH
    candidate = Path(path) if path is not None else default_corrections_path()
    if _CORRECTIONS is not None and _CORRECTIONS_PATH == candidate:
        return _CORRECTIONS
    name = "_nta_betta_corrections_write_boundary"
    spec = importlib.util.spec_from_file_location(name, candidate)
    if spec is None or spec.loader is None:
        raise refusal(ERR_INTERNAL_ERROR, "corrections module unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    _CORRECTIONS = module
    _CORRECTIONS_PATH = candidate
    return module


# ---------------------------------------------------------------------------
# Authorisation records
# ---------------------------------------------------------------------------


def operation_class_for_fields(fields: Iterable[str]) -> Optional[str]:
    field_set = set(fields)
    if not field_set:
        return None
    for name, allowed in OP_FIELDS.items():
        if field_set <= set(allowed):
            return name
    return None


def build_authorisation_core(
    *,
    source_sha256: str,
    tank: str,
    product_id: str,
    variant_id: Optional[str],
    fields: Iterable[str],
    operation_class: str,
    reason: str,
    operator: str,
    created_at: str,
    expires_at: str,
) -> dict:
    normalised_fields = sorted(set(fields))
    if not normalised_fields or any(
            FIELD_RE.fullmatch(field) is None for field in normalised_fields):
        raise AuthorisationError("fields must be a non-empty field-name list")
    if operation_class not in WRITE_OPERATIONS:
        raise AuthorisationError("operation_class must be a write operation")
    if not set(normalised_fields) <= set(OP_FIELDS[operation_class]):
        raise AuthorisationError(
            f"fields are outside the {operation_class} operation class")
    if SHA_RE.fullmatch(source_sha256 or "") is None:
        raise AuthorisationError("source_sha256 must be a lowercase SHA-256")
    if TANK_RE.fullmatch(tank or "") is None:
        raise AuthorisationError("tank must be a canonical tank ID")
    if GID_RE["product_id"].fullmatch(product_id or "") is None:
        raise AuthorisationError("product_id must be a Shopify product GID")
    if variant_id is not None and GID_RE["variant_id"].fullmatch(variant_id or "") is None:
        raise AuthorisationError("variant_id must be a Shopify variant GID")
    created = parse_iso8601(created_at)
    expires = parse_iso8601(expires_at)
    if created is None or expires is None:
        raise AuthorisationError("created_at/expires_at must be ISO-8601 with timezone")
    if expires <= created:
        raise AuthorisationError("expires_at must be after created_at")
    if not str(reason or "").strip():
        raise AuthorisationError("reason is required")
    if not str(operator or "").strip():
        raise AuthorisationError("operator is required")
    return {
        "schema": AUTHORISATION_SCHEMA,
        "source_sha256": source_sha256,
        "tank": tank,
        "product_id": product_id,
        "variant_id": variant_id,
        "fields": normalised_fields,
        "operation_class": operation_class,
        "reason": reason,
        "operator": operator,
        "created_at": created_at,
        "expires_at": expires_at,
    }


def write_authorisation_record(
    paths: BoundaryPaths,
    *,
    source_sha256: str,
    tank: str,
    product_id: str,
    variant_id: Optional[str],
    fields: Iterable[str],
    reason: str,
    operator: str,
    operation_class: Optional[str] = None,
    created_at: Optional[str] = None,
    expires_in_hours: float = 24.0,
    directory: Optional[Path | str] = None,
) -> Path:
    """Write ONE immutable authorisation record (O_EXCL, mode 0444).

    The CLI wrapper refuses to run as non-root; this library function is also
    used by tests against temporary state directories.
    """
    field_list = sorted(set(fields))
    if operation_class is None:
        derived = operation_class_for_fields(field_list)
        if derived is None:
            raise AuthorisationError(
                "fields do not map to exactly one operation class; pass an "
                "explicit operation_class")
        operation_class = derived
    if not isinstance(expires_in_hours, (int, float)) or isinstance(expires_in_hours, bool):
        raise AuthorisationError("expires_in_hours must be numeric")
    if not 0 < float(expires_in_hours) <= 168:
        raise AuthorisationError("expires_in_hours must be in (0, 168]")
    created_text = created_at if created_at is not None else utc_now()
    created = parse_iso8601(created_text)
    if created is None:
        raise AuthorisationError("created_at must be ISO-8601 with timezone")
    expires_text = (created + timedelta(hours=float(expires_in_hours))).isoformat()
    core = build_authorisation_core(
        source_sha256=source_sha256,
        tank=tank,
        product_id=product_id,
        variant_id=variant_id,
        fields=field_list,
        operation_class=operation_class,
        reason=reason,
        operator=operator,
        created_at=created_text,
        expires_at=expires_text,
    )
    digest = json_sha256(core)
    payload = {**core, "authorisation_sha256": digest}
    base = Path(directory) if directory is not None else paths.authorisations_dir
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"authorisation-{digest}.json"
    try:
        write_json_exclusive(path, payload, 0o444)
    except FileExistsError as exc:
        raise AuthorisationError(
            f"authorisation record already exists and is immutable: {path}") from exc
    return path


def validate_authorisation(
    record: Any,
    *,
    operation: str,
    required_fields: Iterable[str],
    target: Mapping[str, Any],
    source_sha256: str,
    now: Optional[datetime] = None,
) -> tuple[bool, str]:
    """Validate one authorisation record against an exact intended request."""
    if not isinstance(record, Mapping):
        return False, "record_not_object"
    if record.get("schema") != AUTHORISATION_SCHEMA:
        return False, "schema_mismatch"
    if set(record) != AUTHORISATION_KEYS:
        return False, "schema_fields_mismatch"
    digest = record.get("authorisation_sha256")
    if not isinstance(digest, str) or SHA_RE.fullmatch(digest) is None:
        return False, "self_hash_missing_or_invalid"
    core = {key: value for key, value in record.items()
            if key != "authorisation_sha256"}
    if json_sha256(core) != digest:
        return False, "self_hash_mismatch"
    fields = record.get("fields")
    if (not isinstance(fields, list) or not fields or
            any(not isinstance(field, str) or FIELD_RE.fullmatch(field) is None
                for field in fields)):
        return False, "fields_invalid"
    if record.get("operation_class") != operation:
        return False, "operation_class_mismatch"
    if not set(str(field) for field in required_fields) <= set(fields):
        return False, "field_scope_mismatch"
    if record.get("source_sha256") != source_sha256:
        return False, "source_sha256_mismatch"
    if record.get("product_id") != target.get("product_id"):
        return False, "product_id_mismatch"
    record_variant = record.get("variant_id")
    if record_variant is not None and target.get("variant_id") != record_variant:
        return False, "variant_id_mismatch"
    created = parse_iso8601(record.get("created_at"))
    expires = parse_iso8601(record.get("expires_at"))
    if created is None or expires is None:
        return False, "timestamps_invalid"
    if expires <= created:
        return False, "timestamps_invalid"
    current = now if now is not None else datetime.now(timezone.utc)
    if current >= expires:
        return False, "expired"
    if not str(record.get("reason") or "").strip():
        return False, "reason_missing"
    if not str(record.get("operator") or "").strip():
        return False, "operator_missing"
    return True, "ok"


def load_authorisation_record(paths: BoundaryPaths, digest: Any) -> Any:
    if not isinstance(digest, str) or SHA_RE.fullmatch(digest) is None:
        return None
    path = paths.authorisations_dir / f"authorisation-{digest}.json"
    try:
        return read_json(path)
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Replay / idempotency / budget ledger
# ---------------------------------------------------------------------------


class Ledger:
    """Persistent replay, idempotency, authorisation-use and budget ledger."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = self._load()

    def _load(self) -> dict:
        try:
            data = read_json(self.path)
        except FileNotFoundError:
            data = None
        except (OSError, json.JSONDecodeError) as exc:
            raise refusal(ERR_INTERNAL_ERROR, "ledger unreadable; fail closed") from exc
        if data is None:
            return {
                "schema": LEDGER_SCHEMA,
                "requests": {},
                "idempotency": {},
                "authorisations": {},
                "day_counters": {},
            }
        if data.get("schema") != LEDGER_SCHEMA or not isinstance(data.get("requests"), dict):
            raise refusal(ERR_INTERNAL_ERROR, "ledger schema mismatch; fail closed")
        for key, default in (
            ("idempotency", {}), ("authorisations", {}), ("day_counters", {}),
        ):
            if not isinstance(data.get(key), dict):
                data[key] = default
        return data

    def save(self) -> None:
        atomic_write_json(self.path, self.data, 0o600)

    # -- request replay -----------------------------------------------------

    def request_entry(self, request_id: str) -> Optional[dict]:
        entry = self.data["requests"].get(request_id)
        return entry if isinstance(entry, dict) else None

    def store_request(
        self,
        request_id: str,
        request_sha256: str,
        state: str,
        response: Any,
        *,
        intent: Optional[dict] = None,
        receipt_path: Optional[str] = None,
        receipt_sha256: Optional[str] = None,
    ) -> None:
        entry = {
            "request_sha256": request_sha256,
            "state": state,
            "at": utc_now(),
            "response": response,
            "intent": intent,
            "receipt_path": receipt_path,
            "receipt_sha256": receipt_sha256,
        }
        self.data["requests"][request_id] = entry
        self.save()

    def set_request_state(self, request_id: str, state: str) -> None:
        entry = self.data["requests"].get(request_id)
        if isinstance(entry, dict):
            entry["state"] = state
            entry["at"] = utc_now()
            self.save()

    def reconcile_products(self, product_id: Any) -> list:
        rows = []
        for request_id, entry in self.data["requests"].items():
            if not isinstance(entry, dict):
                continue
            if entry.get("state") not in (STATE_RECONCILIATION_REQUIRED, STATE_MUTATING):
                continue
            intent = entry.get("intent") or {}
            target = intent.get("target") or {}
            if target.get("product_id") != product_id:
                continue
            rows.append({
                "request_id": request_id,
                "operation": intent.get("operation"),
                "intended": intent.get("intended"),
                "state": entry.get("state"),
            })
        return rows

    # -- idempotency --------------------------------------------------------

    @staticmethod
    def idempotency_fingerprint(target: Mapping[str, Any], operation: str, key: str) -> str:
        return json_sha256({
            "operation": operation,
            "product_id": target.get("product_id"),
            "variant_id": target.get("variant_id"),
            "inventory_item_id": target.get("inventory_item_id"),
            "location_id": target.get("location_id"),
            "idempotency_key": key,
        })

    def idempotency_owner(self, fingerprint: str) -> Optional[str]:
        entry = self.data["idempotency"].get(fingerprint)
        if isinstance(entry, dict):
            return entry.get("request_id")
        return None

    def store_idempotency(self, fingerprint: str, request_id: str) -> None:
        self.data["idempotency"][fingerprint] = {
            "request_id": request_id, "at": utc_now(),
        }

    # -- authorisations (single use) ---------------------------------------

    def authorisation_owner(self, digest: str) -> Optional[str]:
        entry = self.data["authorisations"].get(digest)
        if isinstance(entry, dict):
            return entry.get("request_id")
        return None

    def consume_authorisation(self, digest: str, request_id: str) -> None:
        self.data["authorisations"][digest] = {
            "request_id": request_id, "at": utc_now(), "state": "CONSUMED",
        }

    # -- budgets ------------------------------------------------------------

    @staticmethod
    def utc_day(now: Optional[datetime] = None) -> str:
        current = now if now is not None else datetime.now(timezone.utc)
        return current.date().isoformat()

    def writes_today(self, day: Optional[str] = None) -> int:
        key = day if day is not None else self.utc_day()
        value = self.data["day_counters"].get(key, 0)
        return value if isinstance(value, int) else 0

    def bump_day(self, day: Optional[str] = None) -> None:
        key = day if day is not None else self.utc_day()
        self.data["day_counters"][key] = self.writes_today(key) + 1


# ---------------------------------------------------------------------------
# Signing key + receipts
# ---------------------------------------------------------------------------


class SigningKeyError(RuntimeError):
    pass


def load_signing_key(path: Path, *, create: bool = True) -> bytes:
    """Load the HMAC key (hex, 0600); generate it on first run when absent."""
    path = Path(path)
    try:
        text = path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        if not create:
            raise SigningKeyError("signing key is missing")
        material = os.urandom(32).hex().encode("ascii") + b"\n"
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            text = path.read_text(encoding="ascii").strip()
        else:
            try:
                os.write(descriptor, material)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            fsync_directory(path.parent)
            return bytes.fromhex(material.decode("ascii").strip())
    except OSError as exc:
        raise SigningKeyError("signing key is unreadable") from exc
    try:
        key = bytes.fromhex(text)
    except ValueError as exc:
        raise SigningKeyError("signing key is malformed") from exc
    if len(key) < 32:
        raise SigningKeyError("signing key is too short")
    return key


def receipt_core(full: Mapping[str, Any]) -> dict:
    return {key: value for key, value in full.items()
            if key not in ("receipt_sha256", "receipt_signature")}


def sign_receipt(core: Mapping[str, Any], key: bytes) -> dict:
    if set(core) != set(RECEIPT_CORE_KEYS):
        raise refusal(ERR_INTERNAL_ERROR, "receipt core is incomplete")
    if core.get("schema") != RECEIPT_SCHEMA:
        raise refusal(ERR_INTERNAL_ERROR, "receipt schema mismatch")
    digest = json_sha256(core)
    signature = hmac.new(
        key, canonical_json(core).encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        **core,
        "receipt_sha256": digest,
        "receipt_signature": f"hmac-sha256:{signature}",
    }


def verify_receipt_object(full: Any, key: bytes) -> tuple[bool, str]:
    if not isinstance(full, Mapping):
        return False, "receipt_not_object"
    if full.get("schema") != RECEIPT_SCHEMA:
        return False, "schema_mismatch"
    core = receipt_core(full)
    if set(core) != set(RECEIPT_CORE_KEYS):
        return False, "receipt_fields_mismatch"
    digest = full.get("receipt_sha256")
    if not isinstance(digest, str) or SHA_RE.fullmatch(digest) is None:
        return False, "receipt_sha_missing_or_invalid"
    if json_sha256(core) != digest:
        return False, "receipt_sha_mismatch"
    signature = full.get("receipt_signature")
    if (not isinstance(signature, str) or
            not signature.startswith("hmac-sha256:")):
        return False, "signature_missing_or_invalid"
    expected = hmac.new(
        key, canonical_json(core).encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature[len("hmac-sha256:"):], expected):
        return False, "signature_mismatch"
    return True, "ok"


def receipt_path_for(paths: BoundaryPaths, request_id: str) -> Path:
    return paths.receipts_dir / f"receipt-{request_id}.json"


def write_receipt(paths: BoundaryPaths, full: Mapping[str, Any]) -> Path:
    request_id = require_string(full.get("request_id"), "receipt.request_id")
    path = receipt_path_for(paths, request_id)
    try:
        return write_json_exclusive(path, dict(full), 0o600)
    except FileExistsError:
        existing = read_json(path)
        if existing != dict(full):
            raise refusal(ERR_INTERNAL_ERROR, "existing receipt differs; fail closed")
        return path


# ---------------------------------------------------------------------------
# Request schema validation
# ---------------------------------------------------------------------------


def _validate_request_shape(request: Any) -> tuple[dict, str]:
    if not isinstance(request, dict):
        raise refusal(ERR_BAD_REQUEST, "request must be a JSON object")
    if set(request) - REQUEST_KEYS:
        raise refusal(ERR_BAD_REQUEST, "request has unknown top-level keys")
    if request.get("schema") != REQUEST_SCHEMA:
        raise refusal(ERR_BAD_REQUEST, "request schema mismatch")
    rid = request.get("request_id")
    if not isinstance(rid, str):
        raise refusal(ERR_BAD_REQUEST, "request_id must be a UUID string")
    try:
        parsed = uuid.UUID(rid)
    except (ValueError, AttributeError, TypeError) as exc:
        raise refusal(ERR_BAD_REQUEST, "request_id must be a UUID string") from exc
    if parsed.version != 4:
        raise refusal(ERR_BAD_REQUEST, "request_id must be a version-4 UUID")
    if request.get("operation") not in OPERATIONS:
        # Unknown operations fail closed at step 4, but the value must at
        # least be a non-empty string to reach it.
        if not isinstance(request.get("operation"), str) or not request["operation"]:
            raise refusal(ERR_BAD_REQUEST, "operation must be a non-empty string")
    mode = request.get("mode")
    if mode not in ("apply", "dry_run"):
        raise refusal(ERR_BAD_REQUEST, "mode must be apply or dry_run")
    target = request.get("target", {}) or {}
    if not isinstance(target, dict):
        raise refusal(ERR_BAD_REQUEST, "target must be an object")
    if set(target) - TARGET_KEYS:
        raise refusal(ERR_BAD_REQUEST, "target has unknown keys")
    operations = request.get("operations", []) or []
    if not isinstance(operations, list):
        raise refusal(ERR_BAD_REQUEST, "operations must be a list")
    if request.get("operation") in WRITE_OPERATIONS and not operations:
        raise refusal(ERR_BAD_REQUEST, "write operations require operations[]")
    authorisation = request.get("authorisation")
    if request.get("operation") in WRITE_OPERATIONS:
        if not isinstance(authorisation, dict):
            raise refusal(ERR_BAD_REQUEST, "authorisation object is required")
        if authorisation.get("kind") not in ("standing", "owner"):
            raise refusal(ERR_BAD_REQUEST, "authorisation.kind must be standing or owner")
        if set(authorisation) - {"kind", "authorisation_sha256"}:
            raise refusal(ERR_BAD_REQUEST, "authorisation has unknown keys")
        if authorisation.get("kind") == "owner":
            digest = authorisation.get("authorisation_sha256")
            if not isinstance(digest, str) or SHA_RE.fullmatch(digest) is None:
                raise refusal(
                    ERR_BAD_REQUEST,
                    "owner authorisation requires authorisation_sha256")
    else:
        if request.get("operation") in (OP_STATUS, OP_VERIFY):
            # status/verify are read-only: no authority objects are accepted.
            if authorisation is not None:
                raise refusal(
                    ERR_BAD_REQUEST,
                    "read-only operations must not carry authorisation")
            if operations:
                raise refusal(
                    ERR_BAD_REQUEST, "read-only operations must not carry operations[]")
            if request.get("operation") == OP_STATUS and target:
                raise refusal(ERR_BAD_REQUEST, "status does not accept a target")
        # Unknown operations reach step 4 and fail with operation_not_allowed.
    return request, rid


def _validate_target_for_operation(request: dict) -> dict:
    operation = request["operation"]
    target = request.get("target", {}) or {}
    if operation == OP_STATUS:
        return target
    if operation == OP_VERIFY:
        require_gid(target, "product_id", required=True)
        require_gid(target, "location_id", required=False)
        return target
    if operation == OP_UPDATE_DETAILS:
        require_gid(target, "product_id", required=True)
        return target
    if operation == OP_SET_INVENTORY:
        require_gid(target, "product_id", required=True)
        require_gid(target, "variant_id", required=True)
        require_gid(target, "inventory_item_id", required=True)
        require_gid(target, "location_id", required=True)
        return target
    if operation == OP_MEDIA_APPEND:
        require_gid(target, "product_id", required=True)
        return target
    if operation == OP_MERCH_UPDATE:
        require_gid(target, "product_id", required=True)
        require_gid(target, "variant_id", required=True)
        require_gid(target, "inventory_item_id", required=True)
        return target
    raise refusal(ERR_OPERATION_NOT_ALLOWED, f"unknown operation: {operation}")


ALLOWED_OP_KEYS = {
    OP_UPDATE_DETAILS: frozenset({"type", "title", "arrival_date", "expected"}),
    OP_SET_INVENTORY: frozenset({"type", "quantity", "reason", "expected"}),
    OP_MEDIA_APPEND: frozenset({"type", "assets", "expected"}),
    OP_MERCH_UPDATE: frozenset({"type", "vendor", "price", "cost", "expected"}),
}


def validate_operations(request: dict) -> list:
    """Validate the per-operation payload shape (step 2 semantics).

    Returns the normalised operations; raises ``bad_request`` refusals.
    """
    operation = request["operation"]
    if operation not in WRITE_OPERATIONS:
        return []
    operations = request["operations"]
    if len(operations) != 1:
        raise refusal(
            ERR_BAD_REQUEST, "exactly one operations[] entry per request")
    entry = operations[0]
    if not isinstance(entry, dict):
        raise refusal(ERR_BAD_REQUEST, "operations[0] must be an object")
    if entry.get("type") != operation:
        raise refusal(ERR_BAD_REQUEST, "operations[0].type must equal operation")
    unknown = set(entry) - ALLOWED_OP_KEYS[operation]
    if unknown:
        raise refusal(ERR_BAD_REQUEST, "operations[0] has unknown keys")
    if operation == OP_UPDATE_DETAILS:
        fields = {field for field in OP_FIELDS[OP_UPDATE_DETAILS] if field in entry}
        if not fields:
            raise refusal(
                ERR_BAD_REQUEST, "update_details requires title and/or arrival_date")
        if "arrival_date" in entry:
            _require_date(entry.get("arrival_date"), "operations[0].arrival_date")
        if "title" in entry:
            require_string(entry.get("title"), "operations[0].title", max_length=255)
        expected = entry.get("expected")
        if (not isinstance(expected, dict) or set(expected) != fields or
                any(not isinstance(value, str) for value in expected.values())):
            raise refusal(
                ERR_BAD_REQUEST,
                "update_details expected must cover exactly the changed fields")
        if "arrival_date" in expected:
            _require_date(expected["arrival_date"], "expected.arrival_date")
    elif operation == OP_SET_INVENTORY:
        quantity = entry.get("quantity")
        if not _is_int(quantity) or quantity < 0:
            raise refusal(ERR_BAD_REQUEST, "set_inventory quantity must be a non-negative integer")
        if entry.get("reason") not in ("received", "correction"):
            raise refusal(ERR_BAD_REQUEST, "set_inventory reason must be received or correction")
        expected = entry.get("expected")
        if not isinstance(expected, dict):
            raise refusal(ERR_BAD_REQUEST, "set_inventory requires expected")
        if not _is_int(expected.get("available")) or expected["available"] < 0:
            raise refusal(ERR_BAD_REQUEST, "expected.available must be a non-negative integer")
        for key in ("inventory_item_id", "location_id"):
            if key in expected and (
                    not isinstance(expected[key], str) or not expected[key]):
                raise refusal(ERR_BAD_REQUEST, f"expected.{key} must be a GID string")
        idempotency_key = (request.get("evidence") or {}).get("idempotency_key")
        if not isinstance(idempotency_key, str) or not SAFE_TOKEN_RE.fullmatch(idempotency_key):
            raise refusal(ERR_BAD_REQUEST, "set_inventory requires an idempotency_key")
    elif operation == OP_MEDIA_APPEND:
        assets = entry.get("assets")
        if not isinstance(assets, list) or not assets:
            raise refusal(ERR_BAD_REQUEST, "media_append requires a non-empty assets list")
        roles = []
        for asset in assets:
            if not isinstance(asset, dict):
                raise refusal(ERR_BAD_REQUEST, "media asset must be an object")
            if set(asset) - {"path", "sha256", "role"}:
                raise refusal(ERR_BAD_REQUEST, "media asset has unknown keys")
            if asset.get("role") not in ("hero", "original"):
                raise refusal(ERR_BAD_REQUEST, "media asset role must be hero or original")
            roles.append(asset["role"])
            require_string(asset.get("path"), "media asset path", max_length=4096)
            if not os.path.isabs(asset["path"]):
                raise refusal(ERR_BAD_REQUEST, "media asset path must be absolute")
            if not isinstance(asset.get("sha256"), str) or SHA_RE.fullmatch(asset["sha256"]) is None:
                raise refusal(ERR_BAD_REQUEST, "media asset sha256 must be a lowercase SHA-256")
        if len(set(roles)) != len(roles) or set(roles) != {"hero", "original"}:
            raise refusal(
                ERR_BAD_REQUEST,
                "media_append requires exactly one hero and one original asset")
        expected = entry.get("expected")
        if expected is not None:
            if (not isinstance(expected, dict) or set(expected) != {"media_ids"} or
                    not isinstance(expected["media_ids"], list) or
                    any(not isinstance(value, str) for value in expected["media_ids"])):
                raise refusal(ERR_BAD_REQUEST, "media expected must be {media_ids: [...]} ")
    elif operation == OP_MERCH_UPDATE:
        fields = {field for field in OP_FIELDS[OP_MERCH_UPDATE] if field in entry}
        if not fields:
            raise refusal(ERR_BAD_REQUEST, "merch_update requires vendor, price and/or cost")
        if "vendor" in entry:
            require_string(entry.get("vendor"), "operations[0].vendor", max_length=255)
        for field in ("price", "cost"):
            if field in entry:
                _require_decimal(entry.get(field), f"operations[0].{field}")
        expected = entry.get("expected")
        if not isinstance(expected, dict) or set(expected) != fields:
            raise refusal(
                ERR_BAD_REQUEST,
                "merch expected must cover exactly the changed fields")
        if "vendor" in expected and not isinstance(expected["vendor"], str):
            raise refusal(ERR_BAD_REQUEST, "expected.vendor must be a string")
        for field in ("price", "cost"):
            if field in expected:
                _require_decimal(expected[field], f"expected.{field}")
    return operations


def _require_date(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise refusal(ERR_BAD_REQUEST, f"{label}: YYYY-MM-DD required")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise refusal(ERR_BAD_REQUEST, f"{label}: invalid calendar date") from exc
    return value


def _require_decimal(value: Any, label: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise refusal(ERR_BAD_REQUEST, f"{label}: decimal required")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise refusal(ERR_BAD_REQUEST, f"{label}: decimal required") from exc
    if not parsed.is_finite() or parsed < 0:
        raise refusal(ERR_BAD_REQUEST, f"{label}: non-negative finite decimal required")
    if -parsed.as_tuple().exponent > 4:
        raise refusal(ERR_BAD_REQUEST, f"{label}: at most 4 decimal places")
    return format(parsed.normalize(), "f") if parsed == parsed.normalize() else format(parsed, "f")


def request_fields(request: dict) -> set:
    """The authorisation field set a request consumes."""
    operation = request["operation"]
    if operation not in WRITE_OPERATIONS:
        return set()
    entry = request["operations"][0]
    if operation == OP_UPDATE_DETAILS:
        return {field for field in OP_FIELDS[OP_UPDATE_DETAILS] if field in entry}
    if operation == OP_MERCH_UPDATE:
        return {field for field in OP_FIELDS[OP_MERCH_UPDATE] if field in entry}
    return set(OP_FIELDS[operation])


# ---------------------------------------------------------------------------
# Evidence validation (mirrors the uploader identity gate)
# ---------------------------------------------------------------------------


def validate_evidence(
    request: dict,
    policy: dict,
    paths: BoundaryPaths,
    corrections: Optional[ModuleType],
) -> dict:
    """Validate manifest + identity + correction bindings; raises refusals.

    ``corrections`` is the read-only sibling module, or ``None`` when it could
    not be loaded; a request that references a correction record then fails
    closed (the deployment must install ``betta_corrections.py`` next to the
    boundary files in the root-owned code root).
    """
    target = request.get("target") or {}
    evidence = request.get("evidence")
    if not isinstance(evidence, dict):
        raise refusal(ERR_EVIDENCE_INVALID, "evidence object is required")
    if set(evidence) - EVIDENCE_KEYS:
        raise refusal(ERR_EVIDENCE_INVALID, "evidence has unknown keys")
    manifest_path_raw = evidence.get("manifest_path")
    if not isinstance(manifest_path_raw, str) or not manifest_path_raw:
        raise refusal(ERR_EVIDENCE_INVALID, "evidence.manifest_path is required")
    manifest_path = Path(manifest_path_raw).expanduser()
    if not manifest_path.is_absolute():
        raise refusal(ERR_EVIDENCE_INVALID, "evidence.manifest_path must be absolute")
    roots = [Path(root) for root in policy.get("allowed_roots") or []]
    if not roots or not is_under_roots(manifest_path, roots):
        raise refusal(ERR_EVIDENCE_INVALID, "manifest path is outside the allowed roots")
    manifest_path = manifest_path.resolve()
    manifest_sha256 = evidence.get("manifest_sha256")
    if (not isinstance(manifest_sha256, str) or
            SHA_RE.fullmatch(manifest_sha256) is None):
        raise refusal(ERR_EVIDENCE_INVALID, "evidence.manifest_sha256 is required")
    try:
        actual_manifest_sha = sha256_file(manifest_path)
    except OSError as exc:
        raise refusal(ERR_EVIDENCE_INVALID, "manifest file is unreadable") from exc
    if actual_manifest_sha != manifest_sha256:
        raise refusal(ERR_EVIDENCE_INVALID, "manifest bytes do not match manifest_sha256")
    try:
        manifest = read_json(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise refusal(ERR_EVIDENCE_INVALID, "manifest is not valid JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise refusal(
            ERR_EVIDENCE_INVALID,
            f"manifest schema must be {MANIFEST_SCHEMA}")
    items = manifest.get("items")
    if not isinstance(items, list) or not items:
        raise refusal(ERR_EVIDENCE_INVALID, "manifest items must be a non-empty list")

    source_sha256 = evidence.get("source_sha256")
    if not isinstance(source_sha256, str) or SHA_RE.fullmatch(source_sha256) is None:
        raise refusal(ERR_EVIDENCE_INVALID, "evidence.source_sha256 is required")
    identity = evidence.get("identity")
    if not isinstance(identity, dict) or set(identity) != IDENTITY_KEYS:
        raise refusal(
            ERR_EVIDENCE_INVALID,
            "evidence.identity must be exactly the 5-key identity block")
    if identity.get("source_sha256") != source_sha256:
        raise refusal(ERR_EVIDENCE_INVALID, "identity source hash differs from evidence source hash")
    detected = identity.get("detected_tank")
    requested = identity.get("requested_tank")
    accepted = identity.get("accepted_tank")
    for label, value in (("detected_tank", detected), ("requested_tank", requested),
                         ("accepted_tank", accepted)):
        if not isinstance(value, str) or TANK_RE.fullmatch(value) is None:
            raise refusal(ERR_EVIDENCE_INVALID, f"identity.{label} must be a canonical tank ID")
    if requested != accepted:
        raise refusal(ERR_EVIDENCE_INVALID, "identity requested_tank must equal accepted_tank")

    # The item is selected by the accepted (==item) tank; bindings checked exactly.
    matches = [item for item in items
               if isinstance(item, dict) and item.get("tank_id") == accepted]
    if len(matches) != 1:
        raise refusal(
            ERR_EVIDENCE_INVALID,
            "manifest must contain exactly one item for the accepted tank")
    item = matches[0]
    if item.get("product_id") != target.get("product_id"):
        raise refusal(ERR_EVIDENCE_INVALID, "manifest item product differs from target")
    if target.get("variant_id") is not None and item.get("variant_id") != target.get("variant_id"):
        raise refusal(ERR_EVIDENCE_INVALID, "manifest item variant differs from target")
    if item.get("identity") != identity:
        raise refusal(ERR_EVIDENCE_INVALID, "manifest item identity differs from evidence")
    original = item.get("original")
    if not isinstance(original, dict) or original.get("sha256") != source_sha256:
        raise refusal(
            ERR_EVIDENCE_INVALID,
            "identity source hash differs from the manifest camera original")

    correction_digest = evidence.get("correction_sha256")
    if correction_digest != identity.get("correction_sha256"):
        raise refusal(
            ERR_EVIDENCE_INVALID,
            "evidence.correction_sha256 must equal identity.correction_sha256")
    qa_digest = evidence.get("qa_receipt_sha256")
    if qa_digest is not None and (
            not isinstance(qa_digest, str) or SHA_RE.fullmatch(qa_digest) is None):
        raise refusal(ERR_EVIDENCE_INVALID, "evidence.qa_receipt_sha256 must be null or a SHA-256")
    idempotency_key = evidence.get("idempotency_key")
    if idempotency_key is not None and (
            not isinstance(idempotency_key, str) or
            not SAFE_TOKEN_RE.fullmatch(idempotency_key)):
        raise refusal(ERR_EVIDENCE_INVALID, "evidence.idempotency_key is malformed")

    if correction_digest is None:
        if requested != accepted:
            raise refusal(ERR_EVIDENCE_INVALID, "requested tank differs from accepted tank")
        if detected != requested:
            raise refusal(
                ERR_EVIDENCE_INVALID,
                "vision-detected tank differs from the requested tank without a correction record")
    else:
        if corrections is None:
            raise refusal(ERR_INTERNAL_ERROR, "corrections module is unavailable")
        if (not isinstance(correction_digest, str) or
                SHA_RE.fullmatch(correction_digest) is None):
            raise refusal(ERR_CORRECTION_INVALID, "correction_sha256 must be a lowercase SHA-256")
        record_path = corrections.record_path_for(
            correction_digest, paths.corrections_dir)
        verdict = corrections.validate_correction(
            record_path,
            source_sha256=source_sha256,
            requested_tank=requested,
            accepted_tank=accepted,
            product_id=item.get("product_id"),
            variant_id=target.get("variant_id") or item.get("variant_id"),
            operation_fields=list(IDENTITY_OPERATION_FIELDS),
        )
        if verdict.get("valid") is not True:
            raise refusal(
                ERR_CORRECTION_INVALID,
                f"identity correction rejected: {verdict.get('reason')}")

    return {
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha256,
        "batch_id": manifest.get("batch_id"),
        "source_sha256": source_sha256,
        "identity": dict(identity),
        "correction_sha256": correction_digest,
        "qa_receipt_sha256": qa_digest,
        "idempotency_key": idempotency_key,
    }


# ---------------------------------------------------------------------------
# Operation caps / budgets (step 8) and CAS (step 9)
# ---------------------------------------------------------------------------


def validate_operation_caps(
    request: dict,
    policy: dict,
    ledger: Ledger,
    media_bindings: Optional[list] = None,
) -> dict:
    """Policy caps + budgets for the request; raises ``policy_refused``."""
    operation = request["operation"]
    entry = request["operations"][0]
    config = policy["operations"].get(operation) or {}
    checks = {"operation": operation}
    if operation == OP_UPDATE_DETAILS:
        allowed = set(config.get("fields") or [])
        fields = {field for field in OP_FIELDS[operation] if field in entry}
        if not fields <= allowed:
            raise refusal(
                ERR_POLICY_REFUSED,
                "update_details fields are outside the standing field allowlist")
    elif operation == OP_SET_INVENTORY:
        if entry["reason"] not in (config.get("reasons") or []):
            raise refusal(ERR_POLICY_REFUSED, "set_inventory reason is outside policy")
        if entry["quantity"] != config.get("target"):
            raise refusal(
                ERR_POLICY_REFUSED,
                "set_inventory quantity is not the policy target quantity")
        if entry["expected"]["available"] not in (config.get("allowed_from") or []):
            raise refusal(
                ERR_POLICY_REFUSED,
                "set_inventory baseline is outside the policy allowed_from set")
        checks["inventory_transition"] = {
            "from": entry["expected"]["available"], "to": entry["quantity"],
        }
    elif operation == OP_MEDIA_APPEND:
        assets = entry["assets"]
        if len(assets) > int(config.get("max_assets", 0)):
            raise refusal(ERR_POLICY_REFUSED, "media asset count exceeds policy")
        max_bytes = int(config.get("max_bytes", 0))
        mime_types = set(config.get("mime_types") or [])
        bindings = {binding["role"]: binding for binding in media_bindings or []}
        for asset in assets:
            binding = bindings.get(asset["role"])
            if binding is None:
                raise refusal(ERR_POLICY_REFUSED, "media asset was not evidence-bound")
            if binding["size_bytes"] > max_bytes:
                raise refusal(ERR_POLICY_REFUSED, "media asset exceeds the size cap")
            if binding["mime_type"] not in mime_types:
                raise refusal(ERR_POLICY_REFUSED, "media asset MIME type is not allowed")
        checks["media"] = [
            {"role": binding["role"], "sha256": binding["sha256"],
             "bytes": binding["size_bytes"], "mime_type": binding["mime_type"]}
            for binding in media_bindings or []
        ]
    elif operation == OP_MERCH_UPDATE:
        allowed = set(config.get("fields") or [])
        fields = {field for field in OP_FIELDS[operation] if field in entry}
        if not fields <= allowed:
            raise refusal(
                ERR_POLICY_REFUSED,
                "merch_update fields are outside the policy allowlist")
    budgets = policy["budgets"]
    operation_count = len(request.get("operations") or [])
    if operation_count > budgets["max_operations_per_request"]:
        raise refusal(ERR_POLICY_REFUSED, "operations exceed max_operations_per_request")
    writes_today = ledger.writes_today()
    if writes_today + 1 > budgets["max_daily_writes"]:
        raise refusal(ERR_POLICY_REFUSED, "daily write budget exhausted")
    checks["budget"] = {
        "writes_today": writes_today,
        "max_daily_writes": budgets["max_daily_writes"],
        "max_operations_per_request": budgets["max_operations_per_request"],
    }
    return checks


def bind_media_assets(request: dict, policy: dict) -> list:
    """Bind media asset files to their declared paths/hashes (evidence family)."""
    roots = [Path(root) for root in policy.get("allowed_roots") or []]
    bindings = []
    for asset in request["operations"][0]["assets"]:
        path = Path(asset["path"]).expanduser()
        if not is_under_roots(path, roots):
            raise refusal(ERR_EVIDENCE_INVALID, "media asset path is outside the allowed roots")
        path = path.resolve()
        if not path.is_file():
            raise refusal(ERR_EVIDENCE_INVALID, "media asset file is missing")
        try:
            size_bytes = path.stat().st_size
            actual_sha = sha256_file(path)
            mime_type = detect_image_mime(path)
        except OSError as exc:
            raise refusal(ERR_EVIDENCE_INVALID, "media asset is unreadable") from exc
        if actual_sha != asset["sha256"]:
            raise refusal(ERR_EVIDENCE_INVALID, "media asset bytes do not match sha256")
        if mime_type is None:
            raise refusal(ERR_EVIDENCE_INVALID, "media asset is not png/jpeg")
        bindings.append({
            "role": asset["role"],
            "path": str(path),
            "sha256": asset["sha256"],
            "size_bytes": size_bytes,
            "mime_type": mime_type,
        })
    return bindings


def media_expected_alts(request: dict, evidence: dict) -> dict:
    batch_id = evidence.get("batch_id")
    tank = evidence["identity"]["accepted_tank"]
    if not isinstance(batch_id, str) or not batch_id:
        raise refusal(ERR_EVIDENCE_INVALID, "manifest batch_id is required for media_append")
    alts = {}
    for asset in request["operations"][0]["assets"]:
        alts[asset["role"]] = media_alt(batch_id, tank, asset["role"], asset["sha256"])
    return alts


def cas_expectation(request: dict, before: Mapping[str, Any]) -> None:
    """Compare-and-set against the fresh pre-write readback (raises drift)."""
    operation = request["operation"]
    entry = request["operations"][0]
    target = request.get("target") or {}
    if operation == OP_UPDATE_DETAILS:
        expected = entry["expected"]
        for field, value in expected.items():
            if before.get(field) != value:
                raise refusal(
                    ERR_BASELINE_DRIFT,
                    f"{field} drifted from the expected baseline")
    elif operation == OP_SET_INVENTORY:
        expected = entry["expected"]
        if before.get("available") != expected["available"]:
            raise refusal(ERR_BASELINE_DRIFT, "available quantity drifted from the expected baseline")
        if before.get("inventory_item_id") != target["inventory_item_id"]:
            raise refusal(ERR_BASELINE_DRIFT, "inventory item does not match the target")
        if before.get("location_id") != target["location_id"]:
            raise refusal(ERR_BASELINE_DRIFT, "location does not match the target")
    elif operation == OP_MEDIA_APPEND:
        expected = entry.get("expected") or {}
        ids = expected.get("media_ids")
        if ids is not None:
            current = [value.get("id") for value in before.get("media") or []]
            if current != list(ids):
                raise refusal(ERR_BASELINE_DRIFT, "media set drifted from the expected baseline")
    elif operation == OP_MERCH_UPDATE:
        expected = entry["expected"]
        for field, value in expected.items():
            if field in ("price", "cost"):
                if not numeric_equal(before.get(field), value):
                    raise refusal(ERR_BASELINE_DRIFT, f"{field} drifted from the expected baseline")
            elif before.get(field) != value:
                raise refusal(ERR_BASELINE_DRIFT, f"{field} drifted from the expected baseline")


def assert_readback_target(request: dict, before: Mapping[str, Any]) -> None:
    target = request.get("target") or {}
    if before.get("product_id") != target.get("product_id"):
        raise refusal(ERR_BASELINE_DRIFT, "fresh readback product does not match the target")
    for key in ("variant_id", "inventory_item_id", "location_id"):
        if target.get(key) is not None and before.get(key) != target.get(key):
            raise refusal(ERR_BASELINE_DRIFT, f"fresh readback {key} does not match the target")


def duplicate_media_alts(before: Mapping[str, Any], alts: Mapping[str, str]) -> Optional[str]:
    existing = [value.get("alt") for value in before.get("media") or []]
    wanted = list(alts.values())
    for alt in wanted:
        if existing.count(alt) > 0:
            return alt
    return None


def snapshot_readback(before: Mapping[str, Any]) -> dict:
    return {key: before.get(key) for key in PROTECTED_SNAPSHOT_KEYS}


def protected_drift(before: Mapping[str, Any], after: Mapping[str, Any],
                    allowed: Iterable[str]) -> list:
    allowed_set = set(allowed)
    drift = []
    for key in PROTECTED_SNAPSHOT_KEYS:
        if key in allowed_set:
            continue
        left, right = before.get(key), after.get(key)
        if key in ("price", "cost"):
            if not numeric_equal(left, right):
                drift.append(key)
        elif left != right:
            drift.append(key)
    return drift


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


class BoundaryEngine:
    """Fail-closed validation engine for write-boundary requests.

    ``handle`` is deliberately transport-free: the daemon supplies the Shopify
    service and the peer uid, tests supply fakes.
    """

    def __init__(
        self,
        paths: BoundaryPaths,
        *,
        corrections_path: Optional[Path | str] = None,
        clock: Callable[[], str] = utc_now,
        version_sha256: Optional[str] = None,
        logger: Optional[Callable[[dict], None]] = None,
    ):
        self.paths = BoundaryPaths(paths.state_dir)
        self.corrections_path = (
            Path(corrections_path) if corrections_path is not None
            else default_corrections_path()
        )
        self.clock = clock
        self.version_sha256 = version_sha256
        self._corrections: Optional[ModuleType] = None
        self._ledger: Optional[Ledger] = None
        self.logger = logger if logger is not None else (lambda event: None)

    # -- infrastructure ----------------------------------------------------

    def corrections(self) -> ModuleType:
        if self._corrections is None:
            self._corrections = load_corrections_module(self.corrections_path)
        return self._corrections

    def corrections_or_none(self) -> Optional[ModuleType]:
        """Load the corrections module, or return None when unavailable.

        Evidence validation fails closed only when a request actually
        references a correction record, so a missing module cannot silently
        bypass correction checks for correction-bearing requests.
        """
        try:
            return self.corrections()
        except Exception:  # noqa: BLE001 - fail closed at the use site
            self._log(event="corrections_module_unavailable",
                      path=str(self.corrections_path))
            return None

    def ledger(self) -> Ledger:
        if self._ledger is None:
            self._ledger = Ledger(self.paths.ledger_path)
        return self._ledger

    def policy(self) -> tuple[Optional[dict], Optional[str]]:
        return load_policy(self.paths.policy_path)

    def disabled(self) -> bool:
        return os.path.exists(self.paths.disabled_path)

    def _log(self, **event: Any) -> None:
        try:
            self.logger(event)
        except Exception:  # logging must never break the boundary
            pass

    def _response(
        self,
        ok: bool,
        outcome: str,
        *,
        receipt: Optional[dict] = None,
        readback: Any = None,
        error_code: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> dict:
        return {
            "schema": RESPONSE_SCHEMA,
            "ok": ok,
            "outcome": outcome,
            "receipt": receipt,
            "receipt_sha256": receipt.get("receipt_sha256") if receipt else None,
            "receipt_signature": receipt.get("receipt_signature") if receipt else None,
            "error_code": error_code,
            "detail": detail,
            "readback": readback,
        }

    def _snapshot_for_receipt(self, request: dict) -> dict:
        return {
            "manifest_path": request.get("manifest_path"),
            "manifest_sha256": request.get("manifest_sha256"),
            "source_sha256": request.get("source_sha256"),
            "identity": request.get("identity"),
            "correction_sha256": request.get("correction_sha256"),
            "qa_receipt_sha256": request.get("qa_receipt_sha256"),
            "idempotency_key": request.get("idempotency_key"),
        }

    def _sign_and_store_receipt(
        self,
        request: dict,
        *,
        mode: str,
        outcome: str,
        evidence_ref: Mapping[str, Any],
        auth_ref: Mapping[str, Any],
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        checks: Mapping[str, Any],
    ) -> dict:
        core = {
            "schema": RECEIPT_SCHEMA,
            "request_id": request["request_id"],
            "operation": request["operation"],
            "mode": mode,
            "outcome": outcome,
            "target": {
                key: (request.get("target") or {}).get(key)
                for key in sorted(TARGET_KEYS)
            },
            "evidence": dict(evidence_ref),
            "authorisation": dict(auth_ref),
            "before": snapshot_readback(before) if before else None,
            "after": snapshot_readback(after) if after else None,
            "checks": dict(checks),
            "created_at": self.clock(),
            "daemon": {"version_sha256": self.version_sha256},
        }
        key = load_signing_key(self.paths.signing_key_path)
        full = sign_receipt(core, key)
        write_receipt(self.paths, full)
        return full

    # -- pipeline ----------------------------------------------------------

    def handle(
        self,
        request: Any,
        *,
        peer_uid: Optional[int],
        shopify: Any = None,
    ) -> dict:
        """Validate and (for apply mode) execute one request; never raises."""
        operation: Optional[str] = None
        request_id: Optional[str] = None
        try:
            return self._handle(request, peer_uid=peer_uid, shopify=shopify)
        except BoundaryRefusal as exc:
            self._log(
                event="request", peer_uid=peer_uid,
                request_id=request_id, operation=operation,
                outcome=OUTCOME_REFUSED, error_code=exc.code,
            )
            return self._response(
                False, OUTCOME_REFUSED, error_code=exc.code, detail=exc.detail)
        except Exception as exc:  # noqa: BLE001 - fail closed, no detail leak
            self._log(
                event="internal_error", peer_uid=peer_uid,
                request_id=request_id, operation=operation,
                error_code=ERR_INTERNAL_ERROR, error=type(exc).__name__,
            )
            return self._response(
                False, OUTCOME_REFUSED, error_code=ERR_INTERNAL_ERROR,
                detail="internal error; request refused")

    def _handle(self, request: Any, *, peer_uid: Optional[int], shopify: Any) -> dict:
        # -- step 1: peer uid ------------------------------------------------
        policy, policy_error = self.policy()
        allowed_uids = set(policy["allowed_uids"]) if policy else {501}
        allowed_uids.add(0)  # root admin
        if peer_uid is None or peer_uid not in allowed_uids:
            raise refusal(ERR_PEER_NOT_ALLOWED, "peer uid is not allowed")

        # -- step 2: schema --------------------------------------------------
        request, request_id = _validate_request_shape(request)
        operation = request["operation"]

        # -- step 3: disabled flag ------------------------------------------
        if self.disabled():
            raise refusal(ERR_BOUNDARY_DISABLED, "write boundary is disabled")

        if operation == OP_STATUS:
            return self._status_response(policy, policy_error)

        # -- step 4: operation known + allowed by policy ---------------------
        if policy is None:
            raise refusal(
                ERR_OPERATION_NOT_ALLOWED,
                f"operation not allowed: policy unavailable ({policy_error})")
        config = policy["operations"].get(operation)
        if operation in WRITE_OPERATIONS:
            if config is None:
                raise refusal(
                    ERR_OPERATION_NOT_ALLOWED, f"operation not enabled: {operation}")
        else:  # verify
            if config is None or config.get("enabled") is not True:
                raise refusal(ERR_OPERATION_NOT_ALLOWED, "verify is not enabled")

        target = _validate_target_for_operation(request)

        if operation == OP_VERIFY:
            return self._verify(request, shopify=shopify, target=target)

        # -- write path ------------------------------------------------------
        operations = validate_operations(request)
        request_sha256 = json_sha256(request)
        ledger = self.ledger()

        # -- step 5: replay / duplicate -------------------------------------
        existing = ledger.request_entry(request_id)
        if existing is not None:
            if existing.get("request_sha256") != request_sha256:
                raise refusal(
                    ERR_REPLAY_REJECTED,
                    "request_id was already used for a different request")
            if existing.get("state") == STATE_MUTATING:
                # The process died between intent persistence and outcome;
                # never replay the mutation blindly.
                reconciliation = self._reconciliation_response(
                    request, "mutation intent persisted but outcome unknown")
                ledger.store_request(
                    request_id, request_sha256, STATE_RECONCILIATION_REQUIRED,
                    reconciliation, intent=existing.get("intent"))
                return reconciliation
            self._log(
                event="request_replay", request_id=request_id,
                operation=operation, outcome=existing.get("state"),
            )
            return existing.get("response") or self._response(
                False, OUTCOME_REFUSED, error_code=ERR_REPLAY_REJECTED,
                detail="stored response is unavailable")
        raw_key = (request.get("evidence") or {}).get("idempotency_key")
        idempotency_fp = None
        if isinstance(raw_key, str) and SAFE_TOKEN_RE.fullmatch(raw_key):
            idempotency_fp = Ledger.idempotency_fingerprint(
                target, operation, raw_key)
            owner = ledger.idempotency_owner(idempotency_fp)
            if owner is not None and owner != request_id:
                raise refusal(
                    ERR_DUPLICATE_OPERATION,
                    "idempotency key was already used for this target/operation")

        # -- step 6: authorisation ------------------------------------------
        auth_ref, auth_digest = self._validate_authorisation_step(
            request, policy, ledger, target,
            source_sha256=(request.get("evidence") or {}).get("source_sha256"))

        # -- step 7: evidence + media asset file bindings --------------------
        evidence_ref = validate_evidence(
            request, policy, self.paths, self.corrections_or_none())
        if idempotency_fp is None:
            key = evidence_ref["idempotency_key"]
            if key is not None:
                idempotency_fp = Ledger.idempotency_fingerprint(
                    target, operation, key)
        media_bindings = None
        expected_alts = None
        if operation == OP_MEDIA_APPEND:
            media_bindings = bind_media_assets(request, policy)
            expected_alts = media_expected_alts(request, evidence_ref)

        # -- step 8: policy caps + budgets ----------------------------------
        checks = validate_operation_caps(request, policy, ledger, media_bindings)

        # -- step 9: fresh pre-write snapshot + CAS -------------------------
        self._require_shopify(shopify)
        try:
            before = shopify.read_product(
                target["product_id"], target.get("location_id"))
        except Exception as exc:  # noqa: BLE001 - read failures are refusals
            raise refusal(
                ERR_SHOPIFY_UNAVAILABLE,
                f"fresh Shopify read failed: {type(exc).__name__}") from exc
        assert_readback_target(request, before)
        cas_expectation(request, before)
        if operation == OP_MEDIA_APPEND:
            duplicate = duplicate_media_alts(before, expected_alts)
            if duplicate is not None:
                raise refusal(
                    ERR_POLICY_REFUSED,
                    "an identical media asset (alt/sha convention) already exists")
        if self.disabled():  # re-check immediately before any mutation
            raise refusal(ERR_BOUNDARY_DISABLED, "write boundary is disabled")

        checks = {**checks, "baseline": "PASS", "authorisation": auth_ref["kind"]}

        if request["mode"] == "dry_run":
            receipt = self._sign_and_store_receipt(
                request, mode="dry_run", outcome=OUTCOME_DRY_RUN,
                evidence_ref=evidence_ref, auth_ref=auth_ref,
                before=before, after=before, checks=checks)
            response = self._response(
                True, OUTCOME_DRY_RUN, receipt=receipt,
                detail="dry run validated; no Shopify mutation performed")
            ledger.store_request(
                request_id, request_sha256, STATE_DRY_RUN, response)
            return response

        return self._apply(
            request, request_sha256=request_sha256, shopify=shopify,
            ledger=ledger, auth_ref=auth_ref, auth_digest=auth_digest,
            evidence_ref=evidence_ref, target=target, before=before,
            checks=checks, expected_alts=expected_alts,
            idempotency_fp=idempotency_fp,
        )

    # -- step 6 -------------------------------------------------------------

    def _validate_authorisation_step(
        self,
        request: dict,
        policy: dict,
        ledger: Ledger,
        target: dict,
        *,
        source_sha256: str,
    ) -> tuple[dict, Optional[str]]:
        operation = request["operation"]
        authorisation = request["authorisation"]
        fields = sorted(request_fields(request))
        if authorisation["kind"] == "standing":
            config = policy["operations"].get(operation) or {}
            if operation in STANDING_FORBIDDEN:
                raise refusal(
                    ERR_AUTHORISATION_INVALID,
                    "standing mode is forbidden for this operation")
            if config.get("standing") is not True:
                raise refusal(
                    ERR_AUTHORISATION_INVALID,
                    "policy does not enable standing mode for this operation")
            # Standing field-scope limits are enforced at step 8 (policy caps).
            return {"kind": "standing", "fields": fields}, None
        digest = authorisation["authorisation_sha256"]
        record = load_authorisation_record(self.paths, digest)
        if record is None:
            raise refusal(ERR_AUTHORISATION_INVALID, "authorisation record not found")
        owner = ledger.authorisation_owner(digest)
        if owner is not None:
            raise refusal(
                ERR_AUTHORISATION_INVALID,
                "authorisation record has already been consumed")
        ok, reason = validate_authorisation(
            record,
            operation=operation,
            required_fields=fields,
            target=target,
            source_sha256=source_sha256,
        )
        if not ok:
            raise refusal(ERR_AUTHORISATION_INVALID, f"authorisation rejected: {reason}")
        return {
            "kind": "owner",
            "authorisation_sha256": digest,
            "operator": record.get("operator"),
            "fields": sorted(record["fields"]),
        }, digest

    # -- step 8/10 apply ----------------------------------------------------

    def _require_shopify(self, shopify: Any) -> None:
        if shopify is None:
            raise refusal(ERR_SHOPIFY_UNAVAILABLE, "Shopify service is unavailable")

    def _mutation_intent(self, request: dict, evidence_ref: Mapping[str, Any],
                         target: Mapping[str, Any],
                         expected_alts: Optional[dict]) -> dict:
        operation = request["operation"]
        entry = request["operations"][0]
        intended: dict = {}
        if operation == OP_UPDATE_DETAILS:
            intended = {field: entry[field]
                        for field in OP_FIELDS[operation] if field in entry}
        elif operation == OP_SET_INVENTORY:
            intended = {"quantity": entry["quantity"]}
        elif operation == OP_MEDIA_APPEND:
            intended = {"alts": dict(expected_alts or {})}
        elif operation == OP_MERCH_UPDATE:
            intended = {field: entry[field]
                        for field in OP_FIELDS[operation] if field in entry}
        return {
            "operation": operation,
            "target": {key: target.get(key) for key in sorted(TARGET_KEYS)},
            "intended": intended,
            "idempotency_key": evidence_ref.get("idempotency_key"),
            "recorded_at": self.clock(),
        }

    def _apply(
        self,
        request: dict,
        *,
        request_sha256: str,
        shopify: Any,
        ledger: Ledger,
        auth_ref: dict,
        auth_digest: Optional[str],
        evidence_ref: dict,
        target: dict,
        before: dict,
        checks: dict,
        expected_alts: Optional[dict],
        idempotency_fp: Optional[str],
    ) -> dict:
        request_id = request["request_id"]
        operation = request["operation"]
        intent = self._mutation_intent(request, evidence_ref, target, expected_alts)
        # Persist the intent BEFORE any Shopify call, consume the authorisation
        # and the idempotency key, and count the write against the daily budget.
        ledger.store_request(
            request_id, request_sha256, STATE_MUTATING,
            self._response(
                False, OUTCOME_RECONCILIATION_REQUIRED,
                error_code=ERR_RECONCILIATION_REQUIRED,
                detail="mutation in progress"),
            intent=intent,
        )
        if auth_digest is not None:
            ledger.consume_authorisation(auth_digest, request_id)
        if idempotency_fp is not None:
            ledger.store_idempotency(idempotency_fp, request_id)
        ledger.bump_day()
        ledger.save()
        self._log(
            event="mutation_intent", request_id=request_id,
            operation=operation, target=target.get("product_id"),
        )
        try:
            result = self._execute_operation(request, shopify, evidence_ref)
        except ShopifyRejectedError as exc:
            response = self._response(
                False, OUTCOME_REFUSED,
                error_code=ERR_SHOPIFY_REJECTED,
                detail=f"Shopify rejected the mutation: {exc}")
            ledger.store_request(
                request_id, request_sha256, STATE_REFUSED, response, intent=intent)
            self._log(
                event="mutation_rejected", request_id=request_id,
                operation=operation, error_code=ERR_SHOPIFY_REJECTED,
            )
            return response
        except ShopifyUncertainError as exc:
            reconciliation = self._reconciliation_response(request, str(exc))
            ledger.store_request(
                request_id, request_sha256, STATE_RECONCILIATION_REQUIRED,
                reconciliation, intent=intent)
            self._log(
                event="mutation_uncertain", request_id=request_id,
                operation=operation, error_code=ERR_RECONCILIATION_REQUIRED,
            )
            return reconciliation
        except BoundaryRefusal:
            raise
        except Exception as exc:  # noqa: BLE001 - unknown outcomes are uncertain
            reconciliation = self._reconciliation_response(
                request, f"unexpected {type(exc).__name__} during mutation")
            ledger.store_request(
                request_id, request_sha256, STATE_RECONCILIATION_REQUIRED,
                reconciliation, intent=intent)
            return reconciliation

        # Fresh read-back + assertions.
        try:
            after = shopify.read_product(
                target["product_id"], target.get("location_id"))
        except Exception as exc:  # noqa: BLE001 - applied but unverified
            reconciliation = self._reconciliation_response(
                request, f"post-mutation read-back failed: {type(exc).__name__}")
            ledger.store_request(
                request_id, request_sha256, STATE_RECONCILIATION_REQUIRED,
                reconciliation, intent=intent)
            return reconciliation
        problems = self._assert_after(request, after, expected_alts)
        drift = protected_drift(before, after, self._allowed_change(operation))
        if problems or drift:
            reconciliation = self._reconciliation_response(
                request,
                "post-mutation read-back did not confirm the intended state")
            ledger.store_request(
                request_id, request_sha256, STATE_RECONCILIATION_REQUIRED,
                reconciliation, intent=intent)
            return reconciliation

        checks = {
            **checks,
            "readback": "PASS",
            "protected": "UNCHANGED",
            "after": "MATCHES_INTENT",
        }
        if result is not None:
            checks["shopify"] = result
        receipt = self._sign_and_store_receipt(
            request, mode="apply", outcome=OUTCOME_APPLIED,
            evidence_ref=evidence_ref, auth_ref=auth_ref,
            before=before, after=after, checks=checks)
        response = self._response(
            True, OUTCOME_APPLIED, receipt=receipt,
            detail="mutation applied and verified")
        ledger.store_request(
            request_id, request_sha256, STATE_APPLIED, response, intent=intent,
            receipt_path=str(receipt_path_for(self.paths, request_id)),
            receipt_sha256=receipt["receipt_sha256"],
        )
        self._log(
            event="mutation_applied", request_id=request_id,
            operation=operation, receipt_sha256=receipt["receipt_sha256"],
        )
        return response

    @staticmethod
    def _allowed_change(operation: str) -> tuple:
        if operation == OP_UPDATE_DETAILS:
            return ("title", "arrival_date")
        if operation == OP_SET_INVENTORY:
            return ("available", "inventory_quantity")
        if operation == OP_MEDIA_APPEND:
            return ("media",)
        if operation == OP_MERCH_UPDATE:
            return ("vendor", "price", "cost")
        return ()

    def _execute_operation(self, request: dict, shopify: Any, evidence_ref: dict) -> Any:
        operation = request["operation"]
        entry = request["operations"][0]
        target = request["target"]
        if operation == OP_UPDATE_DETAILS:
            fields = {field: entry[field]
                      for field in OP_FIELDS[operation] if field in entry}
            return shopify.apply_update_details(target["product_id"], fields)
        if operation == OP_SET_INVENTORY:
            key = evidence_ref["idempotency_key"]
            reference = (
                "gid://nta-betta/WriteBoundary/"
                f"{request['request_id']}/{key}")
            return shopify.apply_set_inventory(
                inventory_item_id=target["inventory_item_id"],
                location_id=target["location_id"],
                quantity=entry["quantity"],
                reason=entry["reason"],
                change_from=entry["expected"]["available"],
                reference_document_uri=reference,
                idempotency_key=key,
            )
        if operation == OP_MEDIA_APPEND:
            alts = media_expected_alts(request, evidence_ref)
            assets = []
            for asset in request["operations"][0]["assets"]:
                path = Path(asset["path"]).expanduser().resolve()
                assets.append({
                    "role": asset["role"],
                    "path": str(path),
                    "sha256": asset["sha256"],
                    "alt": alts[asset["role"]],
                })
            # Port semantics: hero first, then original.
            assets.sort(key=lambda value: 0 if value["role"] == "hero" else 1)
            config = self.policy()[0]["operations"][OP_MEDIA_APPEND]
            return shopify.apply_media_append(
                product_id=target["product_id"],
                assets=assets,
                batch_id=evidence_ref["batch_id"],
                tank=evidence_ref["identity"]["accepted_tank"],
                poll_attempts=int(config.get("poll_attempts", 30)),
                poll_interval=float(config.get("poll_interval", 2.0)),
            )
        if operation == OP_MERCH_UPDATE:
            fields = {field: entry[field]
                      for field in OP_FIELDS[operation] if field in entry}
            return shopify.apply_merch_update(
                product_id=target["product_id"],
                variant_id=target["variant_id"],
                inventory_item_id=target.get("inventory_item_id"),
                fields=fields,
            )
        raise refusal(ERR_OPERATION_NOT_ALLOWED, f"unknown operation: {operation}")

    def _assert_after(self, request: dict, after: Mapping[str, Any],
                      expected_alts: Optional[dict]) -> list:
        operation = request["operation"]
        entry = request["operations"][0]
        problems = []
        if operation == OP_UPDATE_DETAILS:
            for field in OP_FIELDS[operation]:
                if field in entry and after.get(field) != entry[field]:
                    problems.append(field)
        elif operation == OP_SET_INVENTORY:
            if after.get("available") != entry["quantity"]:
                problems.append("available")
        elif operation == OP_MEDIA_APPEND:
            media = after.get("media") or []
            wanted = [expected_alts["hero"], expected_alts["original"]]
            alts = [value.get("alt") for value in media[:2]]
            ids = [value.get("id") for value in media[:2]]
            statuses = [value.get("status") for value in media[:2]]
            if alts != wanted or len(set(ids)) != 2 or any(not value for value in ids):
                problems.append("media")
            elif any(status in ("FAILED", "CANCELED") for status in statuses):
                problems.append("media_status")
        elif operation == OP_MERCH_UPDATE:
            for field in OP_FIELDS[operation]:
                if field not in entry:
                    continue
                if field in ("price", "cost"):
                    if not numeric_equal(after.get(field), entry[field]):
                        problems.append(field)
                elif after.get(field) != entry[field]:
                    problems.append(field)
        return problems

    # -- reconciliation + verify -------------------------------------------

    def _reconciliation_response(self, request: dict, reason: str) -> dict:
        return self._response(
            False, OUTCOME_RECONCILIATION_REQUIRED,
            error_code=ERR_RECONCILIATION_REQUIRED,
            detail=(
                "mutation intent was persisted but the outcome is unresolved "
                f"({reason}); run verify for a fresh read-back to settle it; "
                "do not retry blindly"),
            readback={"reconciliation": {"request_id": request["request_id"],
                                         "operation": request["operation"]}},
        )

    @staticmethod
    def _intent_matches(intent: Mapping[str, Any], readback: Mapping[str, Any]) -> str:
        """Return 'applied', 'not_applied' or 'partial' for one intent."""
        operation = intent.get("operation")
        intended = intent.get("intended") or {}
        if operation == OP_UPDATE_DETAILS:
            for field, value in intended.items():
                if readback.get(field) != value:
                    return "not_applied"
            return "applied"
        if operation == OP_SET_INVENTORY:
            return ("applied" if readback.get("available") == intended.get("quantity")
                    else "not_applied")
        if operation == OP_MERCH_UPDATE:
            for field, value in intended.items():
                if field in ("price", "cost"):
                    if not numeric_equal(readback.get(field), value):
                        return "not_applied"
                elif readback.get(field) != value:
                    return "not_applied"
            return "applied"
        if operation == OP_MEDIA_APPEND:
            wanted = [intended.get("alts", {}).get("hero"),
                      intended.get("alts", {}).get("original")]
            alts = [value.get("alt") for value in (readback.get("media") or [])[:2]]
            matched = sum(1 for index in (0, 1)
                          if index < len(alts) and alts[index] == wanted[index])
            if matched == 2:
                return "applied"
            if matched == 0:
                return "not_applied"
            return "partial"
        return "not_applied"

    def _verify(self, request: dict, *, shopify: Any, target: dict) -> dict:
        ledger = self.ledger()
        request_sha256 = json_sha256(request)
        existing = ledger.request_entry(request["request_id"])
        if existing is not None:
            if existing.get("request_sha256") != request_sha256:
                raise refusal(
                    ERR_REPLAY_REJECTED,
                    "request_id was already used for a different request")
            if existing.get("state") in (STATE_MUTATING, STATE_RECONCILIATION_REQUIRED):
                pass  # fall through: verify is how reconciliation is settled
            else:
                return existing.get("response") or self._response(
                    False, OUTCOME_REFUSED, error_code=ERR_REPLAY_REJECTED,
                    detail="stored response is unavailable")
        self._require_shopify(shopify)
        try:
            readback = shopify.read_product(
                target["product_id"], target.get("location_id"))
        except Exception as exc:  # noqa: BLE001
            raise refusal(
                ERR_SHOPIFY_UNAVAILABLE,
                f"fresh Shopify read failed: {type(exc).__name__}") from exc
        assert_readback_target(request, readback)
        ledger = self.ledger()
        pending = ledger.reconcile_products(target["product_id"])
        settled = []
        for row in pending:
            verdict = self._intent_matches(
                {"operation": row["operation"], "intended": row["intended"]},
                readback)
            if verdict == "applied":
                ledger.set_request_state(row["request_id"], STATE_RECONCILED_APPLIED)
                settled.append({"request_id": row["request_id"],
                                "state": STATE_RECONCILED_APPLIED})
            elif verdict == "not_applied":
                ledger.set_request_state(row["request_id"], STATE_RECONCILED_NOT_APPLIED)
                settled.append({"request_id": row["request_id"],
                                "state": STATE_RECONCILED_NOT_APPLIED})
            else:
                settled.append({"request_id": row["request_id"], "state": "PARTIAL",
                                "note": "read-back is partially applied; not settled"})
        checks = {"readback": "PASS",
                  "reconciliations": [
                      {"request_id": row["request_id"], "state": value["state"]}
                      for row, value in zip(pending, settled)
                  ] if pending else []}
        receipt = self._sign_and_store_receipt(
            request, mode=request["mode"], outcome=OUTCOME_VERIFIED,
            evidence_ref={}, auth_ref={"kind": "none"},
            before=readback, after=readback, checks=checks)
        response = self._response(
            True, OUTCOME_VERIFIED, receipt=receipt,
            readback={
                "product": snapshot_readback(readback),
                "reconciliations": settled,
            },
            detail="fresh read-back completed")
        ledger.store_request(
            request["request_id"], request_sha256, STATE_VERIFIED, response,
            receipt_path=str(receipt_path_for(self.paths, request["request_id"])),
            receipt_sha256=receipt["receipt_sha256"])
        self._log(
            event="verify", request_id=request["request_id"],
            operation=OP_VERIFY, settled=len(settled),
        )
        return response

    # -- status --------------------------------------------------------------

    def _status_response(self, policy: Optional[dict],
                         policy_error: Optional[str]) -> dict:
        ledger = None
        writes_today = None
        pending = None
        try:
            ledger = self.ledger()
            writes_today = ledger.writes_today()
            pending = sum(
                1 for entry in ledger.data["requests"].values()
                if isinstance(entry, dict) and entry.get("state") in
                (STATE_RECONCILIATION_REQUIRED, STATE_MUTATING))
        except BoundaryRefusal:
            ledger = None
        operations = {}
        if policy is not None:
            for name in OPERATIONS:
                config = policy["operations"].get(name) or {}
                operations[name] = {
                    "enabled": config.get("enabled", True),
                    "standing": bool(config.get("standing", False)),
                }
        response = self._response(
            True, OUTCOME_STATUS,
            readback={
                "daemon_version_sha256": self.version_sha256,
                "disabled": self.disabled(),
                "policy_loaded": policy is not None,
                "policy_error": policy_error,
                "allowed_uids": (policy or {}).get("allowed_uids"),
                "operations": operations,
                "budgets": (policy or {}).get("budgets"),
                "writes_today": writes_today,
                "pending_reconciliations": pending,
            },
            detail="write boundary status",
        )
        return response


# ---------------------------------------------------------------------------
# Shopify service errors (shared contract with the daemon HTTP layer)
# ---------------------------------------------------------------------------


class ShopifyRejectedError(RuntimeError):
    """Shopify deterministically rejected the mutation (it was not applied)."""


class ShopifyUncertainError(RuntimeError):
    """The mutation outcome is unknown; reconciliation is required."""


class ShopifyReadError(RuntimeError):
    """A read-only Shopify call failed."""


class ShopifyUnavailableError(RuntimeError):
    """Shopify credentials/service are unavailable."""


# ---------------------------------------------------------------------------
# Module entry point (diagnostics only; the daemon is the real server)
# ---------------------------------------------------------------------------


def _main(argv: Optional[list] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="NTA Betta trusted write boundary core")
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--policy-check", action="store_true")
    parser.add_argument("--verify-receipt", type=Path)
    args = parser.parse_args(argv)
    paths = BoundaryPaths(args.state_dir)
    if args.verify_receipt is not None:
        try:
            key = load_signing_key(paths.signing_key_path, create=False)
        except SigningKeyError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}))
            return 2
        full = read_json(args.verify_receipt)
        ok, reason = verify_receipt_object(full, key)
        print(json.dumps({"ok": ok, "reason": reason}, indent=2))
        return 0 if ok else 2
    if args.policy_check:
        policy, error = load_policy(paths.policy_path)
        print(json.dumps({
            "ok": policy is not None,
            "error": error,
            "operations": sorted((policy or {}).get("operations", {})),
        }, indent=2))
        return 0 if policy is not None else 2
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
