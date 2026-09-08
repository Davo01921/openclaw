---
name: "nta-inventory-update"
version: "1.1"
description: "Coordinate received/count/correction inventory work through canonical NTA modules without duplicating product-domain rules."
---

# NTA Inventory Update — v1.1

## Purpose

Specialist orchestration workflow for stock that has physically arrived, a verified physical count, or an authorised correction.

This skill does not own product identity, pricing, inventory arithmetic, availability, metafield, write, or label rules. It routes structured intake state to the canonical modules.

Core principle: **Skills decide. Writers write. Auditors verify.**

## Scope gate

Accepted job states:

- `RECEIVED`
- `RECEIVED_PARTIAL`
- `COUNTED`
- `CORRECTION`

`ORDERED` stock that has not physically arrived is not an inventory-update receipt. Return `REVIEW_REQUIRED` and redirect to `nta-supplier-order-processing`; never increase physical inventory from an order alone.

## Deterministic route planner

When routing flags are already structured, use `scripts/route_plan.py`.

Input:

```yaml
route_input:
  job_state: RECEIVED | RECEIVED_PARTIAL | COUNTED | CORRECTION | ORDERED
  mode: dry_run | write
  supplier_cost_supplied: true | false
  price_review_required: true | false
  label_requested: true | false
```

Output:

```yaml
status: READY | REVIEW_REQUIRED
route: []
redirect: null
missing_or_conflicting_fields: []
notes: []
```

Route planning requires zero model calls, zero network calls, and zero Shopify writes.

## Canonical dependencies

For valid received/count/correction work run, as applicable:

1. `nta-product-resolver`
2. `nta-product-classifier`
3. `nta-supplier-unit-cost-normalizer` only when supplier cost is supplied
4. `nta-retail-pricing-standard` only when retail review is required
5. `nta-inventory-state`
6. `nta-product-availability`
7. `nta-product-metafields`
8. `nta-product-exception-gate`
9. `nta-shopify-write-verifier` in write mode only
10. `nta-dymo-tank-label` when requested; after verified Shopify state in write mode, or from proposed state in dry-run mode

Do not maintain separate child-skill rules here.

## Intake evidence

Pass structured evidence where available:

- exact product/variant evidence;
- vendor/supplier;
- received or counted quantity in the Shopify selling unit;
- supplier cost and GST basis when supplied;
- confirmed arrival date when supplied;
- authorised tank/location when supplied;
- supplier availability/ETA evidence;
- inventory job state and quantity basis;
- correction authorisation when applicable;
- dry-run/write mode;
- label request.

Free-form supplier/operator text may require upstream extraction, but once structured, routing and deterministic child decisions must not use AI merely for arithmetic, formatting, mapping, or state comparison.

## Safety boundaries

- Never default a missing arrival date to today.
- Never default a missing tank/location to `OFFLOCATION1` or another invented value.
- Never repair negative/corrupted stock here; `nta-inventory-state` owns correction rules and authorisation.
- Never infer SET versus ADD here; pass the structured job state/quantity basis to `nta-inventory-state`.
- Never infer preorder eligibility from zero stock; `nta-product-availability` owns orderability.
- Never invent metafield definitions; `nta-product-metafields` owns mapping and validation.
- Never split pair/trio/group selling units silently; upstream unit resolution must be explicit.
- One-off livestock behaviour comes from canonical classification and availability modules, not duplicated rules here.

## Dry-run mode

Run decision modules and exception gate only. Do not route to Shopify mutation. A requested DYMO label may use the proposed `custom.arrival_date` and resolved approved state.

## Write mode

All approved mutations must pass through `nta-shopify-write-verifier`. DYMO label generation, when requested, occurs only after fresh verified Shopify read-back so it consumes the verified `custom.arrival_date`.

## Completion

Do not mark a write-mode item complete until:

1. required child modules returned valid state;
2. exception status permits the intended action;
3. `nta-shopify-write-verifier` confirms expected-vs-live state for every changed field, or returns an explicitly acceptable verified warning state;
4. unresolved review/block conditions are reported;
5. requested label output is generated from approved/verified state.

A successful API response alone is not proof of completion.

See `references/workflow.md` for the lean orchestration reference. Run `python3 scripts/dry_run.py` for deterministic routing regression.
