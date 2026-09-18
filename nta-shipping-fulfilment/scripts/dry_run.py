#!/usr/bin/env python3
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from shipping_fulfilment import build_verifier_request, idempotency_key

base = {
    "job_id": "ship-event-1", "authorised": True, "order_id": "gid://shopify/Order/1",
    "carrier": "Australia Post", "tracking_number": "ABC123",
    "shipped_at": "2026-09-18T14:00:00+10:00", "notify_customer": False,
    "fulfilment_orders": [{"fulfilment_order_id": "gid://shopify/FulfillmentOrder/2",
        "line_items": [{"fulfilment_order_line_item_id": "gid://shopify/FulfillmentOrderLineItem/3", "quantity": 2}]}],
}
r = build_verifier_request(base)
assert r["status"] == "READY"
assert r["write_request"]["entity"] == "fulfilment"
assert r["write_request"]["idempotency_key"] == idempotency_key(base)
assert build_verifier_request({**base, "authorised": False})["status"] == "REVIEW_REQUIRED"
assert build_verifier_request({**base, "tracking_number": None})["status"] == "REVIEW_REQUIRED"
bad = {**base, "fulfilment_orders": [{"fulfilment_order_id": "x", "line_items": [{"fulfilment_order_line_item_id": "y", "quantity": 0}]}]}
assert build_verifier_request(bad)["status"] == "REVIEW_REQUIRED"
reordered = {**base, "fulfilment_orders": [{"fulfilment_order_id": "gid://shopify/FulfillmentOrder/2",
    "line_items": [{"fulfilment_order_line_item_id": "gid://shopify/FulfillmentOrderLineItem/3", "quantity": 2}]}]}
assert idempotency_key(base) == idempotency_key(reordered)
print("nta-shipping-fulfilment dry run: PASS")
