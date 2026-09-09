#!/usr/bin/env python3
from fulfilment_effect import derive_fulfilled_lines


def main():
    before = {
        "source": "FRESH_SHOPIFY_READ",
        "order_id": "gid://shopify/Order/1",
        "fulfilment_order_id": "gid://shopify/FulfillmentOrder/10",
        "shopify_status": "OPEN",
        "line_items": [
            {"fulfilment_order_line_item_id": "line-1", "remaining_quantity": 5},
            {"fulfilment_order_line_item_id": "line-2", "remaining_quantity": 2},
        ],
    }
    after = {
        "source": "FRESH_SHOPIFY_READ",
        "order_id": "gid://shopify/Order/1",
        "fulfilment_order_id": "gid://shopify/FulfillmentOrder/10",
        "shopify_status": "OPEN",
        "line_items": [
            {"fulfilment_order_line_item_id": "line-1", "remaining_quantity": 3},
            {"fulfilment_order_line_item_id": "line-2", "remaining_quantity": 2},
        ],
    }
    result = derive_fulfilled_lines(before, after)
    assert result["status"] == "SUCCESS"
    assert result["actual"]["fulfilled_lines"] == [{"fulfilment_order_line_item_id": "line-1", "quantity": 2}]

    increased = derive_fulfilled_lines(before, {**after, "line_items": [
        {"fulfilment_order_line_item_id": "line-1", "remaining_quantity": 6},
        {"fulfilment_order_line_item_id": "line-2", "remaining_quantity": 2},
    ]})
    assert increased["status"] == "FAIL"

    stale = derive_fulfilled_lines({**before, "source": "WRITER_RESPONSE"}, after)
    assert stale["status"] == "REVIEW_REQUIRED"

    print("DRY_RUN_PASS: fresh FulfillmentOrder before/after effect derivation; exact fulfilled quantity derived from remainingQuantity delta, increased remaining quantity rejected, stale/writer-derived evidence rejected; no Shopify writes, network calls, inventory changes, or model calls")
    print("Derived status:", result["status"])
    print("Increase anomaly status:", increased["status"])
    print("Stale evidence status:", stale["status"])


if __name__ == "__main__":
    main()
