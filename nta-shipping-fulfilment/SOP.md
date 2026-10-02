# SOP — NTA Shipping Fulfilment v2

## Normal path
1. Receive a structured, verified shipment event.
2. Pipe it to `scripts/shipping_fulfilment.py`.
3. Continue only when status is `READY`.
4. Use `shipment_boundary.execute_shipment` and the persistent `ShipmentLedger`. It checks prior receipts and atomically claims an intent before any write.
5. If already completed, return `DUPLICATE_NOOP`.
6. Pass `write_request` to `fulfilment_handoff` with fresh exact order/remaining-line context. Use the canonical writer callback and a separate independent fresh-reader callback.
7. Let the canonical verifier/writer/auditor perform mutation and fresh verification.
8. Persist the writer receipt, then complete the intent only after independent PASS. An unfinished intent is REVIEW_REQUIRED; reconcile it instead of replaying the mutation.

## Exception path
Any missing, conflicting, inferred or ambiguous shipment identity returns `REVIEW_REQUIRED`. Human/AI investigation may resolve the source data, but a new structured event must then pass the same Python validation. Never edit around a failed gate.

## Operational rule
This skill owns shipment-event validation and request construction only. It does not own Shopify transport, inventory mutation, carrier selection, label purchase or fulfilment auditing.

Status: READY FOR FINAL LIVE ACCEPTANCE; see docs/CLOSEOUT.md. Back up the SQLite ledger and retain it when rolling back code.
