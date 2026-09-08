#!/usr/bin/env python3
from inventory_state import decide


def expect(name, payload, status, operation=None, proposed=None):
    result = decide(payload)
    assert result["status"] == status, (name, result)
    if operation is not None:
        assert result["inventory"]["operation"] == operation, (name, result)
    if proposed is not None:
        assert result["inventory"]["proposed_available"] == proposed, (name, result)
    return result


base = {
    "variant_resolved": True,
    "sell_unit_conversion_status": "RESOLVED",
    "location": "NTA Main",
}

physical = expect(
    "physical count set",
    {**base, "job_state": "COUNTED", "quantity_basis": "PHYSICAL_COUNT", "usable_quantity": 30, "current_available": 12},
    "READY",
    "SET",
    30,
)

received = expect(
    "received increment add",
    {**base, "job_state": "RECEIVED", "quantity_basis": "RECEIVED_INCREMENT", "usable_quantity": 30, "current_available": 12},
    "READY",
    "ADD",
    42,
)

ordered = expect(
    "ordered none",
    {**base, "job_state": "ORDERED", "quantity_basis": "NONE", "current_available": 12},
    "READY",
    "NONE",
    12,
)

short_received = expect(
    "short/damaged usable received qty",
    {**base, "job_state": "RECEIVED", "quantity_basis": "RECEIVED_INCREMENT", "usable_quantity": 26, "current_available": 10},
    "READY",
    "ADD",
    36,
)

missing_location = expect(
    "missing location",
    {"variant_resolved": True, "sell_unit_conversion_status": "RESOLVED", "job_state": "COUNTED", "quantity_basis": "PHYSICAL_COUNT", "usable_quantity": 20},
    "REVIEW_REQUIRED",
)

bad_sell_unit = expect(
    "unresolved sell unit",
    {"variant_resolved": True, "sell_unit_conversion_status": "UNKNOWN", "job_state": "COUNTED", "quantity_basis": "PHYSICAL_COUNT", "usable_quantity": 20, "location": "NTA Main"},
    "REVIEW_REQUIRED",
)

negative_no_auth = expect(
    "negative stock correction without authorisation",
    {**base, "job_state": "CORRECTION", "quantity_basis": "PHYSICAL_COUNT", "usable_quantity": 8, "current_available": -4, "correction_authorised": False},
    "REVIEW_REQUIRED",
)

negative_auth = expect(
    "negative stock authorised correction",
    {**base, "job_state": "CORRECTION", "quantity_basis": "PHYSICAL_COUNT", "usable_quantity": 8, "current_available": -4, "correction_authorised": True},
    "READY",
    "SET",
    8,
)

print("DRY_RUN_PASS: deterministic inventory state; physical-count SET, received-increment ADD, ordered NONE, usable received quantity, location gate, sell-unit gate, and authorised negative-stock correction; no Shopify writes, network calls, or model calls")
print("Physical count operation:", physical["inventory"]["operation"], physical["inventory"]["proposed_available"])
print("Received increment operation:", received["inventory"]["operation"], received["inventory"]["proposed_available"])
print("Ordered operation:", ordered["inventory"]["operation"])
print("Short/damaged received proposed:", short_received["inventory"]["proposed_available"])
print("Missing location status:", missing_location["status"])
print("Unresolved sell unit status:", bad_sell_unit["status"])
print("Negative correction without auth:", negative_no_auth["status"])
print("Negative correction with auth:", negative_auth["status"])
