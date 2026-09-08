#!/usr/bin/env python3
from metafield_mapper import map_metafields


def assert_eq(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def defs(*keys):
    return {k: {"owner_scope": "PRODUCT", "type": "test_type"} for k in keys}


def main():
    availability = map_metafields({
        "requested_fields": ["preorder_eligible", "preorder_status_override"],
        "availability": {"preorder_eligible": True, "status_override": "automatic"},
        "verified_definitions": defs("custom.preorder_eligible", "custom.preorder_status_override"),
    })
    assert_eq(availability["status"], "READY", "availability status")
    assert_eq(len(availability["metafields"]["proposed"]), 2, "availability count")

    arrival = map_metafields({
        "requested_fields": ["arrival_date"],
        "product_state": {"arrival_date": "2026-09-08"},
        "verified_definitions": defs("custom.arrival_date"),
    })
    assert_eq(arrival["status"], "READY", "arrival date")

    tank = map_metafields({
        "requested_fields": ["in_store_location_tank_number"],
        "product_state": {"in_store_location_tank_number": "63.10.1"},
        "verified_definitions": defs("custom.in_store_location_tank_number"),
    })
    assert_eq(tank["status"], "READY", "tank location")

    unknown = map_metafields({
        "requested_fields": ["made_up_field"],
        "verified_definitions": {},
    })
    assert_eq(unknown["status"], "REVIEW_REQUIRED", "unknown field")

    missing_def = map_metafields({
        "requested_fields": ["preorder_eligible"],
        "availability": {"preorder_eligible": True},
        "verified_definitions": {},
    })
    assert_eq(missing_def["status"], "REVIEW_REQUIRED", "missing definition")

    bad_override = map_metafields({
        "requested_fields": ["preorder_status_override"],
        "availability": {"status_override": "maybe"},
        "verified_definitions": defs("custom.preorder_status_override"),
    })
    assert_eq(bad_override["status"], "REVIEW_REQUIRED", "bad override")

    guessed_date = map_metafields({
        "requested_fields": ["arrival_date"],
        "product_state": {"arrival_date": "next Tuesday"},
        "verified_definitions": defs("custom.arrival_date"),
    })
    assert_eq(guessed_date["status"], "REVIEW_REQUIRED", "non ISO date")

    print("DRY_RUN_PASS: deterministic metafield mapping; availability, arrival date, tank location, unknown-field gate, verified-definition gate, enum validation, and ISO-date validation; no Shopify writes, network calls, or model calls")
    print("Availability mapping:", availability["status"], len(availability["metafields"]["proposed"]))
    print("Arrival date status:", arrival["status"])
    print("Tank location status:", tank["status"])
    print("Unknown field status:", unknown["status"])
    print("Missing definition status:", missing_def["status"])
    print("Invalid override status:", bad_override["status"])
    print("Non-ISO arrival date status:", guessed_date["status"])


if __name__ == "__main__":
    main()
