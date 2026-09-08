from loss_plan import build_loss_plan


def expect(condition, message):
    if not condition:
        raise AssertionError(message)


base_item = {
    "resolution_status": "RESOLVED",
    "shopify_variant_id": "gid://shopify/ProductVariant/111",
    "quantity": 2,
    "fish": "Synthetic Guppy",
    "tank": "13",
    "cause": None,
    "identification_confidence": "HIGH",
    "evidence": ["synthetic exact variant fixture"],
}

base = {
    "mode": "dry_run",
    "source_event_id": "discord:123456789",
    "loss_items": [base_item],
    "prior_loss_order_found": False,
    "prior_manual_deduction_found": False,
    "manual_reversal_verified": False,
}

r = build_loss_plan(base)
expect(r["status"] == "READY", "resolved dry run should be READY")
expect(r["write_ready"] is False, "dry run must never be write ready")
expect(r["order_plan"]["customer"] == "NTA Losses", "customer constant incorrect")
expect(r["order_plan"]["discount_code"] == "Ntalosses", "discount constant incorrect")
expect(r["order_plan"]["target_total_aud"] == "0.00", "target total incorrect")
expect("NTA Loss" in r["order_plan"]["tags"] and "Death" in r["order_plan"]["tags"], "base tags missing")
expect("Tank 13" in r["order_plan"]["tags"], "tank tag missing")
expect(r["order_plan"]["expected_net_loss_by_variant"][base_item["shopify_variant_id"]] == 2, "net loss incorrect")

r = build_loss_plan({**base, "prior_loss_order_found": True})
expect(r["status"] == "DUPLICATE_NOOP", "duplicate must be a no-op")
expect(r["order_plan"] is None, "duplicate must not produce executable order plan")

bad_item = {**base_item, "resolution_status": "REVIEW_REQUIRED"}
r = build_loss_plan({**base, "loss_items": [bad_item]})
expect(r["status"] == "REVIEW_REQUIRED", "unresolved identity must review")

bad_qty = {**base_item, "quantity": 0}
r = build_loss_plan({**base, "loss_items": [bad_qty]})
expect(r["status"] == "REVIEW_REQUIRED", "non-positive quantity must review")

write_base = {
    **base,
    "mode": "write",
    "customer_verified": True,
    "discount_zero_verified": True,
    "location_verified": True,
    "order_write_capability_verified": True,
    "fulfilment_write_capability_verified": True,
}
r = build_loss_plan(write_base)
expect(r["status"] == "READY" and r["write_ready"] is True, "fully verified write preflight should be READY")

r = build_loss_plan({**write_base, "discount_zero_verified": False})
expect(r["status"] == "REVIEW_REQUIRED", "non-zero/unverified discount must block write")
expect(r["write_ready"] is False, "blocked write must not be write ready")

r = build_loss_plan({**write_base, "order_write_capability_verified": False})
expect(r["status"] == "REVIEW_REQUIRED", "unverified order write capability must block write")

r = build_loss_plan({
    **write_base,
    "prior_manual_deduction_found": True,
    "manual_reversal_verified": False,
})
expect(r["status"] == "REVIEW_REQUIRED", "prior manual deduction without verified reversal must block")

r = build_loss_plan({
    **write_base,
    "loss_items": [
        base_item,
        {
            **base_item,
            "shopify_variant_id": "gid://shopify/ProductVariant/222",
            "quantity": 3,
            "tank": "14",
        },
    ],
})
expect(r["status"] == "READY", "multi-line write preflight should be READY")
expect(len(r["order_plan"]["line_items"]) == 2, "multi-line plan missing items")
expect("Tank 13" in r["order_plan"]["tags"] and "Tank 14" in r["order_plan"]["tags"], "multi-tank tags missing")

print("DRY_RUN_PASS: deterministic death-loss order planning; canonical customer/discount/tags, positive quantity and resolved-variant gates, duplicate no-op, write-capability and zero-total gates, manual-deduction reversal gate, multi-line planning; no Shopify writes, network calls, or model calls")
print("Resolved dry-run status:", build_loss_plan(base)["status"])
print("Duplicate status:", build_loss_plan({**base, "prior_loss_order_found": True})["status"])
print("Unresolved variant status:", build_loss_plan({**base, "loss_items": [bad_item]})["status"])
print("Write preflight status:", build_loss_plan(write_base)["status"])
print("Unverified order-writer status:", build_loss_plan({**write_base, "order_write_capability_verified": False})["status"])
print("Manual deduction without reversal status:", build_loss_plan({**write_base, "prior_manual_deduction_found": True, "manual_reversal_verified": False})["status"])
