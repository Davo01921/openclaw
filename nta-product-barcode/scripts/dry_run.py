from barcode_policy import collision_status, plan_barcode, verification_status


def expect(condition, message):
    if not condition:
        raise AssertionError(message)


missing = plan_barcode(
    {
        "variant_id": "gid://shopify/ProductVariant/123456789",
        "legacy_resource_id": 123456789,
        "current_shopify_barcode": None,
    }
)
expect(missing["status"] == "READY", "missing barcode should be plannable")
expect(missing["action"] == "CREATE_INTERNAL", "missing barcode should create internal barcode")
expect(missing["barcode"] == "NTA-V-123456789", "deterministic barcode mismatch")
expect(missing["requires_shopify_write"] is True, "new barcode must require Shopify write")

existing = plan_barcode(
    {
        "variant_id": "gid://shopify/ProductVariant/123456789",
        "legacy_resource_id": 123456789,
        "current_shopify_barcode": "SUPPLIER-ABC-123",
    }
)
expect(existing["action"] == "KEEP_EXISTING", "existing barcode must be preserved")
expect(existing["barcode"] == "SUPPLIER-ABC-123", "existing barcode changed unexpectedly")
expect(existing["requires_shopify_write"] is False, "existing barcode must not trigger write")

blank = plan_barcode(
    {
        "variant_id": "gid://shopify/ProductVariant/123456789",
        "current_shopify_barcode": "   ",
    }
)
expect(blank["barcode"] == "NTA-V-123456789", "blank barcode should use deterministic fallback")

missing_evidence = plan_barcode(
    {
        "variant_id": "gid://shopify/ProductVariant/123456789",
    }
)
expect(missing_evidence["status"] == "REVIEW_REQUIRED", "missing live barcode evidence must review")

collision = collision_status(
    candidate_barcode="NTA-V-123456789",
    target_variant_id="gid://shopify/ProductVariant/123456789",
    matching_variant_ids=["gid://shopify/ProductVariant/999999999"],
)
expect(collision["status"] == "REVIEW_REQUIRED", "foreign collision must block")

same_variant = collision_status(
    candidate_barcode="NTA-V-123456789",
    target_variant_id="gid://shopify/ProductVariant/123456789",
    matching_variant_ids=["gid://shopify/ProductVariant/123456789"],
)
expect(same_variant["status"] == "READY", "same-variant match should not be a collision")

verified = verification_status(
    expected_barcode="NTA-V-123456789",
    live_barcode="NTA-V-123456789",
)
expect(verified["status"] == "VERIFIED", "matching read-back must verify")

mismatch = verification_status(
    expected_barcode="NTA-V-123456789",
    live_barcode="OTHER",
)
expect(mismatch["status"] == "FAILED", "mismatched read-back must fail")

print("DRY_RUN_PASS: existing barcode preserved; missing barcode deterministically proposed; missing evidence, collision, and read-back mismatch fail safely; no network calls, Shopify writes, model calls, or printing")
