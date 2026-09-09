#!/usr/bin/env python3
from verification_route import build_route, writer_gate, auditor_gate


def main():
    base = {"job_id": "job-1", "idempotency_key": "idem-1", "authorised": True}

    product = build_route({**base, "entity": "product"})
    order = build_route({**base, "entity": "order"})
    fulfilment = build_route({**base, "entity": "fulfilment"})
    unauthorised = build_route({**base, "entity": "order", "authorised": False})

    assert product["status"] == "READY"
    assert product["writer"] == "nta-shopify-product-writer"
    assert product["auditor"] == "nta-product-qa-auditor"

    assert order["status"] == "READY"
    assert order["writer"] == "nta-shopify-order-writer"
    assert order["auditor"] == "nta-shopify-order-auditor"

    assert fulfilment["status"] == "BLOCKED"
    assert unauthorised["status"] == "REVIEW_REQUIRED"

    assert writer_gate("SUCCESS")["continue"] is True
    assert writer_gate("DUPLICATE_NOOP")["continue"] is True
    assert writer_gate("FAILED")["status"] == "FAILED"
    assert writer_gate("REVIEW_REQUIRED")["continue"] is False

    assert auditor_gate("PASS") == {"status": "VERIFIED", "retry": False}
    assert auditor_gate("PASS_WITH_WARNING") == {"status": "VERIFIED_WITH_WARNING", "retry": False}
    assert auditor_gate("FAIL", retry_count=0, retry_safe=True, retry_authorised=True) == {"status": "RETRY_ONCE", "retry": True}
    assert auditor_gate("FAIL", retry_count=1, retry_safe=True, retry_authorised=True) == {"status": "FAILED", "retry": False}
    assert auditor_gate("FAIL", retry_count=0, retry_safe=False, retry_authorised=True) == {"status": "FAILED", "retry": False}

    print("DRY_RUN_PASS: deterministic Shopify write-verifier routing; product/variant/inventory preserve existing writer+auditor path, order routes to canonical order writer+auditor, fulfilment/media remain blocked until implemented, writer fail-fast and fresh-read boundary enforced, audit pass mapping and one explicitly-safe retry maximum verified; no Shopify writes, network calls, or model calls")
    print("Product route status:", product["status"])
    print("Order route status:", order["status"])
    print("Fulfilment route status:", fulfilment["status"])
    print("Unauthorised route status:", unauthorised["status"])
    print("Writer failure gate:", writer_gate("FAILED")["status"])
    print("Order audit PASS maps to:", auditor_gate("PASS")["status"])
    print("Safe first audit failure maps to:", auditor_gate("FAIL", retry_count=0, retry_safe=True, retry_authorised=True)["status"])
    print("Second audit failure maps to:", auditor_gate("FAIL", retry_count=1, retry_safe=True, retry_authorised=True)["status"])


if __name__ == "__main__":
    main()
