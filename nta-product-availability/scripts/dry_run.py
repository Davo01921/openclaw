#!/usr/bin/env python3
"""Regression tests for nta-product-availability deterministic decision engine."""

from availability import decide_availability


def check(name, payload, expected_status, expected_state, expected_policy, expected_preorder):
    result = decide_availability(payload).to_dict()
    assert result["status"] == expected_status, (name, result)
    a = result["availability"]
    assert a["customer_state"] == expected_state, (name, result)
    assert a["inventory_policy"] == expected_policy, (name, result)
    assert a["preorder_eligible"] == expected_preorder, (name, result)
    return result


base = {
    "variant_resolved": True,
    "individually_identified": False,
    "discontinued": False,
    "clearance_only": False,
    "internal_use": False,
    "nta_wants_further_orders": True,
}

in_stock = check(
    "replenishable in stock",
    {**base, "replenishable": True, "available_qty": 12, "supplier_source_state": "NORMAL"},
    "READY", "IN_STOCK", "CONTINUE", True,
)

preorder = check(
    "zero stock normal source",
    {**base, "replenishable": True, "available_qty": 0, "supplier_source_state": "NORMAL"},
    "READY", "PREORDER", "CONTINUE", True,
)

eta_tbc = check(
    "zero stock timing uncertain",
    {**base, "replenishable": True, "available_qty": 0, "supplier_source_state": "ORDERABLE_TIMING_UNCERTAIN"},
    "READY", "AVAILABLE_TO_ORDER_ETA_TBC", "CONTINUE", True,
)

remaining_one_off = check(
    "remaining one-off stock",
    {**base, "replenishable": False, "individually_identified": True, "available_qty": 5, "supplier_source_state": "NORMAL"},
    "READY", "IN_STOCK", "DENY", False,
)

unavailable = check(
    "cannot source zero stock",
    {**base, "replenishable": True, "available_qty": 0, "supplier_source_state": "CANNOT_SOURCE"},
    "READY", "UNAVAILABLE", "DENY", False,
)

unknown_replenishment = decide_availability(
    {**base, "replenishable": None, "available_qty": 0, "supplier_source_state": "NORMAL"}
).to_dict()
assert unknown_replenishment["status"] == "REVIEW_REQUIRED"
assert "replenishable" in unknown_replenishment["missing_or_conflicting_fields"]

unknown_source = decide_availability(
    {**base, "replenishable": True, "available_qty": 0, "supplier_source_state": "UNKNOWN"}
).to_dict()
assert unknown_source["status"] == "REVIEW_REQUIRED"
assert "supplier_source_state" in unknown_source["missing_or_conflicting_fields"]

in_stock_unknown_replenishment = check(
    "in stock with unknown replenishment",
    {**base, "replenishable": None, "available_qty": 3, "supplier_source_state": "UNKNOWN"},
    "READY", "IN_STOCK", "DENY", False,
)

explicit_disabled = check(
    "explicit disabled with stock",
    {**base, "replenishable": True, "available_qty": 4, "supplier_source_state": "NORMAL", "explicit_status_override": "disabled"},
    "READY", "IN_STOCK", "DENY", False,
)

negative_inventory = decide_availability(
    {**base, "replenishable": True, "available_qty": -1, "supplier_source_state": "NORMAL"}
).to_dict()
assert negative_inventory["status"] == "REVIEW_REQUIRED"
assert "available_qty" in negative_inventory["missing_or_conflicting_fields"]

print("DRY_RUN_PASS: deterministic product availability; in-stock, preorder, ETA-TBC, remaining one-off stock, cannot-source, unknown replenishment/source gates, explicit disable, and negative-inventory gate; no Shopify writes, network calls, or model calls")
print("In-stock:", in_stock["availability"]["customer_state"], in_stock["availability"]["inventory_policy"])
print("Preorder:", preorder["availability"]["customer_state"], preorder["availability"]["inventory_policy"])
print("ETA-TBC:", eta_tbc["availability"]["customer_state"])
print("Remaining one-off:", remaining_one_off["availability"]["customer_state"], remaining_one_off["availability"]["inventory_policy"])
print("Cannot source:", unavailable["availability"]["customer_state"])
print("Unknown replenishment status:", unknown_replenishment["status"])
print("Unknown source status:", unknown_source["status"])
print("In-stock unknown replenishment policy:", in_stock_unknown_replenishment["availability"]["inventory_policy"])
print("Explicit disabled policy:", explicit_disabled["availability"]["inventory_policy"])
print("Negative inventory status:", negative_inventory["status"])
