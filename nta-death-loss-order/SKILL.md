---
name: "nta-death-loss-order"
version: "1.1"
description: "Coordinate NTA livestock death/loss recording through exact variant resolution, deterministic zero-dollar loss-order planning, duplicate prevention, and verified Shopify order/fulfilment writes."
---

# NTA Death Loss Order — v1.1

## Purpose

Use when David reports livestock deaths/losses and wants them identified, recorded, or reflected in Shopify inventory through the loss-order workflow.

This is a specialist orchestration skill. It does not own product identity rules, Shopify order mutation implementation, fulfilment implementation, or generic write verification.

Core principle: **identify only as far as evidence supports, resolve the exact Shopify variant, deduct inventory exactly once, and verify the final live state.**

## Canonical constants

The loss-order contract is:

- customer: `NTA Losses`
- discount code: `Ntalosses`
- target total: `$0.00 AUD`
- base tags: `NTA Loss`, `Death`
- add `Tank {tank}` for each known tank
- no separate inventory deduction for the same loss order

Do not silently change these constants inside normal execution. If the live Shopify customer/discount setup differs or the discount does not produce a zero total, stop for review.

## Model-use boundary

Use AI/vision only when visual or free-form evidence genuinely needs interpretation.

- If a trusted exact Shopify variant ID/SKU/barcode already identifies the item, do not spend a model call re-identifying the livestock from an image.
- If a photo is the only useful identification evidence, vision may generate species/strain/tank candidate evidence.
- Vision identification is evidence only. It never authorises a Shopify write by itself.
- Exact product/variant authority must come from `nta-product-resolver` and live/authoritative identifiers.
- Quantity arithmetic, duplicate checks, canonical order construction, zero-total gating, idempotency, and write preflight are deterministic.

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
8. In write mode, verify before mutation:
   - exact `NTA Losses` customer exists/is selected;
   - `Ntalosses` produces exactly `$0.00 AUD` for the intended order;
   - required inventory location/order context is resolved;
   - the installed Shopify mutation boundary is actually verified to support `order` creation and `fulfilment` for this workflow.
9. Submit authorised order/fulfilment mutations only through `nta-shopify-write-verifier` when its order/fulfilment capability has been verified in the running environment.
10. Freshly reread the completed order and exact affected inventory records. Verify the order contract and the final inventory effect exactly once.
11. Report order number, line items, and before/after inventory evidence.

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
  target_total_aud: "0.00"
  tags: []
  line_items: []
  note_fields: []
  financial_target: PAID_OR_ZERO_BALANCE_VERIFIED
  fulfilment_target: FULFILLED
  inventory_effect: ORDER_ONLY_NO_SEPARATE_DEDUCTION
  expected_net_loss_by_variant: {}
  idempotency_key:
missing_or_conflicting_fields: []
notes: []
```

Normal planner execution requires zero model calls, zero network calls, and zero Shopify writes.

## Fail-fast rules

Stop immediately when:

- exact variant resolution is unresolved/blocked;
- quantity is missing, non-integer, or not positive;
- no stable source event ID exists for a write-sensitive job;
- duplicate loss order already exists (`DUPLICATE_NOOP`, not an error);
- a prior manual deduction may have happened but cannot be reconciled safely;
- customer/discount/location preconditions are unresolved in write mode;
- `Ntalosses` does not verify to a zero total;
- order/fulfilment write capability has not been verified for the installed mutation boundary.

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

If multiple lines resolve to the same Shopify variant, the deterministic planner aggregates the expected net loss for verification while preserving the intended order line plan.

After order/fulfilment processing, reread exact affected inventory records and confirm the final net effect represents the loss once. Record available/on-hand/committed values where the Shopify workflow exposes them; do not invent intermediate inventory semantics.

## Shopify mutation boundary gap

`nta-shopify-write-verifier` declares `order` and `fulfilment` as accepted entity types, but the currently documented child implementation in this repository is product-oriented. Therefore this workflow must not assume order/fulfilment mutation support merely from the entity enum.

Before write mode, verify the running installation can actually create and verify the required order and fulfilment operations. Until that capability is demonstrated, return `REVIEW_REQUIRED` rather than attempting a speculative order mutation.

This is a capability gate, not a reason to use a language model as a substitute writer.

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

### Write mode

Do not report success until:

1. every line is exactly resolved;
2. duplicate/idempotency check passes;
3. any prior manual deduction is safely reconciled;
4. customer/discount/location and order/fulfilment write capability are verified;
5. resulting order total is exactly `$0.00 AUD`;
6. order/fulfilment mutation is submitted through the authorised verification boundary;
7. fresh read-back verifies customer, exact line items/quantities, discount, zero total, financial state, fulfilment state, tags, note/source evidence, and final exact inventory effect once.

Run `python3 scripts/dry_run.py` for the deterministic planner regression.
