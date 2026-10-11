#!/usr/bin/env python3
"""Standing Shopify/automation authorisation policy for Betta V2.2.

The policy is disabled by default. Manual, digest-only grants remain available
for backwards compatibility. Routine BAU batches use ``authorise_manifest``:
it validates the exact persisted manifest and all of its hash-bound evidence
through the production uploader before writing one deterministic, immutable
receipt for those bytes.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import importlib.util
import json
import math
import os
import stat
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from zoneinfo import ZoneInfo

SYDNEY = ZoneInfo("Australia/Sydney")
SCHEMA = "nta-betta-automation-policy-v1"
RECEIPT_SCHEMA = "nta-betta-automatic-authorisation-receipt-v1"

DEFAULT_PROTECTED_FIELDS = [
    "description", "retail_price", "cost", "vendor", "product_type",
    "handle", "status", "product_id", "variant_id", "inventory_item_id",
]
DEFAULT_PATH = Path.home() / "Documents" / "Betta Processing" / "automation-policy.json"

HARD_BUDGET_CAPS = {
    "per_fish_usd": 0.14,
    "per_batch_usd": 2.80,
    "max_attempts_per_fish": 2,
    "max_retries_per_fish": 1,
    "max_fish_per_batch": 20,
    "fallback_cost_usd": 0.07,
}


class PolicyError(ValueError):
    """The standing policy or requested automatic authorisation is unsafe."""


def now_sydney() -> str:
    return datetime.now(SYDNEY).isoformat()


def _json_bytes(data: Any) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(_json_bytes(data))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        _fsync_directory(path.parent)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _write_receipt_exclusive(path: Path, expected: bytes) -> None:
    """Create one exact receipt atomically, or verify the existing exact bytes."""
    # Keep the final path unresolved so an existing symlink cannot masquerade as
    # the immutable receipt itself.
    path = path.expanduser().absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(expected)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o444)
        try:
            os.link(temporary, path)
            _fsync_directory(path.parent)
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass

    try:
        metadata = path.lstat()
        actual = path.read_bytes()
    except OSError as exc:
        raise PolicyError(f"authorisation receipt is unavailable: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise PolicyError("authorisation receipt must be a regular file")
    if actual != expected:
        raise PolicyError("existing authorisation receipt differs from expected immutable bytes")


def default_policy() -> dict:
    return {
        "schema": SCHEMA,
        "version": 1,
        "enabled": False,
        "automatic_batch_authorisation": False,
        "paid_generation_authorised": False,
        "allow_product_create": False,
        "protected_fields": list(DEFAULT_PROTECTED_FIELDS),
        "inventory": {
            "allow_zero_to_one": True,
            "require_deny": True,
            "require_tracked": True,
            "allowed_from": [0],
            "target": 1,
        },
        "generation_budget": dict(HARD_BUDGET_CAPS),
        "authorisations": [],
    }


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PolicyError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise PolicyError(f"{label} must be finite and positive")
    return result


def _validate_policy(data: dict) -> None:
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise PolicyError("unsupported policy schema")
    if type(data.get("version")) is not int or data["version"] != 1:
        raise PolicyError("unsupported policy version")
    for field in (
        "enabled", "automatic_batch_authorisation", "paid_generation_authorised",
        "allow_product_create",
    ):
        if not isinstance(data.get(field), bool):
            raise PolicyError(f"policy {field} must be boolean")
    if data["allow_product_create"] is not False:
        raise PolicyError("product creation is outside the standing scope")

    protected = data.get("protected_fields")
    if (not isinstance(protected, list) or
            any(not isinstance(value, str) or not value for value in protected) or
            not set(DEFAULT_PROTECTED_FIELDS).issubset(set(protected))):
        raise PolicyError("protected_fields cannot relax the mandatory protected set")

    inventory = data.get("inventory")
    if not isinstance(inventory, dict):
        raise PolicyError("inventory policy must be an object")
    if (inventory.get("allow_zero_to_one") is not True or
            inventory.get("require_deny") is not True or
            inventory.get("require_tracked") is not True or
            type(inventory.get("target")) is not int or inventory["target"] != 1 or
            not isinstance(inventory.get("allowed_from"), list) or
            len(inventory["allowed_from"]) != 1 or
            type(inventory["allowed_from"][0]) is not int or
            inventory["allowed_from"][0] != 0):
        raise PolicyError("inventory authority must remain exactly tracked DENY 0-to-1")

    budget = data.get("generation_budget")
    if not isinstance(budget, dict):
        raise PolicyError("generation_budget must be an object")
    for key, cap in HARD_BUDGET_CAPS.items():
        value = _finite_number(budget.get(key), f"generation_budget.{key}")
        if key in {"max_attempts_per_fish", "max_retries_per_fish", "max_fish_per_batch"}:
            if not isinstance(budget.get(key), int):
                raise PolicyError(f"generation_budget.{key} must be an integer")
        if key == "fallback_cost_usd":
            if value != cap:
                raise PolicyError("generation_budget.fallback_cost_usd must remain 0.07")
        elif value > cap:
            raise PolicyError(f"generation_budget.{key} exceeds the approved hard cap")
    if budget["max_retries_per_fish"] > budget["max_attempts_per_fish"] - 1:
        raise PolicyError("generation retries exceed the attempt ceiling")
    if not isinstance(data.get("authorisations"), list):
        raise PolicyError("authorisations must be a list")


_UPLOADER: ModuleType | None = None


def _uploader() -> ModuleType:
    """Load the actual sibling uploader without requiring a package install."""
    global _UPLOADER
    if _UPLOADER is not None:
        return _UPLOADER
    path = Path(__file__).with_name("betta_shopify_batch.py")
    name = "_nta_betta_shopify_batch_policy_validation"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PolicyError(f"cannot load uploader: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    _UPLOADER = module
    return module


def _load_manifest(path: Path, *, require_authority: bool, expected_sha256: str | None):
    """Validate exact bytes using the uploader's schema and evidence loader."""
    manifest_path = Path(path).expanduser().resolve()
    try:
        before = manifest_path.read_bytes()
    except OSError as exc:
        raise PolicyError(f"manifest is unavailable: {manifest_path}") from exc
    digest = hashlib.sha256(before).hexdigest()
    if expected_sha256 is not None and expected_sha256 != digest:
        raise PolicyError("expected manifest SHA-256 does not match persisted bytes")

    uploader = _uploader()
    try:
        bundle = uploader.ManifestBundle(manifest_path)
        contexts = bundle.select()
        if require_authority:
            uploader.require_live_authority(bundle, contexts, digest)
    except Exception as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise PolicyError(f"uploader rejected manifest: {exc}") from exc

    try:
        after = manifest_path.read_bytes()
    except OSError as exc:
        raise PolicyError("manifest disappeared during validation") from exc
    if after != before or bundle.sha256 != digest:
        raise PolicyError("manifest bytes changed during validation")
    return bundle, contexts, digest, before


class StandingPolicy:
    """Loads and evaluates the standing policy. Fails closed on any doubt."""

    def __init__(self, data: dict | None = None):
        self.data = default_policy() if data is None else data
        _validate_policy(self.data)

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> "StandingPolicy":
        path = Path(path)
        result = cls(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else cls(default_policy())
        result.source_path = path
        return result

    def enabled(self) -> bool:
        _validate_policy(self.data)
        return self.data.get("enabled") is True

    def paid_generation_authorised(self) -> bool:
        _validate_policy(self.data)
        return self.enabled() and self.data.get("paid_generation_authorised") is True

    def allows_product_create(self) -> bool:
        _validate_policy(self.data)
        return self.data.get("allow_product_create") is True

    def inventory_rule(self) -> dict:
        _validate_policy(self.data)
        return dict(self.data.get("inventory") or {})

    def generation_budget(self) -> dict:
        _validate_policy(self.data)
        return dict(self.data.get("generation_budget") or {})

    def authorise(self, manifest_sha256: str | None) -> dict | None:
        """Return a legacy manual grant for an exact digest, or ``None``."""
        _validate_policy(self.data)
        if not self.enabled() or not manifest_sha256:
            return None
        for entry in self.data.get("authorisations", []):
            if isinstance(entry, dict) and entry.get("manifest_sha256") == manifest_sha256:
                return {
                    "manifest_sha256": manifest_sha256,
                    "policy_version": self.data.get("version"),
                    "receipt": entry.get("receipt"),
                    "authorised_at": entry.get("at"),
                }
        return None

    def authorise_manifest(
        self,
        manifest_path: Path,
        receipt_path: Path,
        expected_sha256: str | None = None,
    ) -> dict:
        """Validate and persist an automatic BAU receipt for exact manifest bytes."""
        _validate_policy(self.data)
        if not self.enabled():
            raise PolicyError("standing policy is disabled")
        if self.data.get("automatic_batch_authorisation") is not True:
            raise PolicyError("automatic batch authorisation is disabled")

        bundle, contexts, digest, original_bytes = _load_manifest(
            Path(manifest_path), require_authority=True, expected_sha256=expected_sha256,
        )
        if len(contexts) > int(self.data["generation_budget"]["max_fish_per_batch"]):
            raise PolicyError("manifest exceeds the approved fish-per-batch limit")

        items = []
        for context in contexts:
            raw = context.raw
            if raw.get("quantity") != 1 or raw.get("inventory_reason") != "received":
                raise PolicyError(f"{context.tank_id}: standing scope permits received inventory target 1 only")
            if context.baseline.get("available") != 0:
                raise PolicyError(f"{context.tank_id}: standing scope permits inventory 0-to-1 only")
            if (context.protected.get("inventory_policy") != "DENY" or
                    context.protected.get("tracked") is not True):
                raise PolicyError(f"{context.tank_id}: inventory must be tracked with DENY policy")
            qa_output = context.qa.get("output") or {}
            assertions = qa_output.get("assertions") or {}
            exception = (raw.get("image_qa") or {}).get("exception")
            if (qa_output.get("overall") != "PASS" or not assertions or
                    any(value != "PASS" for value in assertions.values()) or
                    exception not in (None, {})):
                raise PolicyError(f"{context.tank_id}: automatic authority requires QA PASS without exception")
            items.append({
                "tank_id": context.tank_id,
                "product_id": context.product_id,
                "variant_id": context.variant_id,
                "inventory_item_id": context.inventory_item_id,
                "location_id": context.location_id,
                "inventory_from": 0,
                "inventory_to": 1,
                "qa_receipt_sha256": context.qa_sha256,
            })

        scope = {
            "allow_product_create": False,
            "protected_fields": sorted(set(self.data["protected_fields"])),
            "inventory": dict(self.data["inventory"]),
            "generation_budget": dict(self.data["generation_budget"]),
            "qa_exceptions_allowed": False,
        }
        core = {
            "schema": RECEIPT_SCHEMA,
            "authorisation_mode": "automatic-standing-bau",
            "policy_schema": SCHEMA,
            "policy_version": self.data["version"],
            "batch_id": bundle.batch_id,
            "manifest_sha256": digest,
            "item_count": len(items),
            "items": items,
            "scope": scope,
        }
        receipt = {
            **core,
            "receipt": "bau-" + hashlib.sha256(
                json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            ).hexdigest(),
        }
        expected_receipt = _json_bytes(receipt)

        # Re-read immediately before and after receipt persistence. A later
        # replacement has a different digest and cannot satisfy this receipt.
        if Path(manifest_path).expanduser().resolve().read_bytes() != original_bytes:
            raise PolicyError("manifest bytes changed before receipt persistence")
        _write_receipt_exclusive(Path(receipt_path), expected_receipt)
        if Path(manifest_path).expanduser().resolve().read_bytes() != original_bytes:
            raise PolicyError("manifest bytes changed while receipt was persisted")
        return receipt

    # Public US spelling for callers that do not use the repository's spelling.
    authorize_manifest = authorise_manifest


def grant(policy_path: Path, manifest_sha256: str, receipt: str) -> dict:
    """Record a legacy authorisation bound to a manifest hash (owner action)."""
    policy = StandingPolicy.load(policy_path)
    entry = {"manifest_sha256": manifest_sha256, "receipt": receipt, "at": now_sydney()}
    policy.data.setdefault("authorisations", [])
    policy.data["authorisations"] = [
        e for e in policy.data["authorisations"]
        if not isinstance(e, dict) or e.get("manifest_sha256") != manifest_sha256
    ] + [entry]
    _atomic_write(Path(policy_path), policy.data)
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description="Betta standing automation policy")
    parser.add_argument("--policy", type=Path, default=DEFAULT_PATH)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    sub.add_parser("init")
    p = sub.add_parser("grant")
    p.add_argument("manifest_sha256")
    p.add_argument("--receipt", required=True)
    p = sub.add_parser("set-enabled")
    p.add_argument("state", choices=("true", "false"))
    p = sub.add_parser("set-paid-generation")
    p.add_argument("state", choices=("true", "false"))
    p = sub.add_parser("set-automatic-authorisation")
    p.add_argument("state", choices=("true", "false"))
    args = parser.parse_args()
    try:
        if args.cmd == "init":
            _atomic_write(args.policy, default_policy())
        elif args.cmd == "show":
            policy = StandingPolicy.load(args.policy)
            print(json.dumps(policy.data, indent=2, sort_keys=True))
        elif args.cmd == "grant":
            print(json.dumps(grant(args.policy, args.manifest_sha256, args.receipt), sort_keys=True))
        elif args.cmd in {"set-enabled", "set-paid-generation", "set-automatic-authorisation"}:
            policy = StandingPolicy.load(args.policy)
            field = {
                "set-enabled": "enabled",
                "set-paid-generation": "paid_generation_authorised",
                "set-automatic-authorisation": "automatic_batch_authorisation",
            }[args.cmd]
            policy.data[field] = args.state == "true"
            _validate_policy(policy.data)
            _atomic_write(args.policy, policy.data)
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
