# NTA Shopify Order Writer — Lean Workflow Reference

This module is a deterministic write-phase adapter for authorised Shopify order actions.

## Boundary

Upstream decides:

- exact customer;
- exact variant IDs and quantities;
- tags;
- note;
- discount;
- intended financial outcome;
- whether the write is authorised.

This writer only applies the exact supported order action.

Downstream independently verifies the fresh order state.

## Route

```text
upstream decision / exception gate
        ↓
order_write_plan.py
        ↓
READY?
  no → STOP
        ↓ yes
idempotency / duplicate check
        ↓
concrete Shopify order adapter capability verified?
  no → STOP
        ↓ yes
apply exact authorised order action
        ↓
return write result
        ↓
canonical order auditor
```

## No fulfilment

Fulfilment is deliberately outside this module. A separate canonical fulfilment writer must own exact-line fulfilment actions.

## No direct inventory adjustment

Do not make a separate inventory adjustment when creating an order. Any inventory effect must come from the authorised Shopify order semantics and later be verified by the relevant workflow/auditor.

## Completion

A successful order API response is not completion. Completion requires a fresh independent order read-back against `expected_result`.
