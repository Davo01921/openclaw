from order_write_plan import build_order_write_plan


def expect(condition, message):
    if not condition:
        raise AssertionError(message)


base = {
    "job_id": "loss:synthetic-001",
    "idempotency_key": "nta-loss:abc123",
    "intent": "CREATE_ORDER",
    "target_order_id": None,
    "authorised": True,
    "expected_result": {
        "customer_id": "gid://shopify/Customer/100",
        "line_items": [{"variant_id": "gid://shopify/ProductVariant/200", "quantity": 2}],
        "total": "0.00",
    },
    "order": {
        "customer_id": "gid://shopify/Customer/100",
        "line_items": [{"variant_id": "gid://shopify/ProductVariant/200", "quantity": 2}],
        "tags": ["NTA Loss", "Death", "Tank 13"],
        "note": "synthetic regression fixture",
        "discount": {"code": "Ntalosses"},
        "financial_target": "PAID_OR_ZERO_BALANCE_VERIFIED",
    },
    "protected_fields": [],
    "retry_authorised": False,
    "duplicate_completed": False,
    "prior_result_indeterminate": False,
    "adapter_capability_verified": True,
}

r = build_order_write_plan(base)
expect(r["status"] == "READY" and r["write_ready"] is True, "valid create should be READY")
expect(r["write_plan"]["order"]["line_items"][0]["quantity"] == 2, "quantity changed")

r = build_order_write_plan({**base, "duplicate_completed": True})
expect(r["status"] == "DUPLICATE_NOOP", "duplicate should be no-op")

r = build_order_write_plan({**base, "authorised": False})
expect(r["status"] == "REVIEW_REQUIRED", "unauthorised request must review")

bad_order = {**base["order"], "line_items": [{"variant_id": "gid://shopify/ProductVariant/200", "quantity": 0}]}
r = build_order_write_plan({**base, "order": bad_order})
expect(r["status"] == "REVIEW_REQUIRED", "zero quantity must review")

bad_order = {
    **base["order"],
    "line_items": [
        {"variant_id": "gid://shopify/ProductVariant/200", "quantity": 1},
        {"variant_id": "gid://shopify/ProductVariant/200", "quantity": 1},
    ],
}
r = build_order_write_plan({**base, "order": bad_order})
expect(r["status"] == "REVIEW_REQUIRED", "duplicate variant lines must review")

r = build_order_write_plan({**base, "adapter_capability_verified": False})
expect(r["status"] == "REVIEW_REQUIRED", "unverified live adapter must block")

r = build_order_write_plan({**base, "prior_result_indeterminate": True, "retry_authorised": False})
expect(r["status"] == "REVIEW_REQUIRED", "indeterminate retry must block")

r = build_order_write_plan({**base, "prior_result_indeterminate": True, "retry_authorised": True})
expect(r["status"] == "READY", "authorised retry with same key should pass preflight")

r = build_order_write_plan({**base, "fulfilment": {"status": "FULFILLED"}})
expect(r["status"] == "REVIEW_REQUIRED", "fulfilment instructions must be rejected")

r = build_order_write_plan({**base, "expected_result": {}})
expect(r["status"] == "REVIEW_REQUIRED", "missing expected readback must review")

r = build_order_write_plan({**base, "intent": "UPDATE_ORDER_METADATA", "target_order_id": None})
expect(r["status"] == "REVIEW_REQUIRED", "metadata update requires exact order id")

print("DRY_RUN_PASS: deterministic Shopify order-writer preflight; authorisation, exact customer/variant and positive quantity gates, duplicate no-op, idempotent retry gate, adapter-capability gate, fulfilment rejection, expected-readback requirement, metadata target identity; no Shopify writes, network calls, or model calls")
print("Valid create status:", build_order_write_plan(base)["status"])
print("Duplicate status:", build_order_write_plan({**base, "duplicate_completed": True})["status"])
print("Unverified adapter status:", build_order_write_plan({**base, "adapter_capability_verified": False})["status"])
print("Indeterminate retry status:", build_order_write_plan({**base, "prior_result_indeterminate": True, "retry_authorised": False})["status"])
print("Fulfilment-in-request status:", build_order_write_plan({**base, "fulfilment": {"status": "FULFILLED"}})["status"])
