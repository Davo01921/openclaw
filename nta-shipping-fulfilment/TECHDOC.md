# TECHDOC — NTA Shipping Fulfilment v2

## Components
- `scripts/shipping_fulfilment.py`: schema/safety validation, canonicalisation, SHA-256 idempotency key and verifier-request builder.
- `scripts/dry_run.py`: zero-network regression checks.
- `nta-shopify-write-verifier`: canonical entity routing and verification gates.
- `nta-shopify-fulfilment-writer`: guarded Shopify GraphQL mutation transport.
- `nta-shopify-fulfilment-auditor`: fresh-read deterministic audit.

## Idempotency
The key hashes order ID, carrier, tracking number and sorted fulfilment-order/line identities with quantities. `job_id` and `shipped_at` are deliberately excluded so replayed source events with a new delivery ID still collapse to the same shipment identity.

## Persistence boundary
Use `scripts/shipment_ledger.py` on a persistent private path. Atomic SQLite claims record INDETERMINATE before mutation; only an independent PASS receipt marks VERIFIED. `scripts/shipment_boundary.py` composes the verifier handoff, existing writer and independent reader callbacks. Keep indeterminate intents across crashes and code rollback; reconcile before any retry. Do not substitute an in-memory set.

## Security
No credentials are accepted or printed by this skill. Shopify credentials remain owned by the canonical fulfilment writer adapter. No browser fallback is permitted.

## Tracking and handoff

`verification_route.fulfilment_handoff` checks fresh order identity, open fulfillment orders and exact remaining quantities before constructing the writer input. Carrier/number are a paired, source-verified `tracking_info` object. The API maps this to `FulfillmentInput.trackingInfo`; independent audit checks it and successful state.

`run_shipment.py` is the concrete CLI integration: exact existing bridge read, writer capability gate, durable intent, exact created-fulfillment/remaining-line effect normalization and stored independent readback. Its default preflight does not create a ledger or mutate Shopify.
