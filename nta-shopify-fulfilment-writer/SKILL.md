---
name: "nta-shopify-fulfilment-writer"
version: "1.0"
description: "Canonical deterministic write-phase contract for authorised Shopify fulfilment actions."
---

# NTA Shopify Fulfilment Writer — v1.0

## Purpose

Apply an already-authorised Shopify fulfilment action. This module does not decide order identity, fulfilment policy, tracking, notification policy, or inventory policy.

Core principle: **Skills decide. Writers write. Auditors verify.**

## Contract

The deterministic planner accepts:

```yaml
job_id: <stable id>
idempotency_key: <stable id>
authorised: true
order_id: <exact Shopify order ID>
notify_customer: false
fulfilment_orders:
  - fulfilment_order_id: <exact Shopify FulfillmentOrder ID>
    line_items:
      - fulfilment_order_line_item_id: <exact ID>
        quantity: <positive integer>
duplicate_completed: false
prior_result_indeterminate: false
retry_authorised: false
adapter_capability_verified: false
```

For NTA death-loss orders, tracking is omitted and customer notification is false. The writer must never invent tracking information.

## Safety gates

- exact order and fulfilment-order IDs required;
- exact fulfilment-order line-item IDs and positive quantities required;
- duplicate completed action returns `DUPLICATE_NOOP`;
- indeterminate retry requires explicit retry authorisation with the same idempotency key;
- live execution remains blocked until the concrete Shopify fulfilment adapter capability is verified;
- no inventory adjustment is performed here.

The planner performs zero model calls, zero network calls, and zero Shopify writes.

Run `python3 scripts/dry_run.py` for regression coverage.
