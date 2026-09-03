#!/usr/bin/env python3
"""Offline regression fixture for the NTA DYMO tank-label contract.

This simulates the resolved intake -> planned Shopify fields -> inventory ->
arrival-date read-back -> label path.  It deliberately has no Shopify client,
credentials, network calls, or print operation.
"""

from datetime import date
from decimal import Decimal


def money(value):
    amount = Decimal(str(value))
    if amount < 0:
        raise ValueError("retail_price must be non-negative")
    return format(amount.normalize(), "f").rstrip("0").rstrip(".") if "." in format(amount.normalize(), "f") else format(amount.normalize(), "f")


def make_label(item):
    name = item["name"].strip()
    quantity = item["received_quantity"]
    retail = Decimal(str(item["retail_price"]))
    arrival = date.fromisoformat(item["dry_run_shopify_state"]["custom.arrival_date"])
    if not name or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("name and positive received Shopify-selling-unit quantity are required")

    first_line = f"{name} | ${money(retail)}ea"
    bulk_price = item.get("bulk_price")
    bulk_minimum = item.get("bulk_min_quantity")
    if bulk_price is not None:
        bulk = Decimal(str(bulk_price))
        if isinstance(bulk_minimum, int) and bulk_minimum >= 2 and bulk >= 0 and bulk < retail:
            first_line += f" | ${money(bulk)}ea/{bulk_minimum}+"

    return f"{first_line}\n{arrival:%d%m%y} | Q{quantity}"


def simulate_intake(item):
    # This represents resolved intake data. The only date passed to the label
    # is the proposed Shopify metafield after the dry-run change-set boundary.
    planned_shopify = {
        "variant.price": item["retail_price"],
        "inventory.available": item["received_quantity"],
        "custom.arrival_date": item["arrival_date"],
    }
    item["dry_run_shopify_state"] = dict(planned_shopify)
    return make_label(item)


def main():
    items = [
        {
            "name": "Blue Emperor Tetra",
            "retail_price": "8.00",
            "bulk_price": None,
            "bulk_min_quantity": None,
            "arrival_date": "2026-09-09",
            "received_quantity": 30,
        },
        {
            "name": "Cardinal Tetra",
            "retail_price": "7.00",
            "bulk_price": "6.00",
            "bulk_min_quantity": 10,
            "arrival_date": "2026-09-09",
            "received_quantity": 40,
        },
    ]
    expected = [
        "Blue Emperor Tetra | $8ea\n090926 | Q30",
        "Cardinal Tetra | $7ea | $6ea/10+\n090926 | Q40",
    ]
    labels = [simulate_intake(item) for item in items]
    assert labels == expected, labels
    for item in items:
        assert item["dry_run_shopify_state"]["custom.arrival_date"] == item["arrival_date"]
        assert item["dry_run_shopify_state"]["inventory.available"] == item["received_quantity"]
    print("DRY_RUN_PASS: 2 livestock items; no Shopify writes or print operations")
    for label in labels:
        print(label)


if __name__ == "__main__":
    main()
