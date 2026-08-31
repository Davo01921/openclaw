---
name: "nta-shipping-fulfilment"
version: "1.0"
description: "Safely synchronise authorised NTA shipment and fulfilment events while preserving order and inventory integrity."
---

# NTA Shipping Fulfilment

## Scope

Translate a verified shipment event into authorised Shopify fulfilment updates. This workflow does not select carriers, buy labels, create ShipStation/API credentials, or infer tracking details.

## Procedure

1. Read the exact Shopify order and fulfilment state.
2. Validate order ID, fulfilment-line IDs, quantities, carrier, tracking number and shipment timestamp against the source event.
3. Deduplicate using carrier/tracking plus order/fulfilment-line identifiers. A repeated webhook/event must be a no-op.
4. Submit only the authorised fulfilment state through `nta-shopify-write-verifier` and read it back fresh.
5. Return `VERIFIED`, `DUPLICATE_NOOP`, `REVIEW_REQUIRED`, `PARTIAL`, or `FAILED` with per-line evidence.

## Safeguards

- Never fulfil an unverified or ambiguous line.
- Never use shipping state to adjust inventory; Shopify fulfilment/order policy owns that effect.
- Never send customer notifications unless the calling integration explicitly authorises them.
- Supplier dropship acknowledgement is not proof of dispatch; wait for a verified shipment event.
