# SOP — NTA Shipping Fulfilment v2

## Normal path
1. Receive a structured, verified shipment event.
2. Pipe it to `scripts/shipping_fulfilment.py`.
3. Continue only when status is `READY`.
4. Check the generated idempotency key against the durable completed-event store.
5. If already completed, return `DUPLICATE_NOOP`.
6. Pass `write_request` unchanged to `nta-shopify-write-verifier`.
7. Let the canonical verifier/writer/auditor perform mutation and fresh verification.
8. Persist the idempotency key only after `VERIFIED` or `VERIFIED_WITH_WARNING`.

## Exception path
Any missing, conflicting, inferred or ambiguous shipment identity returns `REVIEW_REQUIRED`. Human/AI investigation may resolve the source data, but a new structured event must then pass the same Python validation. Never edit around a failed gate.

## Operational rule
This skill owns shipment-event validation and request construction only. It does not own Shopify transport, inventory mutation, carrier selection, label purchase or fulfilment auditing.
