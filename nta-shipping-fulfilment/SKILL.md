---
name: "nta-shipping-fulfilment"
version: "2.0"
description: "Deterministically validate, deduplicate and route authorised NTA shipment events into the canonical Shopify fulfilment write/verify boundary."
---

# NTA Shipping Fulfilment — v2.0

## Purpose
Convert a verified structured shipment event into an exact fulfilment request. Normal execution uses Python, not model judgement.

Core principle: **Python validates. The verifier routes. The fulfilment writer writes. The auditor verifies. AI handles exceptions only.**

## Required input
```yaml
job_id: <stable source-event id>
authorised: true
order_id: <exact Shopify order id>
carrier: <explicit carrier or null>
tracking_number: <explicit tracking number or null>
shipped_at: <ISO-8601 timestamp>
notify_customer: false
fulfilment_orders:
  - fulfilment_order_id: <exact id>
    line_items:
      - fulfilment_order_line_item_id: <exact id>
        quantity: <positive integer>
```

## Procedure
1. Run `scripts/shipping_fulfilment.py` against the structured event.
2. Reject missing/ambiguous identities, invalid quantities/timestamps, invented tracking, or absent authorisation as `REVIEW_REQUIRED`.
3. Generate a stable SHA-256 idempotency key from the canonical shipment identity.
4. If the key is already recorded as completed, return `DUPLICATE_NOOP`.
5. Build the exact `entity: fulfilment` request for `nta-shopify-write-verifier`.
6. The verifier must route only to `nta-shopify-fulfilment-writer`, followed by a fresh Shopify read and `nta-shopify-fulfilment-auditor`.
7. Record the idempotency key as completed only after the canonical boundary returns `VERIFIED` or `VERIFIED_WITH_WARNING`.

## Result states
- `READY` — deterministic validation passed; request is ready for the canonical verifier.
- `DUPLICATE_NOOP` — the exact completed shipment identity was already processed.
- `REVIEW_REQUIRED` — input is incomplete, ambiguous or unsafe to execute.
- `VERIFIED` / `VERIFIED_WITH_WARNING` — returned only by the canonical write/verify boundary.
- `FAILED` / `BLOCKED` — canonical mutation or verification did not safely complete.

Do not use `PARTIAL` for fulfilment mismatches.

## Safeguards
- Never infer order, fulfilment-order, line-item, quantity, carrier or tracking values.
- Never perform a separate inventory adjustment.
- Never notify the customer unless explicitly authorised.
- Never treat supplier acknowledgement as proof of dispatch.
- Never bypass `nta-shopify-write-verifier`.
- AI may investigate `REVIEW_REQUIRED`; it must not convert ambiguity into a write.

Run `python3 scripts/dry_run.py` for zero-network regression coverage.
