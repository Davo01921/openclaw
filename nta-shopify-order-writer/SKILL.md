---
name: "nta-shopify-order-writer"
version: "1.0"
description: "Canonical deterministic write-phase adapter for authorised Shopify order creation/update actions; never owns business decisions or declares completion."
---

# NTA Shopify Order Writer — v1.0

## Purpose

Apply an already-authorised Shopify **order** change set. This module is a write-phase implementation only.

It does not decide product identity, quantities, discounts, customer selection, financial policy, fulfilment policy, loss policy, or whether a change is allowed. Those decisions must be made upstream.

Core principle: **Skills decide. Writers write. Auditors verify.**

## Scope

Supported order write intents:

- `CREATE_ORDER`
- `UPDATE_ORDER_METADATA`

This version does **not** implement fulfilment. Fulfilment must use a separate canonical fulfilment writer.

## Required input

```yaml
order_write_request:
  job_id: <stable job identifier>
  idempotency_key: <stable unique key>
  intent: CREATE_ORDER | UPDATE_ORDER_METADATA
  target_order_id: null | <exact Shopify order ID>
  authorised: true
  current_state: {} | null
  expected_result: {}
  order:
    customer_id: <exact Shopify customer ID>
    line_items:
      - variant_id: <exact Shopify variant ID>
        quantity: <positive integer>
    tags: []
    note: null | <authorised string>
    discount:
      code: null | <authorised code>
    financial_target: null | <authorised target metadata>
  protected_fields: []
  retry_authorised: false
```

For `CREATE_ORDER`, `target_order_id` must be null. For `UPDATE_ORDER_METADATA`, an exact target order ID is required.

## Deterministic preflight

Use `scripts/order_write_plan.py` before any live write.

The planner validates:

- explicit authorisation;
- supported intent;
- stable `job_id` and `idempotency_key`;
- exact customer ID;
- exact Shopify variant IDs;
- positive integer quantities;
- no duplicate variant lines in the same request;
- required target-order identity for metadata updates;
- explicit expected result for later read-back;
- that no fulfilment fields are present.

The deterministic planner performs zero model calls, zero network calls, and zero Shopify writes.

## Idempotency

Never apply the same authorised order action twice.

Before a live `CREATE_ORDER`, the calling implementation must check whether the `idempotency_key` has already been recorded against an existing order or immutable operation record. If a matching completed action exists, return `DUPLICATE_NOOP` rather than creating another order.

Do not invent a new idempotency key during retry. A retry must reuse the original key and must be explicitly authorised when the prior result is indeterminate.

## Write rules

1. Accept only an upstream-approved request whose deterministic preflight is `READY`.
2. Re-read relevant live state immediately before consequential writes when stale state could matter.
3. For `CREATE_ORDER`, create exactly the authorised order payload. Do not add line items, quantities, tags, discounts, notes, shipping, tax, customer notifications, fulfilment, or inventory adjustments that were not explicitly authorised.
4. For `UPDATE_ORDER_METADATA`, update only explicitly authorised metadata fields on the exact target order.
5. Never perform a separate inventory adjustment as part of order creation. Shopify order/inventory semantics own any resulting inventory effect.
6. Never fulfil the order in this module.
7. Never mark an order paid merely because the upstream workflow desires a financial outcome; apply only the exact supported authorised API action and let the order auditor verify resulting financial state.
8. Preserve unrelated order data and all product/variant data.
9. Record old → new values and mutation identifiers.
10. Do not declare completion. The canonical order auditor / `nta-shopify-write-verifier` owns fresh verification.

## Refusal conditions

Return `BLOCKED` or `REVIEW_REQUIRED` without writing when any of the following applies:

- exact customer identity is missing;
- any exact variant ID is missing or unresolved;
- quantity is missing, non-integer, or non-positive;
- authorisation is not explicit;
- idempotency key is missing;
- a duplicate completed action is found;
- retry safety is indeterminate and retry is not explicitly authorised;
- the request contains fulfilment instructions;
- expected read-back state is missing;
- the requested Shopify operation is not actually supported by the available adapter/tool.

Do not fall back to ad-hoc browser automation or an unrelated writer.

## Required output

```yaml
order_write_result:
  status: SUCCESS | PARTIAL | FAILED | BLOCKED | DUPLICATE_NOOP | NONE
  job_id:
  idempotency_key:
  intent:
  order_id: null | <Shopify order ID>
  mutation_ids: []
  applied_changes: []
  skipped_changes: []
  failed_changes: []
  warnings: []
  retry_count: 0
```

`SUCCESS` means the authorised API write returned successfully. It does **not** mean the workflow is complete.

## Completion boundary

Only a fresh independent order read-back performed by the canonical order auditor can establish completion. A successful API response alone is never sufficient.

Run `python3 scripts/dry_run.py` for deterministic preflight regression coverage.
