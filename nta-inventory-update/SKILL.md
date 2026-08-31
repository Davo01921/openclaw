---
name: "nta-inventory-update"
description: "Handle NTA livestock/product stock intake as a specialist workflow that delegates identity, cost, pricing, inventory, availability, metafields, writes, and QA to canonical product modules."
---

# NTA inventory update

Use when incoming livestock or other received stock must be reconciled against Shopify.

This is a specialist intake workflow, not the source of truth for product-domain rules.

## Canonical dependencies

Read `nta-product-orchestrator` first and use:

- `nta-product-resolver`
- `nta-product-classifier`
- `nta-supplier-unit-cost-normalizer` when supplier cost is supplied
- `nta-retail-pricing-standard` when retail review is required
- `nta-inventory-state`
- `nta-product-availability`
- `nta-product-metafields`
- `nta-product-exception-gate`
- `nta-shopify-write-verifier`

Do not maintain separate pricing, preorder, or write rules here.

## Intake fields

Parse where available:

- vendor/supplier;
- product and exact variant;
- size/sex/pack/sell unit;
- received physical quantity;
- supplier cost and GST basis;
- arrival date;
- tank/location;
- supplier availability/ETA evidence;
- operator instruction: set/add/received/partial.

## Workflow

1. Resolve exact Shopify identity and duplicate risk with `nta-product-resolver`.
2. Classify product and replenishment/one-off state with `nta-product-classifier`.
3. If cost is supplied, normalize GST and units with `nta-supplier-unit-cost-normalizer`.
4. If price review is required, use `nta-retail-pricing-standard` with normalized cost and current live price.
5. Resolve the stock write with `nta-inventory-state`.
6. Resolve customer orderability/preorder separately with `nta-product-availability`.
7. Map arrival date, tank/location and availability outputs with `nta-product-metafields`.
8. Run `nta-product-exception-gate`.
9. Apply and freshly verify approved changes only through `nta-shopify-write-verifier`.

## Intake-specific rules

- A verified physical count defaults to SET unless the operator explicitly says add/plus/another/increase by.
- Pair/trio/group quantities target their exact Shopify sell unit; do not split them silently.
- Arrival date may use a supplied/confirmed date. Do not invent supplier ETA.
- Tank/location values must follow current NTA store rules; preserve an active assignment when required and report the reason.
- Labels, when requested, are an intake output and must use already-resolved product/vendor/cost/retail/arrival/tank data. Label generation must not change product decisions.
- Individually identified Bettas and other one-off livestock remain non-replenishable and must not be made preorder eligible merely because inventory reaches zero.

## Completion

Do not mark complete until `nta-shopify-write-verifier` returns verified expected-vs-live Shopify state for every changed field.

Report genuine exceptions rather than guessing.
