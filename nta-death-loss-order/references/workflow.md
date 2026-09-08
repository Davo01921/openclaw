# NTA death-loss order workflow reference

Owner: Nano Tanks Australia (NTA)
Version: 1.1

This reference describes orchestration only. Exact identity belongs to `nta-product-resolver`; Shopify mutation and fresh read-back belong to the verified Shopify write boundary.

## Goal

Record confirmed livestock deaths through one zero-dollar Shopify loss order so inventory is reduced exactly once and the event remains auditable.

## Canonical loss-order contract

- customer: `NTA Losses`
- discount code: `Ntalosses`
- target total: `$0.00 AUD`
- tags: `NTA Loss`, `Death`, plus `Tank {tank}` when known
- source event ID retained for idempotency/audit
- no separate inventory deduction for the same death

## Lean route

1. Use structured identifiers first. Use vision/free-form interpretation only when genuine candidate identification is needed.
2. Resolve every exact Shopify variant with `nta-product-resolver`.
3. Stop immediately on unresolved/blocked identity or invalid quantity.
4. Check for an already-recorded loss event/order. Exact duplicate = `DUPLICATE_NOOP`.
5. Check whether the same death was already manually deducted. If yes, reconcile and verify the baseline before any loss order; if uncertain, stop.
6. Run `scripts/loss_plan.py` to build the deterministic zero-dollar order plan.
7. Dry run stops before mutation.
8. Write mode requires live verification of customer, discount-to-zero, location/order context, and actual order + fulfilment mutation capability.
9. Submit authorised writes only through `nta-shopify-write-verifier` when order/fulfilment support is verified in the running environment.
10. Freshly reread the order and exact affected inventory records. Confirm the loss was applied once.

## Vision boundary

Images may help identify a candidate fish/strain/tank, but image interpretation is not write authority. If a trusted exact variant identifier already exists, skip unnecessary vision work. If a photo is needed, use the result as evidence for exact variant resolution rather than as a substitute for resolution.

## Fail-fast rules

Stop before downstream work when:

- any exact variant is unresolved;
- quantity is unknown or invalid;
- a stable source event ID is unavailable for write-sensitive processing;
- a duplicate order already exists;
- a possible manual deduction cannot be reconciled;
- the discount does not verify to exactly zero;
- customer/location preconditions are unresolved;
- order or fulfilment write/verification capability is not verified.

Do not call a model to bypass any of these deterministic safety gates.

## Manual-deduction reconciliation

The loss order is the canonical inventory-loss event. If a prior manual deduction for the same death is verified, restore the correct pre-loss baseline through the canonical inventory/write path and verify it before creating the order. Never make both a manual deduction and a loss-order deduction for the same event.

## Verification

For every completed write, verify fresh live state for:

- exact order/customer;
- exact variant line items and quantities;
- `Ntalosses` discount;
- `$0.00 AUD` total;
- acceptable zero-balance/paid financial state;
- fulfilled state;
- required tags;
- note/source-event evidence;
- exact affected inventory records and final net loss once.

Do not hardcode assumptions about intermediate `available`, `on_hand`, or `committed` transitions; record and compare the actual lifecycle state exposed by Shopify.

## Current capability caution

The repository-level `nta-shopify-write-verifier` contract names `order` and `fulfilment` entity types, but its documented child writer/auditor are product-oriented. Treat order/fulfilment support as unverified until demonstrated in the running OpenClaw installation. Write mode must fail safe rather than improvise an order writer.
