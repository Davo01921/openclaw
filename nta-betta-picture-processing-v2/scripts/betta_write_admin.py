#!/usr/bin/env python3
"""Admin CLI for the NTA Betta trusted write boundary (root-only).

Production wrapper: ``/usr/local/bin/nta-betta-write`` (installed by R2) runs
this file with Apple's ``/usr/bin/python3``. Commands:

- ``status``           inspect the boundary state (no secrets, ever)
- ``authorise``        write ONE immutable, single-use owner authorisation
                       record; REFUSES to run as a non-root user
- ``disable``          create the fail-closed disabled flag
- ``enable``           remove the disabled flag
- ``verify-receipt``   re-verify the HMAC signature of a stored receipt

This tool deliberately does not accept policy from anywhere but the root-owned
``--state-dir``; environment variables never widen authority.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

ADMIN_SCHEMA = "nta-betta-write-admin-result-v1"


def load_boundary(code_root: Path) -> Any:
    path = Path(code_root) / "betta_write_boundary.py"
    spec = importlib.util.spec_from_file_location(
        "_nta_betta_write_boundary_admin", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"boundary module unavailable: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _result(ok: bool, **fields: Any) -> dict:
    return {"schema": ADMIN_SCHEMA, "ok": bool(ok), **fields}


def _split_fields(value: str) -> list:
    fields = [part.strip() for part in value.split(",")]
    fields = [field for field in fields if field]
    if not fields:
        raise argparse.ArgumentTypeError("at least one field is required")
    return fields


def command_status(boundary: Any, paths: Any) -> dict:
    policy, policy_error = boundary.load_policy(paths.policy_path)
    counters = {}
    authorisations = 0
    receipts = 0
    pending_reconciliations = 0
    ledger_error = None
    try:
        ledger = boundary.Ledger(paths.ledger_path)
        counters = dict(ledger.data.get("day_counters", {}))
        pending_reconciliations = sum(
            1 for entry in ledger.data.get("requests", {}).values()
            if isinstance(entry, dict) and entry.get("state") in
            (boundary.STATE_RECONCILIATION_REQUIRED, boundary.STATE_MUTATING))
    except boundary.BoundaryRefusal as exc:
        ledger_error = exc.code
    try:
        authorisations = len(list(paths.authorisations_dir.glob("authorisation-*.json")))
    except OSError:
        authorisations = 0
    try:
        receipts = len(list(paths.receipts_dir.glob("receipt-*.json")))
    except OSError:
        receipts = 0
    operations = {}
    if policy is not None:
        for name, config in policy["operations"].items():
            operations[name] = {
                "enabled": config.get("enabled", True),
                "standing": bool(config.get("standing", False)),
            }
    return _result(
        True,
        disabled=os.path.exists(paths.disabled_path),
        policy_loaded=policy is not None,
        policy_error=policy_error,
        allowed_uids=(policy or {}).get("allowed_uids"),
        allowed_roots=(policy or {}).get("allowed_roots"),
        operations=operations,
        budgets=(policy or {}).get("budgets"),
        day_counters=counters,
        pending_reconciliations=pending_reconciliations,
        authorisations=authorisations,
        receipts=receipts,
        ledger_error=ledger_error,
        signing_key_present=os.path.exists(paths.signing_key_path),
        shopify_env_present=os.path.exists(paths.shopify_env_path),
    )


def command_authorise(boundary: Any, paths: Any, args: argparse.Namespace) -> dict:
    if os.geteuid() != 0:
        return _result(
            False,
            error="authorise must run as root (owner authorisation records "
                  "are root-owned)")
    try:
        path = boundary.write_authorisation_record(
            paths,
            source_sha256=args.source_sha,
            tank=args.tank,
            product_id=args.product,
            variant_id=args.variant,
            fields=args.fields,
            reason=args.reason,
            operator=args.operator,
            expires_in_hours=args.expires_in_hours,
        )
    except boundary.AuthorisationError as exc:
        return _result(False, error=str(exc))
    record = boundary.read_json(path)
    return _result(
        True,
        path=str(path),
        authorisation_sha256=record["authorisation_sha256"],
        fields=record["fields"],
        operation_class=record["operation_class"],
        expires_at=record["expires_at"],
    )


def command_disable(boundary: Any, paths: Any, operator: Optional[str]) -> dict:
    paths.ensure_dirs()
    if os.path.exists(paths.disabled_path):
        return _result(True, disabled=True, detail="already disabled")
    boundary.atomic_write_json(
        paths.disabled_path,
        {"schema": boundary.DISABLED_MARKER_SCHEMA,
         "disabled_at": boundary.utc_now(), "by": operator or "unknown"},
        0o600,
    )
    return _result(True, disabled=True)


def command_enable(boundary: Any, paths: Any) -> dict:
    try:
        os.unlink(paths.disabled_path)
    except FileNotFoundError:
        return _result(True, disabled=False, detail="already enabled")
    except OSError as exc:
        return _result(False, error=f"cannot remove disabled flag: {exc}")
    return _result(True, disabled=False)


def command_verify_receipt(boundary: Any, paths: Any, receipt_file: Path) -> dict:
    try:
        key = boundary.load_signing_key(paths.signing_key_path, create=False)
    except boundary.SigningKeyError as exc:
        return _result(False, error=str(exc))
    try:
        full = boundary.read_json(Path(receipt_file).expanduser())
    except (OSError, json.JSONDecodeError) as exc:
        return _result(False, error=f"receipt is unreadable: {type(exc).__name__}")
    ok, reason = boundary.verify_receipt_object(full, key)
    return _result(
        ok, reason=reason,
        receipt_sha256=full.get("receipt_sha256") if isinstance(full, dict) else None,
        request_id=full.get("request_id") if isinstance(full, dict) else None,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="NTA Betta trusted write-boundary admin (root-only)")
    parser.add_argument(
        "--state-dir", required=True, type=Path,
        help="root-owned boundary state directory")
    parser.add_argument(
        "--code-root", type=Path, default=None,
        help="directory containing betta_write_boundary.py (default: sibling)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="inspect boundary state")

    authorise = sub.add_parser("authorise", help="write an owner authorisation record")
    authorise.add_argument("--source-sha", required=True)
    authorise.add_argument("--tank", required=True)
    authorise.add_argument("--product", required=True)
    authorise.add_argument("--variant", default=None)
    authorise.add_argument("--fields", required=True, type=_split_fields,
                           help="comma-separated authorisation field scope")
    authorise.add_argument("--reason", required=True)
    authorise.add_argument("--operator", required=True)
    authorise.add_argument("--expires-in-hours", type=float, default=24.0)

    disable = sub.add_parser("disable", help="disable the write boundary (fail closed)")
    disable.add_argument("--operator", default=None)

    sub.add_parser("enable", help="re-enable the write boundary")

    verify = sub.add_parser("verify-receipt", help="verify a stored receipt signature")
    verify.add_argument("--file", required=True, type=Path)

    return parser


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    code_root = Path(args.code_root) if args.code_root else Path(__file__).resolve().parent
    try:
        boundary = load_boundary(code_root)
    except (OSError, RuntimeError) as exc:
        print(json.dumps(_result(False, error=str(exc)), indent=2, sort_keys=True))
        return 2
    paths = boundary.BoundaryPaths(args.state_dir)
    if args.command == "authorise":
        # Fail before touching anything when running unprivileged.
        result = command_authorise(boundary, paths, args)
    elif args.command == "status":
        result = command_status(boundary, paths)
    elif args.command == "disable":
        result = command_disable(boundary, paths, args.operator)
    elif args.command == "enable":
        result = command_enable(boundary, paths)
    elif args.command == "verify-receipt":
        result = command_verify_receipt(boundary, paths, args.file)
    else:  # pragma: no cover - argparse enforces the set
        result = _result(False, error=f"unknown command: {args.command}")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
