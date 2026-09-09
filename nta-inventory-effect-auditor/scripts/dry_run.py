from inventory_effect_audit import audit_inventory_effect


def expect(condition, message):
    if not condition:
        raise AssertionError(message)


level = "gid://shopify/InventoryLevel/500"
expected = {level: 2}
before = {level: {"source": "FRESH_SHOPIFY_READ", "available": 10, "on_hand": 10}}
after = {level: {"source": "FRESH_SHOPIFY_READ", "available": 8, "on_hand": 8}}

r = audit_inventory_effect(expected, before, after)
expect(r["status"] == "PASS", "exact one-time loss delta should pass")
expect(r["evidence"][level]["actual_loss"] == 2, "actual loss calculation incorrect")
expect(audit_inventory_effect(expected, before, {level: {"source": "FRESH_SHOPIFY_READ", "available": 6, "on_hand": 6}})["status"] == "FAIL", "double loss must fail")
expect(audit_inventory_effect(expected, before, {level: {"source": "FRESH_SHOPIFY_READ", "available": 9, "on_hand": 9}})["status"] == "FAIL", "partial loss must fail")
expect(audit_inventory_effect(expected, before, {level: {"source": "WRITER_RESPONSE", "available": 8, "on_hand": 8}})["status"] == "FAIL", "non-fresh evidence must fail")

print("DRY_RUN_PASS: deterministic inventory-effect audit; fresh before/after gates and exact one-time available-stock delta verified, double/partial deductions rejected; no Shopify writes, network calls, inventory changes, or model calls")
print("Exact loss status:", audit_inventory_effect(expected, before, after)["status"])
print("Double loss status:", audit_inventory_effect(expected, before, {level: {"source": "FRESH_SHOPIFY_READ", "available": 6, "on_hand": 6}})["status"])
