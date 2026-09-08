from __future__ import annotations

from typing import Any

VALID_INTENTS = {"CREATE_ORDER", "UPDATE_ORDER_METADATA"}
FORBIDDEN_KEYS = {
    "fulfilment",
    "fulfillment",
    "fulfilment_status",
    "fulfillment_status",
    "tracking_number",
    "tracking_company",
}


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _collect_forbidden_keys(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            if key.lower() in FORBIDDEN_KEYS:
                found.append(child_path)
            found.extend(_collect_forbidden_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            found.extend(_collect_forbidden_keys(child, child_path))
    return found


def build_order_write_plan(data: dict) -> dict:
    errors: list[str] = []

    job_id = data.get("job_id")
    if not _nonempty_string(job_id):
        errors.append("job_id")

    idempotency_key = data.get("idempotency_key")
    if not _nonempty_string(idempotency_key):
        errors.append("idempotency_key")

    intent = data.get("intent")
    if intent not in VALID_INTENTS:
        errors.append("intent")

    if data.get("authorised") is not True:
        errors.append("authorised")

    expected_result = data.get("expected_result")
    if not isinstance(expected_result, dict) or not expected_result:
        errors.append("expected_result")

    duplicate_completed = data.get("duplicate_completed")
    if not isinstance(duplicate_completed, bool):
        errors.append("duplicate_completed")

    prior_result_indeterminate = data.get("prior_result_indeterminate")
    if not isinstance(prior_result_indeterminate, bool):
        errors.append("prior_result_indeterminate")

    retry_authorised = data.get("retry_authorised")
    if not isinstance(retry_authorised, bool):
        errors.append("retry_authorised")

    adapter_capability_verified = data.get("adapter_capability_verified")
    if not isinstance(adapter_capability_verified, bool):
        errors.append("adapter_capability_verified")

    forbidden = _collect_forbidden_keys(data)
    errors.extend(f"forbidden:{path}" for path in forbidden)

    order = data.get("order")
    canonical_order = None
    if not isinstance(order, dict):
        errors.append("order")
    else:
        customer_id = order.get("customer_id")
        if not _nonempty_string(customer_id):
            errors.append("order.customer_id")

        line_items = order.get("line_items")
        canonical_lines: list[dict] = []
        seen_variant_ids: set[str] = set()
        if not isinstance(line_items, list) or not line_items:
            errors.append("order.line_items")
        else:
            for index, item in enumerate(line_items):
                prefix = f"order.line_items[{index}]"
                if not isinstance(item, dict):
                    errors.append(prefix)
                    continue
                variant_id = item.get("variant_id")
                quantity = item.get("quantity")
                if not _nonempty_string(variant_id):
                    errors.append(f"{prefix}.variant_id")
                    continue
                variant_id = variant_id.strip()
                if variant_id in seen_variant_ids:
                    errors.append(f"{prefix}.variant_id:duplicate")
                else:
                    seen_variant_ids.add(variant_id)
                if not _positive_int(quantity):
                    errors.append(f"{prefix}.quantity")
                    continue
                canonical_lines.append({"variant_id": variant_id, "quantity": quantity})

        tags = order.get("tags", [])
        if not isinstance(tags, list) or any(not _nonempty_string(tag) for tag in tags):
            errors.append("order.tags")
            tags = []

        note = order.get("note")
        if note is not None and not isinstance(note, str):
            errors.append("order.note")

        discount = order.get("discount", {})
        if discount is None:
            discount = {}
        if not isinstance(discount, dict):
            errors.append("order.discount")
            discount = {}
        discount_code = discount.get("code")
        if discount_code is not None and not _nonempty_string(discount_code):
            errors.append("order.discount.code")

        financial_target = order.get("financial_target")
        if financial_target is not None and not isinstance(financial_target, (str, dict)):
            errors.append("order.financial_target")

        canonical_order = {
            "customer_id": customer_id.strip() if isinstance(customer_id, str) else None,
            "line_items": canonical_lines,
            "tags": [tag.strip() for tag in tags] if isinstance(tags, list) else [],
            "note": note,
            "discount": {"code": discount_code.strip() if isinstance(discount_code, str) else None},
            "financial_target": financial_target,
        }

    target_order_id = data.get("target_order_id")
    if intent == "CREATE_ORDER" and target_order_id is not None:
        errors.append("target_order_id:must_be_null_for_create")
    if intent == "UPDATE_ORDER_METADATA" and not _nonempty_string(target_order_id):
        errors.append("target_order_id")

    if errors:
        return {
            "status": "REVIEW_REQUIRED",
            "write_ready": False,
            "write_plan": None,
            "missing_or_conflicting_fields": sorted(set(errors)),
            "notes": [],
        }

    if duplicate_completed:
        return {
            "status": "DUPLICATE_NOOP",
            "write_ready": False,
            "write_plan": None,
            "missing_or_conflicting_fields": [],
            "notes": ["Matching completed idempotent order action already exists; do not write again."],
        }

    if prior_result_indeterminate and not retry_authorised:
        return {
            "status": "REVIEW_REQUIRED",
            "write_ready": False,
            "write_plan": None,
            "missing_or_conflicting_fields": ["retry_authorised"],
            "notes": ["Previous result is indeterminate; retry is blocked unless explicitly authorised with the same idempotency key."],
        }

    if adapter_capability_verified is not True:
        return {
            "status": "REVIEW_REQUIRED",
            "write_ready": False,
            "write_plan": None,
            "missing_or_conflicting_fields": ["adapter_capability_verified"],
            "notes": ["No live write is allowed until the concrete Shopify order adapter capability is verified."],
        }

    assert isinstance(job_id, str)
    assert isinstance(idempotency_key, str)

    return {
        "status": "READY",
        "write_ready": True,
        "write_plan": {
            "job_id": job_id.strip(),
            "idempotency_key": idempotency_key.strip(),
            "intent": intent,
            "target_order_id": target_order_id.strip() if isinstance(target_order_id, str) else None,
            "order": canonical_order,
            "expected_result": expected_result,
            "protected_fields": data.get("protected_fields", []),
            "retry_authorised": retry_authorised,
        },
        "missing_or_conflicting_fields": [],
        "notes": [
            "Deterministic preflight passed. Apply only the authorised Shopify order action.",
            "Do not perform fulfilment or a separate inventory adjustment in this writer.",
            "A successful write still requires independent fresh order audit before completion.",
        ],
    }
