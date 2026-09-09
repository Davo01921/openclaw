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
expect(r["order_plan"]["discount"]["code"] == "Ntalosses", "writer discount code incorrect")
expect(r["order_plan"]["discount"]["type"] == "ITEM_PERCENTAGE", "writer discount type incorrect")
expect(r["order_plan"]["discount"]["percentage"] == "100", "writer discount percentage incorrect")
expect(r["order_plan"]["target_total_aud"] == "0.00", "target total incorrect")
expect(r["order_plan"]["financial_target"] == "PAID", "financial target must be exact API-supported state")
expect(r["order_plan"]["financial_verification"] == "ZERO_BALANCE_VERIFIED", "zero-balance verification target missing")
expect(r["order_plan"]["inventory_behaviour"] == "DECREMENT_OBEYING_POLICY", "inventory behaviour contract incorrect")
expect(r["order_plan"]["expected_order_audit"]["discount_code"] == "Ntalosses", "expected audit discount missing")
expect(r["order_plan"]["expected_order_audit"]["total_aud"] == "0.00", "expected audit total missing")
expect(r["order_plan"]["expected_order_audit"]["zero_balance"] is True, "expected zero-balance audit missing")
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

r = build_loss_plan({**base, "source_event_id": ""})
expect(r["status"] == "REVIEW_REQUIRED", "missing source event id must review")

r = build_loss_plan({
    **base,
    "prior_manual_deduction_found": True,
    "manual_reversal_verified": False,
})
expect(r["status"] == "REVIEW_REQUIRED", "unreconciled manual deduction must block even dry run readiness")

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

print("DRY_RUN_PASS: deterministic death-loss order planning; canonical Ntalosses 100% item-discount writer contract, $0.00/zero-balance audit target, explicit inventory behaviour, canonical customer/tags, stable source-event and positive-quantity gates, resolved-variant gate, duplicate no-op, manual-deduction reconciliation, write-capability gates, multi-line planning; no Shopify writes, network calls, or model calls")
print("Resolved dry-run status:", build_loss_plan(base)["status"])
print("Duplicate status:", build_loss_plan({**base, "prior_loss_order_found": True})["status"])
print("Unresolved variant status:", build_loss_plan({**base, "loss_items": [bad_item]})["status"])
print("Missing source-event status:", build_loss_plan({**base, "source_event_id": ""})["status"])
print("Manual deduction without reversal status:", build_loss_plan({**base, "prior_manual_deduction_found": True, "manual_reversal_verified": False})["status"])
print("Write preflight status:", build_loss_plan(write_base)["status"])
print("Unverified order-writer status:", build_loss_plan({**write_base, "order_write_capability_verified": False})["status"])
