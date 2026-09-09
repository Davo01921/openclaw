from shopify_order_api import build_create_payload, probe_capabilities


def expect(condition, message):
    if not condition:
        raise AssertionError(message)


base_plan = {
    "intent": "CREATE_ORDER",
    "order": {
        "customer_id": "gid://shopify/Customer/100",
        "line_items": [{"variant_id": "gid://shopify/ProductVariant/200", "quantity": 2}],
        "tags": ["NTA Loss", "Death"],
        "note": "synthetic regression fixture",
        "discount": {"code": None},
        "financial_target": "PAID",
        "create_options": {
            "inventory_behaviour": "DECREMENT_OBEYING_POLICY",
            "send_receipt": False,
            "send_fulfillment_receipt": False,
        },
    },
}

r = build_create_payload(base_plan)
expect(r["status"] == "READY", "supported create payload should be READY")
expect(r["variables"]["options"]["inventoryBehaviour"] == "DECREMENT_OBEYING_POLICY", "inventory behaviour changed")
expect(r["variables"]["options"]["sendReceipt"] is False, "receipt default changed")
expect(r["variables"]["order"]["customer"]["toAssociate"]["id"] == "gid://shopify/Customer/100", "customer mapping changed")

no_options = {**base_plan, "order": {k: v for k, v in base_plan["order"].items() if k != "create_options"}}
r2 = build_create_payload(no_options)
expect(r2["status"] == "REVIEW_REQUIRED", "missing create options must block")

bad_inventory = {
    **base_plan,
    "order": {**base_plan["order"], "create_options": {**base_plan["order"]["create_options"], "inventory_behaviour": "UNKNOWN"}},
}
r3 = build_create_payload(bad_inventory)
expect(r3["status"] == "REVIEW_REQUIRED", "unknown inventory behaviour must block")

with_code_only = {**base_plan, "order": {**base_plan["order"], "discount": {"code": "Ntalosses"}}}
r4 = build_create_payload(with_code_only)
expect(r4["status"] == "REVIEW_REQUIRED", "discount code without explicit definition must block")
expect("order.discount:definition_required" in r4["errors"], "discount-definition blocker missing")

unsupported_financial = {**base_plan, "order": {**base_plan["order"], "financial_target": "PAID_OR_ZERO_BALANCE_VERIFIED"}}
r5 = build_create_payload(unsupported_financial)
expect(r5["status"] == "REVIEW_REQUIRED", "non-API financial target must block")

probe = probe_capabilities(live=False)
expect(probe["order_read_adapter_verified"] is False, "offline dry-run must not claim read capability")
expect(probe["order_create_adapter_verified"] is False, "offline dry-run must not claim write capability")

print("DRY_RUN_PASS: concrete Shopify order API adapter payload mapping; explicit inventory behaviour, receipt flags, exact customer/variant mapping, unsupported discount-definition and financial-target blocking, and no false live-capability claims; no Shopify access, network calls, order writes, inventory changes, or model calls")
print("Supported create payload status:", build_create_payload(base_plan)["status"])
print("Missing create-options status:", build_create_payload(no_options)["status"])
print("Unknown inventory behaviour status:", build_create_payload(bad_inventory)["status"])
print("Code-only discount status:", build_create_payload(with_code_only)["status"])
print("Unsupported financial target status:", build_create_payload(unsupported_financial)["status"])
print("Offline read capability verified:", probe["order_read_adapter_verified"])
print("Offline create capability verified:", probe["order_create_adapter_verified"])
