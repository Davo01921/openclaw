#!/usr/bin/env python3
"""Immutable owner-correction records for the NTA Betta identity firewall.

A correction record is a small immutable JSON document (schema
``nta-betta-owner-correction-v1``) that binds, exactly:

- the raw camera original (``source_sha256``),
- the vision model's original (wrong) tank reading (``original_model_tank``),
- the owner's corrected tank (``corrected_tank``),
- the exact Shopify product (and optionally variant),
- the operation scope (which fields the correction authorises),
- reason, evidence reference, operator and creation time.

The uploader refuses to mutate an item whose vision-detected identity differs
from the requested identity unless a hash-verified correction record binding
exactly that source, target tank, product and operation scope is presented.
Records are written once, with O_EXCL, mode 0444, and are never overwritten.
Reuse of one record for a different source hash, tank, product or operation
field set fails validation.

``validate_correction`` never raises for record-content problems; it returns
``{"valid": bool, "reason": str}`` with a stable machine-readable reason:

- ``record_unavailable`` / ``record_invalid_json`` / ``record_not_object``
- ``schema_mismatch`` / ``schema_fields_mismatch``
- ``invalid_field:<name>`` (field format)
- ``self_hash_missing_or_invalid`` / ``self_hash_mismatch``
- ``no_op_correction`` (``original_model_tank`` equals ``corrected_tank``)
- ``invalid_operation_scope``
- ``source_sha256_mismatch``
- ``corrected_tank_mismatch`` (record target != accepted tank)
- ``requested_tank_mismatch`` (owner request != record target)
- ``product_id_mismatch``
- ``variant_id_mismatch`` (when the caller binds a variant)
- ``operation_scope_mismatch`` (requested fields not covered)
- ``invalid_requested_operation_fields``
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA = "nta-betta-owner-correction-v1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
TANK_RE = re.compile(r"^(?:[1-9]\d*BT[1-9]\d*|APE\d+)$")
PRODUCT_RE = re.compile(r"^(?:gid://shopify/Product/[1-9]\d*|[1-9]\d*)$")
FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
MODE_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")

RECORD_KEYS = frozenset({
    "schema", "source_sha256", "original_model_tank", "corrected_tank",
    "product_id", "variant_id", "operation", "reason", "evidence_reference",
    "operator", "created_at", "correction_sha256",
})


class CorrectionError(ValueError):
    """The requested correction record is malformed or already recorded."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_directory() -> Path:
    """Default corrections directory: ``<repo>/references/corrections/``."""
    return Path(__file__).resolve().parents[1] / "references" / "corrections"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def record_path_for(correction_sha256: str, directory: Path | str | None = None) -> Path:
    """Return the deterministic on-disk path for a correction digest."""
    if not isinstance(correction_sha256, str) or SHA_RE.fullmatch(correction_sha256) is None:
        raise CorrectionError("correction sha must be a lowercase SHA-256 hex string")
    base = Path(directory).expanduser() if directory else default_directory()
    return base.resolve() / f"correction-{correction_sha256}.json"


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _require_nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CorrectionError(f"{label}: non-empty string required")
    return value


def _require_tank(value: Any, label: str) -> str:
    if not isinstance(value, str) or TANK_RE.fullmatch(value) is None:
        raise CorrectionError(f"{label}: canonical tank ID required")
    return value


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise CorrectionError(f"{label}: lowercase SHA-256 required")
    return value


def _require_product(value: Any, label: str) -> str:
    if not isinstance(value, str) or PRODUCT_RE.fullmatch(value) is None:
        raise CorrectionError(f"{label}: Shopify product GID or numeric ID required")
    return value


def _require_created_at(value: Any, label: str) -> str:
    text = _require_nonempty(value, label)
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CorrectionError(f"{label}: ISO-8601 timestamp required") from exc
    return text


def _normalise_operation(operation: Any) -> dict[str, Any]:
    """Accept ``["field", ...]`` or ``{"fields": [...], "mode": "..."}``."""
    mode = "owner-directed"
    if isinstance(operation, Mapping):
        unknown = set(operation) - {"fields", "mode"}
        if unknown:
            raise CorrectionError(
                "operation: unknown keys: " + ", ".join(sorted(unknown))
            )
        fields = operation.get("fields")
        if "mode" in operation:
            mode = operation.get("mode")
    elif isinstance(operation, (list, tuple)):
        fields = list(operation)
    else:
        raise CorrectionError("operation: list of fields or {fields, mode} required")
    if not isinstance(mode, str) or MODE_RE.fullmatch(mode) is None:
        raise CorrectionError("operation.mode: invalid mode")
    if (not isinstance(fields, (list, tuple)) or not fields or
            any(not isinstance(value, str) or FIELD_RE.fullmatch(value) is None
                for value in fields)):
        raise CorrectionError("operation.fields: non-empty list of field names required")
    return {"fields": sorted(set(fields)), "mode": mode}


def scope_fields(operation: Any) -> list[str]:
    """Extract the field list from a stored operation scope."""
    return list(_normalise_operation(operation)["fields"])


def load_record(path: Path | str) -> dict[str, Any]:
    """Read one correction record file; raises CorrectionError if unusable."""
    candidate = Path(path).expanduser()
    try:
        raw = candidate.read_text(encoding="utf-8")
    except OSError as exc:
        raise CorrectionError(f"correction record unavailable: {candidate}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CorrectionError(f"correction record is not valid JSON: {candidate}") from exc
    if not isinstance(data, dict):
        raise CorrectionError("correction record must be a JSON object")
    return data


def _validate_record_shape(data: Mapping[str, Any]) -> str | None:
    """Return a reason string when the record is malformed, else ``None``."""
    if data.get("schema") != SCHEMA:
        return "schema_mismatch"
    if set(data) != RECORD_KEYS:
        return "schema_fields_mismatch"
    digest = data.get("correction_sha256")
    if not isinstance(digest, str) or SHA_RE.fullmatch(digest) is None:
        return "self_hash_missing_or_invalid"
    core = {key: value for key, value in data.items() if key != "correction_sha256"}
    if json_sha256(core) != digest:
        return "self_hash_mismatch"
    for key, check in (
        ("source_sha256", _require_sha),
        ("original_model_tank", _require_tank),
        ("corrected_tank", _require_tank),
        ("product_id", _require_product),
        ("reason", _require_nonempty),
        ("evidence_reference", _require_nonempty),
        ("operator", _require_nonempty),
        ("created_at", _require_created_at),
    ):
        try:
            check(data.get(key), key)
        except CorrectionError:
            return f"invalid_field:{key}"
    if data["original_model_tank"] == data["corrected_tank"]:
        return "no_op_correction"
    variant = data.get("variant_id")
    if variant is not None and (not isinstance(variant, str) or not variant.strip()):
        return "invalid_field:variant_id"
    try:
        _normalise_operation(data.get("operation"))
    except CorrectionError:
        return "invalid_operation_scope"
    return None


def validate_correction(
    record_path_or_dict: Any,
    *,
    source_sha256: Any,
    requested_tank: Any,
    accepted_tank: Any,
    product_id: Any,
    variant_id: Any = None,
    operation_fields: Iterable[str] | None,
) -> dict[str, Any]:
    """Validate one correction record against an exact intended operation.

    The record is valid ONLY when it binds exactly: the same source SHA-256,
    ``corrected_tank == accepted_tank``, ``requested_tank == corrected_tank``
    (the owner target), the same product, and — when the caller binds one — the
    same ``variant_id``; the recorded operation scope must cover every requested
    operation field, and a no-op correction (``original_model_tank ==
    corrected_tank``) is never valid. Reuse for a different source, product,
    variant, tank or operation set fails.
    """
    if isinstance(record_path_or_dict, (str, Path)):
        path = Path(record_path_or_dict).expanduser()
        if not path.is_file():
            return {"valid": False, "reason": "record_unavailable"}
        try:
            data: Any = load_record(path)
        except CorrectionError as exc:
            reason = (
                "record_invalid_json"
                if "not valid JSON" in str(exc) else "record_unavailable"
            )
            return {"valid": False, "reason": reason}
    else:
        data = record_path_or_dict
    if not isinstance(data, Mapping):
        return {"valid": False, "reason": "record_not_object"}

    shape_reason = _validate_record_shape(data)
    if shape_reason is not None:
        return {"valid": False, "reason": shape_reason}

    requested_fields: list[str]
    if isinstance(operation_fields, (str, bytes)) or operation_fields is None:
        return {"valid": False, "reason": "invalid_requested_operation_fields"}
    try:
        requested_fields = [
            str(value) for value in operation_fields
        ]
    except TypeError:
        return {"valid": False, "reason": "invalid_requested_operation_fields"}
    if any(FIELD_RE.fullmatch(value) is None for value in requested_fields):
        return {"valid": False, "reason": "invalid_requested_operation_fields"}

    if data["source_sha256"] != source_sha256:
        return {"valid": False, "reason": "source_sha256_mismatch"}
    if data["corrected_tank"] != accepted_tank:
        return {"valid": False, "reason": "corrected_tank_mismatch"}
    if requested_tank != data["corrected_tank"]:
        return {"valid": False, "reason": "requested_tank_mismatch"}
    if data["product_id"] != product_id:
        return {"valid": False, "reason": "product_id_mismatch"}
    if variant_id is not None and data["variant_id"] != variant_id:
        return {"valid": False, "reason": "variant_id_mismatch"}
    recorded_scope = set(scope_fields(data["operation"]))
    if not set(requested_fields).issubset(recorded_scope):
        return {"valid": False, "reason": "operation_scope_mismatch"}
    return {"valid": True, "reason": "ok"}


def record(
    *,
    source_sha256: str,
    original_model_tank: str,
    corrected_tank: str,
    product_id: str,
    operation: Any,
    reason: str,
    evidence_reference: str,
    operator: str,
    variant_id: str | None = None,
    directory: Path | str | None = None,
    created_at: str | None = None,
) -> Path:
    """Write ONE immutable correction record; refuses to overwrite.

    Returns the path of the new record. Raises :class:`CorrectionError` on
    malformed input or when an identical record already exists.
    """
    core = {
        "schema": SCHEMA,
        "source_sha256": _require_sha(source_sha256, "source_sha256"),
        "original_model_tank": _require_tank(original_model_tank, "original_model_tank"),
        "corrected_tank": _require_tank(corrected_tank, "corrected_tank"),
        "product_id": _require_product(product_id, "product_id"),
        "variant_id": (
            None if variant_id is None else _require_nonempty(variant_id, "variant_id")
        ),
        "operation": _normalise_operation(operation),
        "reason": _require_nonempty(reason, "reason"),
        "evidence_reference": _require_nonempty(evidence_reference, "evidence_reference"),
        "operator": _require_nonempty(operator, "operator"),
        "created_at": _require_created_at(
            created_at if created_at is not None else utc_now(), "created_at"
        ),
    }
    if core["original_model_tank"] == core["corrected_tank"]:
        raise CorrectionError(
            "original_model_tank and corrected_tank must differ; "
            "a no-op correction is invalid"
        )
    digest = json_sha256(core)
    payload = {**core, "correction_sha256": digest}
    base = Path(directory).expanduser() if directory else default_directory()
    base = base.resolve()
    path = base / f"correction-{digest}.json"
    base.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    except FileExistsError as exc:
        raise CorrectionError(
            f"correction record already exists and is immutable: {path}"
        ) from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    _fsync_directory(base)
    return path


def _split_fields(value: str) -> list[str]:
    fields = [part.strip() for part in value.split(",")]
    fields = [field for field in fields if field]
    if not fields:
        raise argparse.ArgumentTypeError("at least one operation field is required")
    return fields


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="NTA Betta owner-correction records (immutable JSON)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    record_parser = sub.add_parser("record", help="write one immutable correction record")
    record_parser.add_argument("--source-sha256", required=True)
    record_parser.add_argument("--original-model-tank", required=True)
    record_parser.add_argument("--corrected-tank", required=True)
    record_parser.add_argument("--product-id", required=True)
    record_parser.add_argument("--variant-id")
    record_parser.add_argument(
        "--operation-fields", required=True, type=_split_fields,
        help="comma-separated fields the correction authorises",
    )
    record_parser.add_argument("--operation-mode", default="owner-directed")
    record_parser.add_argument("--reason", required=True)
    record_parser.add_argument("--evidence-reference", required=True)
    record_parser.add_argument("--operator", required=True)
    record_parser.add_argument("--directory", type=Path)
    record_parser.add_argument("--created-at")

    validate_parser = sub.add_parser("validate", help="validate a correction record")
    validate_parser.add_argument("--record", required=True, type=Path)
    validate_parser.add_argument("--source-sha256", required=True)
    validate_parser.add_argument("--requested-tank", required=True)
    validate_parser.add_argument("--accepted-tank", required=True)
    validate_parser.add_argument("--product-id", required=True)
    validate_parser.add_argument(
        "--variant-id",
        help="when provided, the record's variant_id must match exactly",
    )
    validate_parser.add_argument(
        "--operation-fields", required=True, type=_split_fields,
        help="comma-separated fields the intended operation will change",
    )

    args = parser.parse_args(argv)
    try:
        if args.command == "record":
            path = record(
                source_sha256=args.source_sha256,
                original_model_tank=args.original_model_tank,
                corrected_tank=args.corrected_tank,
                product_id=args.product_id,
                variant_id=args.variant_id,
                operation={
                    "fields": args.operation_fields,
                    "mode": args.operation_mode,
                },
                reason=args.reason,
                evidence_reference=args.evidence_reference,
                operator=args.operator,
                directory=args.directory,
                created_at=args.created_at,
            )
            data = load_record(path)
            print(json.dumps({
                "ok": True,
                "path": str(path),
                "correction_sha256": data["correction_sha256"],
            }, indent=2))
            return 0
        verdict = validate_correction(
            args.record,
            source_sha256=args.source_sha256,
            requested_tank=args.requested_tank,
            accepted_tank=args.accepted_tank,
            product_id=args.product_id,
            variant_id=args.variant_id,
            operation_fields=args.operation_fields,
        )
        print(json.dumps(verdict, indent=2))
        return 0 if verdict["valid"] else 2
    except (CorrectionError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
