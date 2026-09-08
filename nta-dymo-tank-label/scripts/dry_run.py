#!/usr/bin/env python3
"""Offline regression fixture for the NTA DYMO tank-label contract.

No Shopify client, credentials, network calls, print operation, or model call.
"""

from label_formatter import render_label


def main():
    ready_cases = [
        (
            {
                "product_name": "Blue Emperor Tetra",
                "retail_price": "8.00",
                "bulk_price": None,
                "bulk_min_quantity": None,
                "shopify_arrival_date": "2026-09-09",
                "quantity": 30,
                "source": "dry_run_proposed_shopify_state",
            },
            "Blue Emperor Tetra | $8ea\n090926 | Q30",
        ),
        (
            {
                "product_name": "Cardinal Tetra",
                "retail_price": "7.00",
                "bulk_price": "6.00",
                "bulk_min_quantity": 10,
                "shopify_arrival_date": "2026-09-09",
                "quantity": 40,
                "source": "dry_run_proposed_shopify_state",
            },
            "Cardinal Tetra | $7ea | $6ea/10+\n090926 | Q40",
        ),
    ]

    for payload, expected in ready_cases:
        result = render_label(payload)
        assert result["status"] == "READY", result
        assert result["text"] == expected, result
        assert result["warnings"] == [], result

    invalid_bulk = render_label(
        {
            "product_name": "Cardinal Tetra",
            "retail_price": "7.00",
            "bulk_price": "8.00",
            "bulk_min_quantity": 10,
            "shopify_arrival_date": "2026-09-09",
            "quantity": 40,
            "source": "dry_run_proposed_shopify_state",
        }
    )
    assert invalid_bulk["status"] == "READY", invalid_bulk
    assert invalid_bulk["text"] == "Cardinal Tetra | $7ea\n090926 | Q40"
    assert invalid_bulk["warnings"], invalid_bulk

    bad_date = render_label(
        {
            "product_name": "Blue Emperor Tetra",
            "retail_price": "8.00",
            "bulk_price": None,
            "bulk_min_quantity": None,
            "shopify_arrival_date": "09/09/2026",
            "quantity": 30,
            "source": "dry_run_proposed_shopify_state",
        }
    )
    assert bad_date["status"] == "REVIEW_REQUIRED", bad_date
    assert "shopify_arrival_date" in bad_date["missing_or_invalid_fields"]

    print(
        "DRY_RUN_PASS: deterministic formatter; 2 ready cases, "
        "bulk-warning case, invalid-date case; no Shopify writes, "
        "print operations, or model calls"
    )
    for payload, _ in ready_cases:
        print(render_label(payload)["text"])


if __name__ == "__main__":
    main()
