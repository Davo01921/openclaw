from __future__ import annotations


def _line_map(lines):
    if not isinstance(lines, list):
        return None
    out = {}
    for line in lines:
        if not isinstance(line, dict):
            return None
        line_id = line.get("fulfilment_order_line_item_id")
        qty = line.get("quantity")
        if not isinstance(line_id, str) or not line_id.strip() or not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            return None
        key = line_id.strip()
        if key in out:
            return None
        out[key] = qty
    return out


def audit_fulfilment(expected: dict, actual: dict) -> dict:
    problems = []
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return {"status": "REVIEW_REQUIRED", "mismatches": ["expected/actual must be objects"]}
    if actual.get("source") != "FRESH_SHOPIFY_READ":
        problems.append("actual.source")
    if expected.get("order_id") != actual.get("order_id"):
        problems.append("order_id")
    expected_lines = _line_map(expected.get("fulfilled_lines"))
    actual_lines = _line_map(actual.get("fulfilled_lines"))
    if expected_lines is None:
        problems.append("expected.fulfilled_lines")
    if actual_lines is None:
        problems.append("actual.fulfilled_lines")
    if expected_lines is not None and actual_lines is not None and expected_lines != actual_lines:
        problems.append("fulfilled_lines")
    status = actual.get("status")
    if status not in {"SUCCESS", "OPEN", "FULFILLED"}:
        problems.append("status")
    return {"status": "PASS" if not problems else "FAIL", "mismatches": sorted(set(problems))}
