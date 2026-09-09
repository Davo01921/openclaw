from __future__ import annotations


def _map(snapshot: dict):
    if not isinstance(snapshot, dict) or snapshot.get("source") != "FRESH_SHOPIFY_READ":
        return None
    lines = snapshot.get("line_items")
    if not isinstance(lines, list):
        return None
    result = {}
    for line in lines:
        if not isinstance(line, dict):
            return None
        line_id = line.get("fulfilment_order_line_item_id")
        remaining = line.get("remaining_quantity")
        if not isinstance(line_id, str) or not line_id.strip():
            return None
        if not isinstance(remaining, int) or isinstance(remaining, bool) or remaining < 0:
            return None
        result[line_id.strip()] = remaining
    return result


def derive_fulfilled_lines(before: dict, after: dict) -> dict:
    if not isinstance(before, dict) or not isinstance(after, dict):
        return {"status": "REVIEW_REQUIRED", "actual": None, "errors": ["before/after"]}
    if before.get("order_id") != after.get("order_id"):
        return {"status": "FAIL", "actual": None, "errors": ["order_id"]}
    if before.get("fulfilment_order_id") != after.get("fulfilment_order_id"):
        return {"status": "FAIL", "actual": None, "errors": ["fulfilment_order_id"]}
    bmap = _map(before)
    amap = _map(after)
    if bmap is None or amap is None:
        return {"status": "REVIEW_REQUIRED", "actual": None, "errors": ["fresh_line_state"]}
    if set(bmap) != set(amap):
        return {"status": "FAIL", "actual": None, "errors": ["line_identity_set"]}
    fulfilled = []
    for line_id in sorted(bmap):
        delta = bmap[line_id] - amap[line_id]
        if delta < 0:
            return {"status": "FAIL", "actual": None, "errors": [f"remaining_quantity_increased:{line_id}"]}
        if delta > 0:
            fulfilled.append({"fulfilment_order_line_item_id": line_id, "quantity": delta})
    return {
        "status": "SUCCESS",
        "actual": {
            "source": "FRESH_SHOPIFY_READ",
            "order_id": after.get("order_id"),
            "fulfilled_lines": fulfilled,
            "status": after.get("shopify_status") or "SUCCESS",
        },
        "errors": [],
    }
