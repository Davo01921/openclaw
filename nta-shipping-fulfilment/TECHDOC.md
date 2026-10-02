# TECHDOC — NTA Shipping Fulfilment v2

## Components
- `scripts/shipping_fulfilment.py`: schema/safety validation, canonicalisation, SHA-256 idempotency key and verifier-request builder.
- `scripts/dry_run.py`: zero-network regression checks.
- `nta-shopify-write-verifier`: canonical entity routing and verification gates.
- `nta-shopify-fulfilment-writer`: guarded Shopify GraphQL mutation transport.
- `nta-shopify-fulfilment-auditor`: fresh-read deterministic audit.

## Idempotency
The key hashes order ID, carrier, tracking number, shipment timestamp and sorted fulfilment-order/line identities with quantities. `job_id` is deliberately excluded so replayed source events with a new delivery ID still collapse to the same shipment identity.

## Persistence boundary
This skill does not invent a database. The runtime/orchestrator must provide a durable completed-key store. Mark completion only after canonical verification succeeds.

## Security
No credentials are accepted or printed by this skill. Shopify credentials remain owned by the canonical fulfilment writer adapter. No browser fallback is permitted.
