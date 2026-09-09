from fulfilment_write_plan import build_fulfilment_write_plan


def expect(condition, message):
    if not condition:
        raise AssertionError(message)


base = {
    "job_id": "loss:synthetic-001",
    "idempotency_key": "nta-loss:abc123:fulfilment",
    "authorised": True,
    "order_id": "gid://shopify/Order/100",
    "notify_customer": False,
    "fulfilment_orders": [
        {
            "fulfilment_order_id": "gid://shopify/FulfillmentOrder/200",
            "line_items": [
                {"fulfilment_order_line_item_id": "gid://shopify/FulfillmentOrderLineItem/300", "quantity": 2}
            ],
        }
    ],
    "duplicate_completed": False,
    "prior_result_indeterminate": False,
    "retry_authorised": False,
    "adapter_capability_verified": True,
}

r = build_fulfilment_write_plan(base)
expect(r["status"] == "READY" and r["write_ready"] is True, "valid fulfilment should be READY")
expect(r["write_plan"]["notify_customer"] is False, "death-loss fulfilment must not notify customer")
expect(r["write_plan"]["tracking_info"] is None, "death-loss fulfilment must not invent tracking")

expect(build_fulfilment_write_plan({**base, "duplicate_completed": True})["status"] == "DUPLICATE_NOOP", "duplicate must be no-op")
expect(build_fulfilment_write_plan({**base, "adapter_capability_verified": False})["status"] == "REVIEW_REQUIRED", "unverified adapter must block")
expect(build_fulfilment_write_plan({**base, "prior_result_indeterminate": True, "retry_authorised": False})["status"] == "REVIEW_REQUIRED", "unsafe retry must block")
expect(build_fulfilment_write_plan({**base, "notify_customer": "false"})["status"] == "REVIEW_REQUIRED", "notify flag must be boolean")

bad = {**base, "fulfilment_orders": [{"fulfilment_order_id": "gid://shopify/FulfillmentOrder/200", "line_items": [{"fulfilment_order_line_item_id": "gid://shopify/FulfillmentOrderLineItem/300", "quantity": 0}]}]}
expect(build_fulfilment_write_plan(bad)["status"] == "REVIEW_REQUIRED", "zero quantity must block")

print("DRY_RUN_PASS: deterministic Shopify fulfilment-writer preflight; exact order/fulfilment IDs, positive quantities, duplicate no-op, idempotent retry gate, adapter-capability gate, notifications disabled, no invented tracking; no Shopify writes, network calls, inventory changes, or model calls")
print("Valid fulfilment status:", build_fulfilment_write_plan(base)["status"])
print("Duplicate status:", build_fulfilment_write_plan({**base, "duplicate_completed": True})["status"])
print("Unverified adapter status:", build_fulfilment_write_plan({**base, "adapter_capability_verified": False})["status"])
