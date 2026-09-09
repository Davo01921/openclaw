---
name: "nta-shopify-order-writer"
version: "1.2"
description: "Canonical deterministic write-phase implementation for authorised Shopify order actions, with guarded Admin GraphQL transport, explicit discount/inventory contracts, and an independent-audit boundary."
---

# NTA Shopify Order Writer — v1.2

## Purpose

Apply an already-authorised Shopify **order** change set. This module is a write-phase implementation only.

It does not decide product identity, quantities, discounts, customer selection, financial policy, fulfilment policy, loss policy, or whether a change is allowed. Those decisions must be made upstream.

Core principle: **Skills decide. Writers write. Auditors verify.**

## Scope

Supported intent contract:

- `CREATE_ORDER`
- `UPDATE_ORDER_METADATA`

Concrete live transport currently implemented in `scripts/shopify_order_api.py`:

- guarded `CREATE_ORDER` via Shopify Admin GraphQL `orderCreate`;
- explicit item-percentage discount mapping when fully specified upstream;
- fresh `READ_ORDER` for independent audit use;
- read-only access-scope capability probe.

`UPDATE_ORDER_METADATA` remains a contract-level intent until a canonical exact-field API adapter is added. Do not claim it live-capable merely because preflight accepts the intent.

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
  duplicate_completed: false
  prior_result_indeterminate: false
  adapter_capability_verified: false
  order:
    customer_id: <exact Shopify customer ID>
    line_items:
      - variant_id: <exact Shopify variant ID>
        quantity: <positive integer>
    tags: []
    note: null | <authorised string>
    discount:
      code: null | <authorised code>
      type: null | ITEM_PERCENTAGE
      percentage: null | <number > 0 and <= 100>
    financial_target: null | <exact Shopify-supported financial status>
    create_options:
      inventory_behaviour: BYPASS | DECREMENT_IGNORING_POLICY | DECREMENT_OBEYING_POLICY
      send_receipt: false
      send_fulfillment_receipt: false
  protected_fields: []
  retry_authorised: false
```

For `CREATE_ORDER`, `target_order_id` must be null and `create_options.inventory_behaviour` is mandatory. Never rely on Shopify's implicit inventory default. For `UPDATE_ORDER_METADATA`, an exact target order ID is required.

A percentage discount must be supplied as a complete explicit contract: `code`, `type: ITEM_PERCENTAGE`, and `percentage`. A code name by itself is never enough authority for the writer to invent a discount value.

## Why explicit inventory behaviour is mandatory

Shopify `orderCreate` defaults inventory handling to `BYPASS`, meaning inventory is not claimed. NTA workflows that require an order to decrement stock must therefore authorise the exact inventory behaviour explicitly. The writer must not infer it from workflow names such as “loss”, “sale”, or “receipt”.

## Deterministic preflight

Use `scripts/order_write_plan.py` before any live write.

The planner validates:

- explicit authorisation;
- supported intent;
- stable `job_id` and `idempotency_key`;
- exact customer ID;
- exact Shopify variant IDs;
- positive integer quantities;
- no duplicate variant lines;
- complete explicit percentage-discount definition when a discount is present;
- percentage greater than zero and not above 100;
- explicit create options and recognised inventory behaviour for `CREATE_ORDER`;
- required target-order identity for metadata updates;
- explicit expected result for later read-back;
- duplicate/retry state;
- that no fulfilment fields are present;
- that concrete adapter capability has been positively verified.

The deterministic planner performs zero model calls, zero network calls, and zero Shopify writes.

## Concrete Shopify API adapter

`scripts/shopify_order_api.py` uses the Shopify Admin GraphQL API directly. Secrets are read from environment only and must never be committed.

Accepted environment names:

- `SHOPIFY_STORE_DOMAIN` or `SHOPIFY_SHOP_DOMAIN`
- `SHOPIFY_ADMIN_ACCESS_TOKEN` or `SHOPIFY_ACCESS_TOKEN`
- optional `SHOPIFY_API_VERSION` (default `2026-07`)
- `SHOPIFY_TOKEN_MODE=offline` to positively assert the token mode required by `orderCreate`

The read-only capability probe queries the current app installation's access scopes. A live create capability is considered verified only when `write_orders` is present **and** token mode is explicitly `offline`. A read-only probe never creates an order.

Actual order creation additionally requires `NTA_SHOPIFY_ORDER_WRITE_ENABLED=true` and an explicit execute call. Merely importing or probing the module cannot create an order.

## Discount contract

The adapter supports an explicit item-percentage discount by mapping:

```yaml
discount:
  code: <authorised code>
  type: ITEM_PERCENTAGE
  percentage: <0 < value <= 100>
```

to Shopify `orderCreate.discountCode.itemPercentageDiscountCode`.

The writer does **not** look up a Shopify discount by code and then infer its value. Upstream policy owns the intended discount value. Fresh order audit owns proof that the resulting saved order actually matches the expected code and financial outcome.

For `nta-death-loss-order`, the canonical upstream contract is:

```yaml
discount:
  code: Ntalosses
  type: ITEM_PERCENTAGE
  percentage: 100
financial_target: PAID
expected_result:
  discount_code: Ntalosses
  total_aud: "0.00"
  zero_balance: true
  financial_status: PAID
```

This closes the order-creation discount-definition gap for the death-loss flow. It does **not** close the separate fulfilment or inventory read-back gaps.

## Current adapter safety limits

The direct adapter intentionally blocks rather than guesses when:

- only a discount-code string is supplied without explicit type/value;
- an unsupported discount type or percentage is supplied;
- `financial_target` is a workflow phrase rather than a Shopify-supported exact financial status;
- create options or inventory behaviour are missing;
- live scopes/token mode are unverified.

## Idempotency

Never apply the same authorised order action twice.

Before a live `CREATE_ORDER`, the calling implementation must check whether the `idempotency_key` has already been recorded against an existing order or immutable operation record. If a matching completed action exists, return `DUPLICATE_NOOP` rather than creating another order.

Do not invent a new idempotency key during retry. A retry must reuse the original key and must be explicitly authorised when the prior result is indeterminate.

## Write rules

1. Accept only an upstream-approved request whose deterministic preflight is `READY`.
2. Re-read relevant live state immediately before consequential writes when stale state could matter.
3. For `CREATE_ORDER`, create exactly the authorised order payload and explicit `create_options`. Do not add line items, quantities, tags, discounts, notes, shipping, tax, customer notifications, fulfilment, or inventory behavior that were not explicitly authorised.
4. Never infer a discount percentage or amount from a discount-code string.
5. Never rely on Shopify's default `BYPASS` inventory behaviour silently.
6. For `UPDATE_ORDER_METADATA`, write only through a future verified exact-field metadata adapter; until then live execution is blocked.
7. Never perform a separate inventory adjustment as part of order creation.
8. Never fulfil the order in this module.
9. Never mark an order paid merely because the upstream workflow desires a financial outcome; apply only an exact supported authorised API status.
10. Preserve unrelated order data and all product/variant data.
11. Record old → new values and mutation identifiers.
12. Do not declare completion. The canonical order auditor / `nta-shopify-write-verifier` owns fresh verification.

## Fresh read-back

The same low-level API module provides `read_order(order_id)` and normalises live Shopify state into the current `nta-shopify-order-auditor` snapshot fields:

- order ID;
- customer ID;
- exact variant IDs and quantities;
- first applied discount code;
- AUD current total when currency is AUD;
- AUD outstanding balance when currency is AUD;
- financial status;
- tags;
- note.

The auditor must call this as a new Shopify read after the write. The write response itself is never audit evidence.

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

Only a fresh independent order read-back performed by the canonical order auditor can establish order-state completion. A successful API response alone is never sufficient.

Run:

- `python3 scripts/dry_run.py`
- `python3 scripts/adapter_dry_run.py`

for deterministic regression coverage. Neither dry-run may access Shopify or the network.
