from __future__ import annotations

import re
from typing import Any

MAX_BARCODE_LENGTH = 48
INTERNAL_PREFIX = "NTA-V-"
VARIANT_GID_RE = re.compile(r"^gid://shopify/ProductVariant/([0-9]+)$")


class BarcodePolicyError(ValueError):
    pass


def _validate_printable_barcode(value: str) -> str:
    value = value.strip()
    if not value:
        raise BarcodePolicyError("barcode must not be empty")
    if len(value) > MAX_BARCODE_LENGTH:
        raise BarcodePolicyError(f"barcode exceeds {MAX_BARCODE_LENGTH} characters")
    if any(ord(char) < 32 or ord(char) > 126 for char in value):
        raise BarcodePolicyError("barcode must contain printable ASCII only")
    return value


def _legacy_id(variant_id: str, explicit_legacy_resource_id: Any = None) -> str:
    if explicit_legacy_resource_id is not None:
        text = str(explicit_legacy_resource_id).strip()
        if text.isdigit() and int(text) > 0:
            return text
        raise BarcodePolicyError("legacy_resource_id must be a positive integer")
    if not isinstance(variant_id, str):
        raise BarcodePolicyError("variant_id must be a Shopify ProductVariant GID")
    match = VARIANT_GID_RE.fullmatch(variant_id.strip())
    if not match:
        raise BarcodePolicyError("variant_id must be a Shopify ProductVariant GID")
    return match.group(1)


def generate_internal_barcode(variant_id: str, legacy_resource_id: Any = None) -> str:
    barcode = f"{INTERNAL_PREFIX}{_legacy_id(variant_id, legacy_resource_id)}"
    return _validate_printable_barcode(barcode)


def plan_barcode(data: dict[str, Any]) -> dict[str, Any]:
    invalid: list[str] = []

    variant_id = data.get("variant_id")
    try:
        legacy_id = _legacy_id(variant_id, data.get("legacy_resource_id"))
    except BarcodePolicyError:
        legacy_id = None
        invalid.append("variant_id_or_legacy_resource_id")

    if "current_shopify_barcode" not in data:
        invalid.append("current_shopify_barcode")
        current = None
    else:
        current = data.get("current_shopify_barcode")

    if invalid:
        return {
            "status": "REVIEW_REQUIRED",
            "action": None,
            "barcode": None,
            "requires_shopify_write": False,
            "missing_or_invalid_fields": sorted(set(invalid)),
        }

    if current is not None and (not isinstance(current, str) or current.strip()):
        if not isinstance(current, str):
            return {
                "status": "REVIEW_REQUIRED",
                "action": None,
                "barcode": None,
                "requires_shopify_write": False,
                "missing_or_invalid_fields": ["current_shopify_barcode"],
            }
        try:
            barcode = _validate_printable_barcode(current)
        except BarcodePolicyError:
            return {
                "status": "REVIEW_REQUIRED",
                "action": None,
                "barcode": None,
                "requires_shopify_write": False,
                "missing_or_invalid_fields": ["current_shopify_barcode"],
            }
        return {
            "status": "READY",
            "action": "KEEP_EXISTING",
            "barcode": barcode,
            "barcode_source": "existing_shopify",
            "requires_shopify_write": False,
            "collision_query": f"barcode:{barcode}",
            "legacy_resource_id": legacy_id,
        }

    barcode = generate_internal_barcode(variant_id, legacy_id)
    return {
        "status": "READY",
        "action": "CREATE_INTERNAL",
        "barcode": barcode,
        "barcode_source": "generated_internal",
        "requires_shopify_write": True,
        "collision_query": f"barcode:{barcode}",
        "legacy_resource_id": legacy_id,
    }


def collision_status(
    *,
    candidate_barcode: str,
    target_variant_id: str,
    matching_variant_ids: list[str],
) -> dict[str, Any]:
    candidate_barcode = _validate_printable_barcode(candidate_barcode)
    foreign = sorted({variant_id for variant_id in matching_variant_ids if variant_id != target_variant_id})
    if foreign:
        return {
            "status": "REVIEW_REQUIRED",
            "barcode": candidate_barcode,
            "collision": True,
            "conflicting_variant_ids": foreign,
        }
    return {
        "status": "READY",
        "barcode": candidate_barcode,
        "collision": False,
        "conflicting_variant_ids": [],
    }


def verification_status(*, expected_barcode: str, live_barcode: Any) -> dict[str, Any]:
    expected_barcode = _validate_printable_barcode(expected_barcode)
    if not isinstance(live_barcode, str):
        return {
            "status": "FAILED",
            "expected_barcode": expected_barcode,
            "live_barcode": live_barcode,
        }
    try:
        actual = _validate_printable_barcode(live_barcode)
    except BarcodePolicyError:
        return {
            "status": "FAILED",
            "expected_barcode": expected_barcode,
            "live_barcode": live_barcode,
        }
    return {
        "status": "VERIFIED" if actual == expected_barcode else "FAILED",
        "expected_barcode": expected_barcode,
        "live_barcode": actual,
    }
