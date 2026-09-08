# NTA inventory-update workflow reference

Owner: Nano Tanks Australia (NTA)
Version: 1.2

This reference describes orchestration only. Product-domain rules belong to the canonical child skills and must not be duplicated here.

## Scope

Use `nta-inventory-update` for stock that has physically arrived, a verified physical count, or an authorised inventory correction.

Do not use this workflow for `ORDERED` stock that has not physically arrived. Route that case to `nta-supplier-order-processing`.

## Structured intake

Provide, where applicable:

- exact product/variant evidence;
- vendor/supplier;
- received or counted physical quantity in the Shopify selling unit;
- supplier cost and GST basis when supplied;
- whether retail review is required;
- confirmed arrival date when supplied;
- authorised tank/location when supplied;
- supplier availability/ETA evidence;
- inventory job state and quantity basis;
- correction authorisation when applicable;
- dry-run or write mode;
- whether a DYMO tank label is requested.

Do not invent missing dates, tank locations, supplier ETAs, selling-unit conversions, correction authority, or product identity.

## Canonical route

For received/count/correction work, the maximum planned route is:

1. `nta-product-resolver`
2. `nta-product-classifier`
3. `nta-supplier-unit-cost-normalizer` only when supplier cost is supplied
4. `nta-retail-pricing-standard` only when a retail review is required
5. `nta-inventory-state`
6. `nta-product-availability`
7. `nta-product-metafields`
8. `nta-product-exception-gate`
9. `nta-shopify-write-verifier` in write mode only
10. `nta-dymo-tank-label` when requested; after verified Shopify state in write mode, or from proposed state in dry-run mode

Use `scripts/route_plan.py` when the routing flags are already structured.

## Fail-fast execution

The maximum route is not a requirement to invoke every child after a prerequisite fails.

Run children sequentially and stop dependent work immediately when:

- a required child returns `REVIEW_REQUIRED`;
- any child returns `BLOCK`;
- required structured output for the next dependency is missing.

Continue only when the reached child has satisfied its own documented success contract.

Examples:

- unresolved exact product/variant identity → stop after `nta-product-resolver`;
- unresolved classification → stop before inventory/availability/metafield work that depends on it;
- unresolved inventory state → stop before downstream availability/metafield/write work;
- unresolved availability → do not generate availability-derived metafield changes;
- unresolved metafield mapping → do not write;
- exception gate `REVIEW_REQUIRED` or `BLOCK` → do not write.

Do not call downstream skills simply to reproduce a failure already established by a prerequisite. This keeps the workflow cheaper, faster, and easier to audit.

## Responsibility boundaries

- Identity and duplicate risk: `nta-product-resolver`.
- Classification and replenishment/one-off state: `nta-product-classifier`.
- Supplier-unit arithmetic: `nta-supplier-unit-cost-normalizer`.
- Retail decisions: `nta-retail-pricing-standard`.
- Physical quantity operation (`SET`, `ADD`, `NONE`): `nta-inventory-state`.
- Customer orderability/preorder state: `nta-product-availability`.
- Shopify metafield mapping: `nta-product-metafields`.
- Exception disposition: `nta-product-exception-gate`.
- Shopify mutation plus fresh verification: `nta-shopify-write-verifier`.
- DYMO text formatting: `nta-dymo-tank-label`.

This workflow must not maintain its own competing rules for any of those domains.

## Arrival date and location

A supplied/confirmed arrival date may flow to `nta-product-metafields`. Never default a missing arrival date to today.

A tank/location must come from authorised upstream state. Never default a missing location to `OFFLOCATION1` or another invented value.

## Inventory corrections

Do not repair negative or corrupted inventory inside this workflow. Pass the state to `nta-inventory-state`, which owns correction rules and required authorisation.

## Writes and completion

In dry-run mode, stop before Shopify mutation and return the approved proposed state reached before any fail-fast condition.

In write mode, all approved changes must pass through `nta-shopify-write-verifier`. Do not declare completion from a successful mutation request alone.

A write-mode item is complete only when expected-vs-live verification succeeds for every changed field or an explicit accepted warning state is returned. Unresolved review items or blocks must be reported.

## Model use

Routing and terminal child-result gating are deterministic and should use zero model calls.

AI may be used upstream only when genuinely needed to turn ambiguous free-form supplier/operator material into structured evidence. Once structured, arithmetic, routing, state decisions, mapping, writing and verification should use the relevant canonical deterministic components wherever available.
