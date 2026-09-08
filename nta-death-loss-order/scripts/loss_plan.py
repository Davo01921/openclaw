from __future__ import annotations

from hashlib import sha256
from typing import Any

CUSTOMER_NAME = "NTA Losses"
DISCOUNT_CODE = "Ntalosses"
TARGET_TOTAL_AUD = "0.00"
BASE_TAGS = ["NTA Loss", "Death"]
VALID_MODES = {"dry_run", "write"}
VALID_RESOLUTION_STATUSES = {"RESOLVED", "REVIEW_REQUIRED", "UNMATCHED", "BLOCKED"}


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _as_bool(value: Any, field: str, errors: list[str]) -> bool | None:
    if isinstance(value, bool):
        return value
    errors.append(field)
    return None


def _canonical_item(item: dict, index: int, errors: list[str]) -> dict | None:
    prefix = f"loss_items[{index}]"
    resolution_status = item.get("resolution_status")
    variant_id = item.get("shopify_variant_id")
    quantity = item.get("quantity")

    if resolution_status not in VALID_RESOLUTION_STATUSES:
        errors.append(f"{prefix}.resolution_status")
    elif resolution_status != "RESOLVED":
        errors.append(f"{prefix}.resolution_status:{resolution_status}")

    if not _nonempty_string(variant_id):
        errors.append(f"{prefix}.shopify_variant_id")
    if not _positive_int(quantity):
        errors.append(f"{prefix}.quantity")

    if errors and any(e.startswith(prefix) for e in errors):
        return None

    tank = item.get("tank")
    if tank is not None and not _nonempty_string(tank):
        errors.append(f"{prefix}.tank")
        return None

    confidence = item.get("identification_confidence")
    if confidence is not None and not _nonempty_string(confidence):
        errors.append(f"{prefix}.identification_confidence")
        return None

    evidence = item.get("evidence")
    if evidence is not None and not isinstance(evidence, list):
        errors.append(f"{prefix}.evidence")
        return None

    return {
        "shopify_variant_id": variant_id.strip(),
        "quantity": quantity,
        "fish": item.get("fish"),
        "tank": tank.strip() if isinstance(tank, str) else None,
        "cause": item.get("cause"),
        "identification_confidence": confidence,
        "evidence": evidence or [],
    }


def _idempotency_key(source_event_id: str, items: list[dict]) -> str:
    canonical = [source_event_id]
    for item in sorted(items, key=lambda x: (x["shopify_variant_id"], x["quantity"])):
        canonical.append(f'{item["shopify_variant_id"]}:{item["quantity"]}')
    digest = sha256("|".join(canonical).encode("utf-8")).hexdigest()[:24]
    return f"nta-loss:{digest}"


def build_loss_plan(data: dict) -> dict:
    errors: list[str] = []

    mode = data.get("mode")
    if mode not in VALID_MODES:
        errors.append("mode")

    source_event_id = data.get("source_event_id")
    if not _nonempty_string(source_event_id):
        errors.append("source_event_id")

    items_raw = data.get("loss_items")
    if not isinstance(items_raw, list) or not items_raw:
        errors.append("loss_items")
        items_raw = []

    items: list[dict] = []
    for i, item in enumerate(items_raw):
        if not isinstance(item, dict):
            errors.append(f"loss_items[{i}]")
            continue
        canonical = _canonical_item(item, i, errors)
        if canonical is not None:
            items.append(canonical)

    prior_loss_order_found = _as_bool(data.get("prior_loss_order_found"), "prior_loss_order_found", errors)
    prior_manual_deduction_found = _as_bool(
        data.get("prior_manual_deduction_found"), "prior_manual_deduction_found", errors
    )
    manual_reversal_verified = _as_bool(
        data.get("manual_reversal_verified"), "manual_reversal_verified", errors
    )

    if errors:
        return {
            "status": "REVIEW_REQUIRED",
            "write_ready": False,
            "order_plan": None,
            "missing_or_conflicting_fields": sorted(set(errors)),
            "notes": [],
        }

    assert isinstance(source_event_id, str)

    if prior_loss_order_found:
        return {
            "status": "DUPLICATE_NOOP",
            "write_ready": False,
            "order_plan": None,
            "missing_or_conflicting_fields": [],
            "notes": ["A loss order for this source event/items is already recorded; do not deduct inventory again."],
        }

    idempotency_key = _idempotency_key(source_event_id.strip(), items)

    tags = list(BASE_TAGS)
    for tank in sorted({item["tank"] for item in items if item["tank"]}):
        tags.append(f"Tank {tank}")

    expected_net_loss_by_variant: dict[str, int] = {}
    for item in items:
        variant_id = item["shopify_variant_id"]
        expected_net_loss_by_variant[variant_id] = expected_net_loss_by_variant.get(variant_id, 0) + item["quantity"]

    order_plan = {
        "customer": CUSTOMER_NAME,
        "discount_code": DISCOUNT_CODE,
        "target_total_aud": TARGET_TOTAL_AUD,
        "tags": tags,
        "line_items": [
            {
                "shopify_variant_id": item["shopify_variant_id"],
                "quantity": item["quantity"],
            }
            for item in items
        ],
        "note_fields": [
            {
                "fish": item["fish"],
                "quantity": item["quantity"],
                "tank": item["tank"],
                "cause": item["cause"],
                "identification_confidence": item["identification_confidence"],
                "evidence": item["evidence"],
                "source_event_id": source_event_id.strip(),
            }
            for item in items
        ],
        "financial_target": "PAID_OR_ZERO_BALANCE_VERIFIED",
        "fulfilment_target": "FULFILLED",
        "inventory_effect": "ORDER_ONLY_NO_SEPARATE_DEDUCTION",
        "expected_net_loss_by_variant": expected_net_loss_by_variant,
        "idempotency_key": idempotency_key,
        "preserve_unrelated_product_fields": True,
    }

    if mode == "dry_run":
        return {
            "status": "READY",
            "write_ready": False,
            "order_plan": order_plan,
            "missing_or_conflicting_fields": [],
            "notes": [
                "Dry run only: no Shopify order, fulfilment, payment, or inventory mutation is authorised.",
                "Photo/vision evidence may generate a candidate, but exact variant resolution must already be RESOLVED before this planner is READY.",
            ],
        }

    write_errors: list[str] = []
    customer_verified = _as_bool(data.get("customer_verified"), "customer_verified", write_errors)
    discount_zero_verified = _as_bool(data.get("discount_zero_verified"), "discount_zero_verified", write_errors)
    location_verified = _as_bool(data.get("location_verified"), "location_verified", write_errors)
    order_write_capability_verified = _as_bool(
        data.get("order_write_capability_verified"), "order_write_capability_verified", write_errors
    )
    fulfilment_write_capability_verified = _as_bool(
        data.get("fulfilment_write_capability_verified"), "fulfilment_write_capability_verified", write_errors
    )

    if prior_manual_deduction_found and not manual_reversal_verified:
        write_errors.append("manual_reversal_verified")
    if customer_verified is False:
        write_errors.append("customer_verified:false")
    if discount_zero_verified is False:
        write_errors.append("discount_zero_verified:false")
    if location_verified is False:
        write_errors.append("location_verified:false")
    if order_write_capability_verified is False:
        write_errors.append("order_write_capability_verified:false")
    if fulfilment_write_capability_verified is False:
        write_errors.append("fulfilment_write_capability_verified:false")

    if write_errors:
        return {
            "status": "REVIEW_REQUIRED",
            "write_ready": False,
            "order_plan": order_plan,
            "missing_or_conflicting_fields": sorted(set(write_errors)),
            "notes": ["Write mode is blocked until all live Shopify and mutation-capability preconditions are verified."],
        }

    return {
        "status": "READY",
        "write_ready": True,
        "order_plan": order_plan,
        "missing_or_conflicting_fields": [],
        "notes": [
            "All deterministic preconditions are satisfied; mutation still must pass through the authorised Shopify write/verification boundary.",
            "Do not make a separate inventory deduction for the same loss order.",
        ],
    }
