---
name: "nta-inventory-update"
version: "1.3"
description: "Coordinate received/count/correction inventory work through canonical NTA modules without duplicating product-domain rules, with fail-fast dependency handling."
---

# NTA Inventory Update — v1.3

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
2. `nta-product-barcode` when a DYMO label is requested; preserves any existing barcode and deterministically proposes an internal NTA barcode only when the resolved Shopify variant barcode is missing
3. `nta-product-classifier`
4. `nta-supplier-unit-cost-normalizer` only when supplier cost is supplied
5. `nta-retail-pricing-standard` only when retail review is required
6. `nta-inventory-state`
7. `nta-product-availability`
8. `nta-product-metafields`
9. `nta-product-exception-gate`
10. `nta-shopify-write-verifier` in write mode only
11. `nta-dymo-tank-label` when requested; after verified Shopify state in write mode, or from proposed state in dry-run mode

Do not maintain separate child-skill rules here.

## Fail-fast execution gate

The planned route is a maximum route, not an instruction to call every child after a prerequisite has failed.

Execute child skills sequentially. After every required child result:

- `BLOCK` → stop immediately and return workflow `BLOCK`;
- `REVIEW_REQUIRED` → stop immediately before dependent downstream children and return workflow `REVIEW_REQUIRED`;
- missing required structured output → stop as `REVIEW_REQUIRED`;
- otherwise continue only when that child's own documented success contract is satisfied.

Use `child_result_gate()` from `scripts/route_plan.py` for the shared `REVIEW_REQUIRED` / `BLOCK` terminal check when useful.

Critical examples:

- unresolved product/variant identity → stop after `nta-product-resolver`; do not call barcode policy, classifier, inventory, availability, metafields, exception gate, writer, or label;
- label requested + missing Shopify barcode → run `nta-product-barcode`; if its collision check or barcode plan is not safe, stop before Shopify mutation or printing;
- unresolved classification required for the workflow → stop before inventory/availability/metafields;
- unresolved inventory-state decision → stop before availability/metafields/write;
- unresolved availability → stop before availability-derived metafields/write;
- unresolved metafield mapping → stop before mutation;
- exception-gate `BLOCK` or `REVIEW_REQUIRED` → do not mutate Shopify.

Do not cascade the same known prerequisite failure through multiple downstream skills merely to obtain repeated `REVIEW_REQUIRED` results. Fail fast to reduce model/tool usage and keep the reason for stopping clear.

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
- Never invent UPC/EAN/GTIN/ISBN/MPN values. `nta-product-barcode` may create only an internal `NTA-V-<variant-id>` barcode for a missing Shopify variant barcode, and only for the label workflow.
- Never split pair/trio/group selling units silently; upstream unit resolution must be explicit.
- One-off livestock behaviour comes from canonical classification and availability modules, not duplicated rules here.

## Dry-run mode

Run only the decision modules that remain reachable under the fail-fast gate. Do not route to Shopify mutation. If a requested label has no Shopify barcode, `nta-product-barcode` may deterministically propose the internal barcode for preview, but it must not write Shopify and a physical print must not be attempted. A requested DYMO label may use the proposed `custom.arrival_date` and resolved approved state only when all prerequisite state required by the label is valid.

## Write mode

All approved mutations must pass through `nta-shopify-write-verifier`. When a requested label targets a resolved variant whose Shopify barcode is null or blank, `nta-product-barcode` deterministically proposes `NTA-V-<legacyResourceId>`, requires a live collision check, and adds only that exact variant `barcode` change to the authorised write set. The verifier must fresh-read the variant and confirm the exact barcode before the label step. DYMO label generation occurs only after fresh verified Shopify read-back so it consumes the verified `custom.arrival_date` and verified barcode.

## Completion

Do not mark a write-mode item complete until:

1. required child modules that were reached returned valid state;
2. no unresolved prerequisite has stopped the route;
3. exception status permits the intended action;
4. `nta-shopify-write-verifier` confirms expected-vs-live state for every changed field, or returns an explicitly acceptable verified warning state;
5. unresolved review/block conditions are reported;
6. for a requested label, an existing barcode is preserved or a missing barcode has been generated, written, collision-checked and freshly verified as required by `nta-product-barcode`;
7. requested label output is generated from approved/verified state.

A successful API response alone is not proof of completion.

See `references/workflow.md` for the lean orchestration reference. Run `python3 scripts/dry_run.py` for deterministic routing and fail-fast regression.
