#!/usr/bin/env python3
"""Standing Shopify/automation authorisation policy for Betta V2.2.

One narrowly scoped policy replaces per-batch, per-fish approvals. It is DISABLED
by default and every authorisation is bound to the exact immutable manifest
SHA-256, so approving a manifest never authorises different bytes.

The policy grants only what the standing approval permits (title, arrival date,
hero+original media, guarded inventory). It never widens the orchestrator's
authority and never stores secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SYDNEY = ZoneInfo("Australia/Sydney")
SCHEMA = "nta-betta-automation-policy-v1"

DEFAULT_PROTECTED_FIELDS = [
    "description", "retail_price", "cost", "vendor", "product_type",
    "handle", "status", "product_id", "variant_id", "inventory_item_id",
]
DEFAULT_PATH = Path.home() / "Documents" / "Betta Processing" / "automation-policy.json"


def now_sydney() -> str:
    return datetime.now(SYDNEY).isoformat()


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def default_policy() -> dict:
    return {
        "schema": SCHEMA,
        "version": 1,
        "enabled": False,
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
        "authorisations": [],
    }


class StandingPolicy:
    """Loads and evaluates the standing policy. Fails closed on any doubt."""

    def __init__(self, data: dict | None = None):
        self.data = data or default_policy()
        if self.data.get("schema") != SCHEMA:
            raise ValueError("unsupported policy schema")

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> "StandingPolicy":
        path = Path(path)
        if not path.is_file():
            return cls(default_policy())  # absent policy == disabled
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def enabled(self) -> bool:
        return self.data.get("enabled") is True

    def paid_generation_authorised(self) -> bool:
        return self.enabled() and self.data.get("paid_generation_authorised") is True

    def allows_product_create(self) -> bool:
        return self.data.get("allow_product_create") is True

    def inventory_rule(self) -> dict:
        return dict(self.data.get("inventory") or {})

    def authorise(self, manifest_sha256: str | None) -> dict | None:
        """Return the authorisation receipt bound to this exact manifest, or None."""
        if not self.enabled() or not manifest_sha256:
            return None
        for entry in self.data.get("authorisations", []):
            if entry.get("manifest_sha256") == manifest_sha256:
                return {
                    "manifest_sha256": manifest_sha256,
                    "policy_version": self.data.get("version"),
                    "receipt": entry.get("receipt"),
                    "authorised_at": entry.get("at"),
                }
        return None


def grant(policy_path: Path, manifest_sha256: str, receipt: str) -> dict:
    """Record a standing authorisation bound to a manifest hash (owner action)."""
    policy = StandingPolicy.load(policy_path)
    entry = {"manifest_sha256": manifest_sha256, "receipt": receipt, "at": now_sydney()}
    policy.data.setdefault("authorisations", [])
    policy.data["authorisations"] = [
        e for e in policy.data["authorisations"] if e.get("manifest_sha256") != manifest_sha256
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
    args = parser.parse_args()
    try:
        if args.cmd == "init":
            _atomic_write(args.policy, default_policy())
        elif args.cmd == "show":
            policy = StandingPolicy.load(args.policy)
            print(json.dumps(policy.data, indent=2, sort_keys=True))
        elif args.cmd == "grant":
            print(json.dumps(grant(args.policy, args.manifest_sha256, args.receipt), sort_keys=True))
        elif args.cmd == "set-enabled":
            policy = StandingPolicy.load(args.policy)
            policy.data["enabled"] = args.state == "true"
            _atomic_write(args.policy, policy.data)
        elif args.cmd == "set-paid-generation":
            policy = StandingPolicy.load(args.policy)
            policy.data["paid_generation_authorised"] = args.state == "true"
            _atomic_write(args.policy, policy.data)
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
