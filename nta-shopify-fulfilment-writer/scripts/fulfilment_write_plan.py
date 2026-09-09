from __future__ import annotations

from typing import Any


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def build_fulfilment_write_plan(data: dict) -> dict:
    errors: list[str] = []
    for field in ("job_id", "idempotency_key", "order_id"):
        if not _nonempty(data.get(field)):
            errors.append(field)
    if data.get("authorised") is not True:
        errors.append("authorised")
    if not isinstance(data.get("notify_customer"), bool):
        errors.append("notify_customer")
    duplicate_completed = data.get("duplicate_completed")
    prior_result_indeterminate = data.get("prior_result_indeterminate")
    retry_authorised = data.get("retry_authorised")
    adapter_capability_verified = data.get("adapter_capability_verified")
    for field, value in (
        ("duplicate_completed", duplicate_completed),
        ("prior_result_indeterminate", prior_result_indeterminate),
        ("retry_authorised", retry_authorised),
        ("adapter_capability_verified", adapter_capability_verified),
    ):
        if not isinstance(value, bool):
            errors.append(field)

    groups = data.get("fulfilment_orders")
    canonical_groups: list[dict] = []
    if not isinstance(groups, list) or not groups:
        errors.append("fulfilment_orders")
    else:
        seen_fo: set[str] = set()
        seen_lines: set[str] = set()
        for i, group in enumerate(groups):
            prefix = f"fulfilment_orders[{i}]"
            if not isinstance(group, dict):
                errors.append(prefix)
                continue
            fo_id = group.get("fulfilment_order_id")
            if not _nonempty(fo_id):
                errors.append(f"{prefix}.fulfilment_order_id")
                continue
            fo_id = fo_id.strip()
            if fo_id in seen_fo:
                errors.append(f"{prefix}.fulfilment_order_id:duplicate")
            seen_fo.add(fo_id)
            lines = group.get("line_items")
            canonical_lines: list[dict] = []
            if not isinstance(lines, list) or not lines:
                errors.append(f"{prefix}.line_items")
            else:
                for j, line in enumerate(lines):
                    lp = f"{prefix}.line_items[{j}]"
                    if not isinstance(line, dict):
                        errors.append(lp)
                        continue
                    line_id = line.get("fulfilment_order_line_item_id")
                    qty = line.get("quantity")
                    if not _nonempty(line_id):
                        errors.append(f"{lp}.fulfilment_order_line_item_id")
                        continue
                    line_id = line_id.strip()
                    if line_id in seen_lines:
                        errors.append(f"{lp}.fulfilment_order_line_item_id:duplicate")
                    seen_lines.add(line_id)
                    if not _positive_int(qty):
                        errors.append(f"{lp}.quantity")
                        continue
                    canonical_lines.append({"fulfilment_order_line_item_id": line_id, "quantity": qty})
            canonical_groups.append({"fulfilment_order_id": fo_id, "line_items": canonical_lines})

    if errors:
        return {"status": "REVIEW_REQUIRED", "write_ready": False, "write_plan": None, "missing_or_conflicting_fields": sorted(set(errors))}
    if duplicate_completed:
        return {"status": "DUPLICATE_NOOP", "write_ready": False, "write_plan": None, "missing_or_conflicting_fields": []}
    if prior_result_indeterminate and not retry_authorised:
        return {"status": "REVIEW_REQUIRED", "write_ready": False, "write_plan": None, "missing_or_conflicting_fields": ["retry_authorised"]}
    if adapter_capability_verified is not True:
        return {"status": "REVIEW_REQUIRED", "write_ready": False, "write_plan": None, "missing_or_conflicting_fields": ["adapter_capability_verified"]}

    return {
        "status": "READY",
        "write_ready": True,
        "write_plan": {
            "job_id": data["job_id"].strip(),
            "idempotency_key": data["idempotency_key"].strip(),
            "order_id": data["order_id"].strip(),
            "notify_customer": data["notify_customer"],
            "fulfilment_orders": canonical_groups,
            "tracking_info": None,
            "retry_authorised": retry_authorised,
        },
        "missing_or_conflicting_fields": [],
    }
