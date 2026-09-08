from route_plan import build_route


def expect(condition, message):
    if not condition:
        raise AssertionError(message)


base = {
    "job_state": "RECEIVED",
    "mode": "dry_run",
    "supplier_cost_supplied": True,
    "price_review_required": False,
    "label_requested": False,
}

r = build_route(base)
expect(r["status"] == "READY", "received dry run should be READY")
expect("nta-supplier-unit-cost-normalizer" in r["route"], "cost normalizer missing")
expect("nta-retail-pricing-standard" not in r["route"], "pricing should be skipped")
expect("nta-shopify-write-verifier" not in r["route"], "dry run must not route to writer/verifier")

r = build_route({**base, "mode": "write", "price_review_required": True, "label_requested": True})
expect(r["status"] == "READY", "write route should be READY")
expect("nta-retail-pricing-standard" in r["route"], "pricing missing")
expect(r["route"][-2:] == ["nta-shopify-write-verifier", "nta-dymo-tank-label"], "write verification must precede label")

r = build_route({**base, "supplier_cost_supplied": False})
expect("nta-supplier-unit-cost-normalizer" not in r["route"], "cost normalizer should be skipped")

r = build_route({**base, "job_state": "ORDERED"})
expect(r["status"] == "REVIEW_REQUIRED", "ORDERED must not run receipt workflow")
expect(r["redirect"] == "nta-supplier-order-processing", "ORDERED redirect missing")
expect("nta-inventory-state" not in r["route"], "ORDERED must not route to inventory state here")

r = build_route({**base, "job_state": "UNKNOWN"})
expect(r["status"] == "REVIEW_REQUIRED", "invalid job state must review")

r = build_route({**base, "label_requested": "yes"})
expect(r["status"] == "REVIEW_REQUIRED", "non-boolean route flags must review")

print("DRY_RUN_PASS: deterministic inventory-update routing; received/write/dry-run, optional cost/pricing, ORDERED redirect, invalid-state gate, label-after-verification ordering; no Shopify writes, network calls, or model calls")
print("Received dry-run route:", " -> ".join(build_route(base)["route"]))
print("Write+label final steps:", " -> ".join(build_route({**base, "mode": "write", "price_review_required": True, "label_requested": True})["route"][-3:]))
print("ORDERED status:", build_route({**base, "job_state": "ORDERED"})["status"])
print("ORDERED redirect:", build_route({**base, "job_state": "ORDERED"})["redirect"])
print("Invalid state status:", build_route({**base, "job_state": "UNKNOWN"})["status"])
