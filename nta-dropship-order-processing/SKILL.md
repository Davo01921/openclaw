---
name: "nta-dropship-order-processing"
version: "1.0"
description: "Safely coordinate NTA qualifying dropship orders without inventing supplier API behaviour or duplicate supplier orders."
---

# NTA Dropship Order Processing

## Scope

Process a Shopify order only when its authorised dropship marker and qualifying vendor are present. This workflow owns order detection, supplier hand-off evidence, and order-level idempotency. It does not own pricing or product rules.

## Procedure

1. Read the live Shopify order, line items, dropship marker, vendor and current fulfilment state.
2. For every eligible line, resolve the exact sellable variant with `nta-product-resolver` and verify supplier SKU/order unit mapping. Ambiguous lines require review.
3. Build an idempotency record from Shopify order ID, line IDs, vendor and supplier reference. Never create or resend a supplier order when a matching successful hand-off exists.
4. Use the configured supplier adapter only when it is available and the supplier payload is fully resolved. This repository does not invent supplier API endpoints, credentials, or acceptance semantics.
5. Record the supplier reference back to Shopify only through `nta-shopify-write-verifier`, preserving unrelated order and fulfilment state.
6. Report supplier hand-off state separately from customer fulfilment. A supplier submission is not fulfilment confirmation.

## Statuses

`READY_FOR_HANDOFF`, `SENT_TO_SUPPLIER`, `SUPPLIER_ACKNOWLEDGED`, `REVIEW_REQUIRED`, `BLOCKED`, or `NO_ELIGIBLE_LINES`.

If no supplier adapter is configured, return `READY_FOR_HANDOFF` with a validated payload and no external write.
