from __future__ import annotations


def audit_inventory_effect(expected: dict, before: dict, after: dict) -> dict:
    problems = []
    if not isinstance(expected, dict) or not expected:
        return {"status": "REVIEW_REQUIRED", "mismatches": ["expected"]}
    if not isinstance(before, dict) or not isinstance(after, dict):
        return {"status": "REVIEW_REQUIRED", "mismatches": ["before/after"]}

    evidence = {}
    for level_id, expected_loss in expected.items():
        if not isinstance(level_id, str) or not level_id.strip():
            problems.append("inventory_level_id")
            continue
        if not isinstance(expected_loss, int) or isinstance(expected_loss, bool) or expected_loss <= 0:
            problems.append(f"{level_id}.expected_loss")
            continue
        b = before.get(level_id)
        a = after.get(level_id)
        if not isinstance(b, dict):
            problems.append(f"{level_id}.before")
            continue
        if not isinstance(a, dict):
            problems.append(f"{level_id}.after")
            continue
        if b.get("source") != "FRESH_SHOPIFY_READ":
            problems.append(f"{level_id}.before.source")
        if a.get("source") != "FRESH_SHOPIFY_READ":
            problems.append(f"{level_id}.after.source")
        b_avail = b.get("available")
        a_avail = a.get("available")
        if not isinstance(b_avail, int) or isinstance(b_avail, bool):
            problems.append(f"{level_id}.before.available")
            continue
        if not isinstance(a_avail, int) or isinstance(a_avail, bool):
            problems.append(f"{level_id}.after.available")
            continue
        actual_loss = b_avail - a_avail
        evidence[level_id] = {
            "before_available": b_avail,
            "after_available": a_avail,
            "expected_loss": expected_loss,
            "actual_loss": actual_loss,
            "before_on_hand": b.get("on_hand"),
            "after_on_hand": a.get("on_hand"),
        }
        if actual_loss != expected_loss:
            problems.append(f"{level_id}.available_delta")

    return {
        "status": "PASS" if not problems else "FAIL",
        "mismatches": sorted(set(problems)),
        "evidence": evidence,
    }
