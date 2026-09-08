from order_audit import audit_order


def expect(condition, message):
    if not condition:
        raise AssertionError(message)


request = {
    "job_id": "job-1",
    "order_id": "gid://shopify/Order/1001",
    "read_adapter_capability_verified": True,
    "expected": {
        "customer_id": "gid://shopify/Customer/2001",
        "line_items": [
            {"variant_id": "gid://shopify/ProductVariant/3001", "quantity": 2},
            {"variant_id": "gid://shopify/ProductVariant/3002", "quantity": 1},
        ],
        "discount_code": "Ntalosses",
        "total_aud": "0.00",
        "financial_status": "PAID",
        "zero_balance": True,
        "tags": ["NTA Loss", "Death"],
        "tags_mode": "SUBSET",
        "note": "synthetic loss order",
    },
}

fresh = {
    "order_id": "gid://shopify/Order/1001",
    "customer_id": "gid://shopify/Customer/2001",
    "line_items": [
        {"variant_id": "gid://shopify/ProductVariant/3001", "quantity": 2},
        {"variant_id": "gid://shopify/ProductVariant/3002", "quantity": 1},
    ],
    "discount_code": "Ntalosses",
    "total_aud": "0.00",
    "outstanding_aud": "0.00",
    "financial_status": "PAID",
    "tags": ["NTA Loss", "Death", "Tank 13"],
    "note": "synthetic loss order",
}

r = audit_order(request, fresh)
expect(r["final_status"] == "PASS", "exact authorised expectations should pass")

r = audit_order({**request, "read_adapter_capability_verified": False}, fresh)
expect(r["final_status"] == "REVIEW_REQUIRED", "missing read capability must review")

r = audit_order({**request, "order_id": None}, fresh)
expect(r["final_status"] == "REVIEW_REQUIRED", "missing exact order ID must review")

r = audit_order(request, None)
expect(r["final_status"] == "REVIEW_REQUIRED", "missing fresh snapshot must review")

bad_lines = {**fresh, "line_items": [{"variant_id": "gid://shopify/ProductVariant/3001", "quantity": 1}]}
r = audit_order(request, bad_lines)
expect(r["final_status"] == "FAIL", "missing/quantity-mismatched lines must fail")

extra_lines = {**fresh, "line_items": fresh["line_items"] + [{"variant_id": "gid://shopify/ProductVariant/3999", "quantity": 1}]}
r = audit_order(request, extra_lines)
expect(r["final_status"] == "FAIL", "unexpected line must fail exact line comparison")

bad_note = {**fresh, "note": "different note"}
r = audit_order(request, bad_note)
expect(r["final_status"] == "FAIL", "note mismatch must fail")

bad_financial = {**fresh, "total_aud": "2.00", "outstanding_aud": "2.00", "financial_status": "PENDING"}
r = audit_order(request, bad_financial)
expect(r["final_status"] == "FAIL", "financial/total mismatch must fail")

exact_tags_request = {
    **request,
    "expected": {**request["expected"], "tags_mode": "EXACT"},
}
r = audit_order(exact_tags_request, fresh)
expect(r["final_status"] == "FAIL", "EXACT tags must fail when extra live tags exist")

subset_tags_request = {
    **request,
    "expected": {**request["expected"], "tags_mode": "SUBSET"},
}
r = audit_order(subset_tags_request, fresh)
expect(r["final_status"] == "PASS", "SUBSET tags should permit unrelated extra tags")

contaminated_writer_response = {
    "status": "SUCCESS",
    "order_id": request["order_id"],
    "customer_id": request["expected"]["customer_id"],
}
r = audit_order(request, contaminated_writer_response)
expect(r["final_status"] != "PASS", "writer response must not be accepted as fresh complete order proof")

print("DRY_RUN_PASS: deterministic Shopify order auditing; exact order identity, fresh-read capability, exact line-item comparison, customer/discount/total/financial/zero-balance/tag/note verification, mismatch failure, subset-vs-exact tag semantics, and writer-response contamination rejection; no Shopify writes, network calls, or model calls")
print("Exact match status:", audit_order(request, fresh)["final_status"])
print("Missing adapter status:", audit_order({**request, "read_adapter_capability_verified": False}, fresh)["final_status"])
print("Missing order ID status:", audit_order({**request, "order_id": None}, fresh)["final_status"])
print("Line mismatch status:", audit_order(request, bad_lines)["final_status"])
print("Financial mismatch status:", audit_order(request, bad_financial)["final_status"])
print("Exact-tag mismatch status:", audit_order(exact_tags_request, fresh)["final_status"])
print("Subset-tag status:", audit_order(subset_tags_request, fresh)["final_status"])
