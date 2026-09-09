# NTA Shopify Order Writer — Lean Workflow Reference

This module is a deterministic write-phase implementation for authorised Shopify order actions.

## Boundary

Upstream decides:

- exact customer;
- exact variant IDs and quantities;
- tags;
- note;
- discount definition/value;
- exact supported financial status if one is to be sent to Shopify;
- explicit Shopify order-create inventory behaviour;
- whether receipts are allowed;
- whether the write is authorised.

This writer applies only the exact supported order action. Downstream independently verifies fresh order state.

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
shopify_order_api.py capability probe
  no read/write scope or offline token proof → STOP
        ↓
build exact GraphQL payload
  unsupported discount/financial semantics → STOP
        ↓
explicit write-enable present?
  no → STOP
        ↓ yes
orderCreate
        ↓
return API write result only
        ↓
fresh independent read_order(order_id)
        ↓
nta-shopify-order-auditor
```

## Inventory behaviour

Shopify `orderCreate` defaults to `BYPASS`, so inventory is not claimed unless an option is supplied. The writer therefore requires one explicit value:

- `BYPASS`
- `DECREMENT_IGNORING_POLICY`
- `DECREMENT_OBEYING_POLICY`

The workflow calling the writer owns the choice. The writer must never infer it.

## Discount boundary

A discount code name alone is insufficient for the direct `orderCreate` adapter because Shopify requires an explicit discount definition/value in the create input. The adapter blocks code-only discount requests rather than inventing a percentage or amount.

## No fulfilment

Fulfilment is deliberately outside this module. A separate canonical fulfilment writer must own exact-line fulfilment actions.

## No separate inventory adjustment

Do not make a second inventory adjustment when creating an order. If the authorised order must claim stock, use the explicit Shopify `inventoryBehaviour` option and verify the resulting stock effect separately in the calling workflow.

## Completion

A successful order API response is not completion. Completion requires a new live `read_order` result passed to `nta-shopify-order-auditor` against the caller's expected state.
