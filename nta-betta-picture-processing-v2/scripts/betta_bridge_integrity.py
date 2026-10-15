#!/usr/bin/env python3
"""Bridge-integrity pinning for NTA/Fred Shopify session bridges.

The P1 incident (2026-10-15) proved that a Shopify session bridge is only as
safe as the file it runs from: Fred mutated product 5BT43 through a *copied*
bridge living in an agent-writable temp workspace, whose write allowlist
(merch targets and values) was defined in the same file the agent could edit.

This tool pins the canonical bridge file by absolute path and SHA-256 in
``references/bridge-integrity.json`` and checks any configured bridge path:

- the configured path must resolve to the pinned canonical file, and
- the bytes must match the pinned SHA-256 exactly.

Any workspace copy is therefore detectable even if it is byte-identical today.
This is a detection tool; deployment/wiring into write paths is owner-gated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "nta-betta-bridge-integrity-v1"
DEFAULT_INDEX = Path(__file__).resolve().parents[1] / "references" / "bridge-integrity.json"


class BridgeIntegrityError(ValueError):
    """The integrity index itself is missing or malformed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_index(index_path: Path | str | None = None) -> dict[str, Any]:
    """Load and validate the bridge-integrity index."""
    path = Path(index_path).expanduser() if index_path else DEFAULT_INDEX
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BridgeIntegrityError(f"bridge integrity index unavailable: {path}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BridgeIntegrityError(
            f"bridge integrity index is not valid JSON: {path}"
        ) from exc
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise BridgeIntegrityError("unsupported bridge integrity index schema")
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        raise BridgeIntegrityError("bridge integrity index has no entries")
    for entry in entries:
        if not isinstance(entry, dict):
            raise BridgeIntegrityError("bridge integrity entry must be an object")
        for key in ("name", "role", "path", "sha256"):
            if not isinstance(entry.get(key), str) or not entry[key]:
                raise BridgeIntegrityError(f"bridge integrity entry missing {key}")
        digest = entry["sha256"]
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise BridgeIntegrityError("bridge integrity entry sha256 is invalid")
    roles = [entry["role"] for entry in entries]
    if roles.count("canonical") != 1:
        raise BridgeIntegrityError("bridge integrity index must pin exactly one canonical bridge")
    return data


def canonical_entry(index: Mapping[str, Any]) -> Mapping[str, Any]:
    for entry in index.get("entries", []):
        if isinstance(entry, Mapping) and entry.get("role") == "canonical":
            return entry
    raise BridgeIntegrityError("bridge integrity index has no canonical entry")


def _result(
    ok: bool, reason: str, expected: str | None, actual: str | None,
) -> dict[str, Any]:
    return {
        "ok": bool(ok),
        "reason": reason,
        "expected_sha256": expected,
        "actual_sha256": actual,
    }


def check_bridge(
    bridge_path: Path | str, *, index_path: Path | str | None = None,
) -> dict[str, Any]:
    """Check one configured bridge path against the pinned index.

    Reasons: ``verified`` / ``bridge_not_canonical`` / ``bridge_missing`` /
    ``bridge_hash_mismatch`` / ``integrity_index_missing`` /
    ``integrity_index_invalid``.
    """
    try:
        index = load_index(index_path)
    except BridgeIntegrityError as exc:
        reason = (
            "integrity_index_missing"
            if "unavailable" in str(exc) else "integrity_index_invalid"
        )
        actual = None
        try:
            candidate = Path(bridge_path).expanduser()
            if candidate.is_file():
                actual = sha256_file(candidate)
        except OSError:
            actual = None
        return _result(False, reason, None, actual)

    entry = canonical_entry(index)
    expected = entry["sha256"]
    configured = Path(bridge_path).expanduser()
    canonical = Path(entry["path"]).expanduser().resolve()
    if configured.resolve() != canonical:
        actual = sha256_file(configured) if configured.is_file() else None
        return _result(False, "bridge_not_canonical", expected, actual)
    if not configured.is_file():
        return _result(False, "bridge_missing", expected, None)
    actual = sha256_file(configured)
    if actual != expected:
        return _result(False, "bridge_hash_mismatch", expected, actual)
    return _result(True, "verified", expected, actual)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pin and verify Shopify session-bridge integrity"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="check one configured bridge path")
    check.add_argument("--bridge", required=True, type=Path)
    check.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    args = parser.parse_args(argv)
    if args.command == "check":
        result = check_bridge(args.bridge, index_path=args.index)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["ok"] else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
