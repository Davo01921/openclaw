# SPECDOC — NTA Shipping Fulfilment v2

## Objective
Remove model judgement from routine shipment fulfilment preparation while preserving the canonical Shopify mutation boundary.

## Inputs
Stable job ID, explicit authorisation, exact Shopify order/fulfilment-order/line IDs, positive quantities, offset-aware shipment timestamp, explicit notification boolean, and either a carrier+tracking pair or both null.

## Deterministic outputs
`READY` with an exact verifier request, or `REVIEW_REQUIRED`. Duplicate completion uses the persistent SQLite intent/receipt ledger and the generated SHA-256 key. Tracking survives the canonical write boundary; verification uses a separate fresh read.

## Non-goals
No line matching by product title/SKU, no tracking inference, no carrier selection, no inventory write, no Shopify mutation, and no AI decision to fulfil.

## Acceptance criteria
Normal validation performs zero model calls and zero network calls; equivalent canonical shipment identities produce the same idempotency key; malformed/ambiguous events cannot produce a writable request; all writes remain behind `nta-shopify-write-verifier`.

Project status is CLOSED / BAU as recorded in docs/CLOSEOUT.md. A future genuine dispatch restart/replay may still be used as an optional operational confidence check.
