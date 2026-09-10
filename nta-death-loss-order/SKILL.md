---
name: "nta-death-loss-order"
version: "1.3"
description: "Queue verified NTA livestock deaths and close them at 6 pm Sydney as one idempotent, paid, fulfilled, zero-dollar Shopify order with fresh inventory verification."
---

# NTA Death Loss Order — v1.3

## Documents

- [SOP.md](SOP.md) — operator procedure and exception handling.
- [TECHDOC.md](TECHDOC.md) — deployed architecture, authentication, scheduling, and verification.
- [SPECDOC.md](SPECDOC.md) — normative business and software contract.

## Purpose

Use when David reports livestock deaths/losses and wants them identified, recorded, or reflected in Shopify inventory through the loss-order workflow.

This is a specialist orchestration skill. It does not own product identity rules, Shopify order mutation implementation, fulfilment implementation, or generic write verification.

Core principle: **identify only as far as evidence supports, resolve the exact Shopify variant, deduct inventory exactly once, and verify the final live state.**

## Canonical constants

The loss-order contract is:

- customer: `NTA Losses`
- discount code: `Ntalosses`
- discount type: `ITEM_PERCENTAGE`
- discount percentage: `100`
- target total: `$0.00 AUD`
- financial target sent to the order writer: `PAID`
- financial verification requirement: zero outstanding balance
- base tags: `NTA Loss`, `Death`
- add `Tank {tank}` for each known tank
- inventory behaviour for order creation: `DECREMENT_OBEYING_POLICY`
- no separate inventory deduction for the same loss order

Do not silently change these constants inside normal execution. The writer must never infer the discount percentage from the code name. Fresh order read-back must prove that the saved order carries `Ntalosses`, totals exactly `$0.00 AUD`, has zero outstanding balance, and matches the expected financial state.

## Model-use boundary

Use AI/vision only when visual or free-form evidence genuinely needs interpretation.

- If a trusted exact Shopify variant ID/SKU/barcode already identifies the item, do not spend a model call re-identifying the livestock from an image.
- If a photo is the only useful identification evidence, vision may generate species/strain/tank candidate evidence.
- Vision identification is evidence only. It never authorises a Shopify write by itself.
- Exact product/variant authority must come from `nta-product-resolver` and live/authoritative identifiers.
- Quantity arithmetic, duplicate checks, canonical order construction, discount construction, zero-total gating, idempotency, and write preflight are deterministic.

## Required workflow

1. Inspect supplied message/photo evidence only as needed. Extract candidate fish/strain, quantity, tank, cause when stated, and source context.
2. Establish a stable `source_event_id` for idempotency, preferably the source message/event identifier.
3. Resolve every loss line to the exact Shopify variant with `nta-product-resolver`.
4. Fail fast if any affected line remains `REVIEW_REQUIRED`, `UNMATCHED`, or `BLOCKED`. Ask only for the smallest genuinely missing detail.
5. Search for an already-recorded loss order for the same source event/items. If found, return `DUPLICATE_NOOP`; do not deduct inventory again.
6. Determine whether any manual inventory deduction for the same loss has already happened.
   - If none: continue.
   - If one is verified: reverse it through the canonical inventory/write path and verify the restored baseline before creating the loss order.
   - If a possible prior deduction cannot be verified: stop `REVIEW_REQUIRED`.
7. Build the deterministic loss-order plan with `scripts/loss_plan.py`.
8. Resolve the exact Shopify customer ID for `NTA Losses` and construct the canonical `nta-shopify-order-writer` request from the loss plan:
   - exact resolved variant IDs and quantities;
   - `Ntalosses` as `ITEM_PERCENTAGE` at `100`;
   - financial target `PAID`;
   - inventory behaviour `DECREMENT_OBEYING_POLICY`;
   - receipts disabled;
   - expected read-back containing `discount_code: Ntalosses`, `total_aud: "0.00"`, `zero_balance: true`, expected financial status, tags, customer and exact line items.
9. Run canonical order-writer deterministic preflight. Submit an authorised order mutation only if the concrete adapter capability is verified and all upstream write gates pass.
10. Freshly reread the created order through the canonical order auditor. Do not use the mutation response as proof. Verify customer, exact line items/quantities, `Ntalosses`, `$0.00 AUD`, zero outstanding balance, financial status, tags and note/source evidence.
11. Continue to the separate fulfilment writer/auditor only when that capability is independently verified. Order creation success does not imply fulfilment capability.
12. Freshly reread exact affected inventory records through the canonical inventory audit path and prove the final net loss occurred exactly once.
13. Report order number, line items, and before/after inventory evidence only after all required downstream gates pass.

## Deterministic loss planner

Production logic:

```text
scripts/loss_plan.py
```

Input is structured state after exact variant resolution:

```yaml
mode: dry_run | write
source_event_id: <stable source event/message id>
loss_items:
  - resolution_status: RESOLVED | REVIEW_REQUIRED | UNMATCHED | BLOCKED
    shopify_variant_id:
    quantity:
    fish: null
    tank: null
    cause: null
    identification_confidence: null
    evidence: []
prior_loss_order_found: true | false
prior_manual_deduction_found: true | false
manual_reversal_verified: true | false

# write mode only
customer_verified: true | false
discount_zero_verified: true | false
location_verified: true | false
order_write_capability_verified: true | false
fulfilment_write_capability_verified: true | false
```

Output:

```yaml
status: READY | REVIEW_REQUIRED | DUPLICATE_NOOP
write_ready: true | false
order_plan:
  customer: NTA Losses
  discount_code: Ntalosses
  discount:
    code: Ntalosses
    type: ITEM_PERCENTAGE
    percentage: "100"
  target_total_aud: "0.00"
  tags: []
  line_items: []
  note_fields: []
  financial_target: PAID
  financial_verification: ZERO_BALANCE_VERIFIED
  fulfilment_target: FULFILLED
  inventory_effect: ORDER_ONLY_NO_SEPARATE_DEDUCTION
  inventory_behaviour: DECREMENT_OBEYING_POLICY
  expected_net_loss_by_variant: {}
  idempotency_key:
  expected_order_audit:
    discount_code: Ntalosses
    total_aud: "0.00"
    zero_balance: true
    financial_status: PAID
    tags: []
    tags_mode: SUBSET
missing_or_conflicting_fields: []
notes: []
```

Normal planner execution requires zero model calls, zero network calls, and zero Shopify writes.

## Canonical order-writer integration

The death-loss order-creation leg is now defined against `nta-shopify-order-writer` v1.2 or later.

The upstream death-loss skill owns the business contract. The writer receives explicit values and must not infer them:

```yaml
order:
  customer_id: <exact NTA Losses customer ID>
  line_items:
    - variant_id: <exact resolved variant ID>
      quantity: <positive integer>
  tags: <loss-plan tags>
  note: <canonical source/evidence note>
  discount:
    code: Ntalosses
    type: ITEM_PERCENTAGE
    percentage: 100
  financial_target: PAID
  create_options:
    inventory_behaviour: DECREMENT_OBEYING_POLICY
    send_receipt: false
    send_fulfillment_receipt: false
```

The order writer maps that explicit discount to Shopify `orderCreate.discountCode.itemPercentageDiscountCode` and fresh order read-back must prove the resulting saved state.

This closes the previous **discount-definition / zero-dollar order-writer integration gap**. It does not by itself prove fulfilment or inventory read-back.

## Fail-fast rules

Stop immediately when:

- exact variant resolution is unresolved/blocked;
- quantity is missing, non-integer, or not positive;
- no stable source event ID exists for a write-sensitive job;
- duplicate loss order already exists (`DUPLICATE_NOOP`, not an error);
- a prior manual deduction may have happened but cannot be reconciled safely;
- exact `NTA Losses` customer identity is unresolved;
- the explicit discount contract differs from `Ntalosses` / `ITEM_PERCENTAGE` / `100`;
- fresh order audit does not prove `$0.00 AUD` and zero outstanding balance;
- order adapter capability is unverified;
- fulfilment capability is unverified when fulfilment is required;
- final inventory read-back capability is unverified when proving completion.

Do not cascade an upstream identity or duplicate failure through unnecessary downstream calls.

## Order note evidence

For each line, preserve where available:

- fish/strain candidate or resolved label;
- quantity;
- tank;
- cause (may remain null/not established; do not invent one);
- identification confidence;
- evidence used;
- `source_event_id`.

Cause is useful audit context but is not required to record a confirmed death when identity and quantity are otherwise safe.

## Inventory integrity

The loss order is the inventory-loss mechanism. Do not also make a separate inventory deduction for the same death.

Order creation must use explicit `DECREMENT_OBEYING_POLICY`. If multiple lines resolve to the same Shopify variant, the deterministic planner aggregates the expected net loss for verification while preserving the intended order line plan.

After order/fulfilment processing, reread exact affected inventory records and confirm the final net effect represents the loss once. Record available/on-hand/committed values where the Shopify workflow exposes them; do not invent intermediate inventory semantics.

## Deployed downstream capability

The production Fred installation closes one Sydney-date queue at 18:00 through a fixed OpenClaw command. Its deterministic helper uses the allowlisted persisted-session bridge for Shopify reads, `orderCreate`, `fulfillmentCreate`, and fresh verification reads.

The production mutation remains fail-closed unless the fixed scheduled process receives `NTA_SHOPIFY_DEATH_BATCH_WRITE_ENABLED=true`. The helper scopes the generic order and fulfilment gates to its own bridge child process. It does not expose or persist Shopify access-token values.

Full completion is reported only after a fresh order read proves `PAID`, `FULFILLED`, `$0.00 AUD`, the expected customer/tags/source references, and exact inventory deltas. An existing unfulfilled batch order or an indeterminate mutation stops for manual reconciliation rather than blind retry.

## Protected state

Unless independently authorised by another workflow, preserve:

- product title/description;
- retail price;
- images/media;
- product status;
- vendor;
- metafields;
- collections;
- handles;
- unrelated inventory locations/variants.

## Completion

### Dry run

Complete when every loss line is exactly resolved, quantities are valid, duplicate/manual-adjustment checks are represented, and the deterministic order plan is `READY`. No Shopify mutation occurs.

### Order-creation integration

The order-creation integration is complete when:

1. the loss planner emits the explicit `Ntalosses` 100% item-percentage contract;
2. the canonical order writer accepts that contract deterministically;
3. the Shopify adapter maps it to the explicit `orderCreate` percentage-discount input;
4. fresh independent order audit is capable of checking `Ntalosses`, `$0.00 AUD`, zero balance, financial state, exact line items, customer, tags and note.

This integration can be complete even while overall death-loss production readiness remains blocked by fulfilment/inventory verification.

### Full write mode

Do not report overall death-loss success until:

1. every line is exactly resolved;
2. duplicate/idempotency check passes;
3. any prior manual deduction is safely reconciled;
4. customer/location and order/fulfilment write capability are verified;
5. resulting order total is exactly `$0.00 AUD` with zero outstanding balance;
6. order mutation is submitted through the authorised order-writer boundary;
7. fresh order read-back verifies customer, exact line items/quantities, `Ntalosses`, zero total, financial state, tags and note/source evidence;
8. fulfilment is completed and independently verified through a canonical fulfilment path;
9. fresh exact inventory read-back proves the final inventory effect occurred once.

Run `python3 scripts/dry_run.py` for the deterministic planner regression.
