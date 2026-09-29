---
name: "nta-product-orchestrator"
version: "1.4"
description: "Coordinate NTA product decisions through canonical modules, canonical general-model routing, and the shared Shopify write-verification boundary."
---

# NTA Product Orchestrator — v1.4

## Purpose

This is the top-level controller for Nano Tanks Australia product work.

It does not own detailed product-domain rules. It decides which canonical modules must run, in what order, which can be skipped, and when human review is required.

Core principle:

**Skills decide. Writers write. Auditors verify.**

Do not duplicate child-skill rules here. When a canonical child skill changes, this orchestrator should continue to reference it rather than maintain a parallel copy.

## Canonical modules

Use these modules where applicable:

1. `nta-product-resolver` — match/create decision, SKU, vendor identity, duplicate prevention. `nta-product-identity-resolver` is a compatible legacy entry point.
2. `nta-product-barcode` — preserve a live existing variant barcode or deterministically propose an internal NTA barcode when a label workflow finds the barcode missing; owns barcode collision policy but never invents GTIN/UPC/EAN/ISBN/MPN identifiers.
3. `nta-product-classifier` — category, subtype, one-off/replenishable classification.
4. `nta-supplier-unit-cost-normalizer` — GST, packs, retail-unit conversion, landed cost inputs.
5. `nta-retail-pricing-standard` — final retail-pricing decision and price confidence.
6. `nta-product-facts-research` — verified product facts/specifications for content and decision support.
7. `nta-product-description-standard` — canonical NTA description generation and content QA.
8. `nta-inventory-state` — physical quantity interpretation and inventory-set/delta decision.
9. `nta-product-availability` — preorder/orderability state independent of physical stock.
10. `nta-product-merchandising` — tags, collections and customer-facing merchandising classifications.
11. `nta-product-metafields` — map approved product state to Shopify metafields.
12. `nta-shopify-write-verifier` — the only canonical Shopify mutation boundary: authorised write then fresh live-state assertion.
13. `nta-product-exception-gate` — AUTO_APPROVE / WARNING / REVIEW_REQUIRED / BLOCK.
14. `nta-dymo-tank-label` — deterministic read-only two-line DYMO tank-label output from approved livestock intake state and Shopify arrival-date state.
15. `adaptive-model-router` — the sole authority for interchangeable reasoning, extraction, review and vision-inference model selection whenever a product phase genuinely needs a general model.

Existing specialist workflows remain valid entry points but must call these modules instead of maintaining conflicting copies of the same rules:

- `nta-supplier-order-processing`
- `nta-inventory-update`
- `nta-betta-picture-processing-v2`
- `nta-individual-betta-shopify-update`

`nta-automation-orchestrator` is the parent router when the request is not already known to be product work. Direct product-skill invocation still inherits the `adaptive-model-router` rule from `SOUL.md`.

A fixed, non-substitutable specialist service may remain owned by its specialist workflow for its bounded operation under the router's specialised-service boundary. For example, Betta `grok_hero` may remain a fixed Grok/xAI generation stage; that does not make Grok an eligible general reasoning/review route.

## Shared Product State

All modules should exchange structured state rather than free-form prose where practical.

```yaml
product:
  job:
    source:
    mode: dry_run | write
    state: ordered | received | received_partial | catalogue_review | new_product | update

  identity:
    title:
    shopify_product_id:
    shopify_variant_id:
    resolution_status:
    sku:
    barcode:
    barcode_source: existing_shopify | generated_internal | null
    barcode_verification: VERIFIED | PROPOSED | null
    vendor:
    supplier_sku:
    match_confidence:
    duplicate_risk:

  classification:
    category:
    subtype:
    replenishable:
    individually_identified:

  cost:
    supplier_cost:
    gst_basis:
    supplier_order_qty:
    supplier_pack_size:
    shopify_sell_unit:
    unit_purchase_cost_ex_gst:
    attributable_unit_cost:
    landed_cost_ex_gst:
    confidence:

  pricing:
    current_price:
    proposed_price:
    bulk_price:
    bulk_min_quantity:
    decision:
    confidence:

  inventory:
    current_available:
    received_qty:
    mode: set | add | none
    proposed_available:
    confidence:

  availability:
    preorder_eligible:
    inventory_policy:
    status_override:
    customer_state:
    eta:
    confidence:

  content:
    facts:
    description_html:
    content_confidence:

  merchandising:
    tags_add:
    tags_remove:
    collections_add:
    collections_remove:

  metafields:
    proposed: {}

  writes:
    authorised_fields: []
    proposed_changes: []
    applied_changes: []

  qa:
    warnings: []
    errors: []
    final_status:

  labels:
    dymo_tank:
      status:
      text:
      source:
      warnings: []
```

A module may update only its own responsibility unless explicitly defined otherwise.

## Entry-point routing

### New product

Run:

`identity → classifier → facts research as needed → cost normalizer → pricing → inventory state → availability → description → merchandising → metafields → exception gate → Shopify writer → QA auditor`

Do not create a product when identity or classification is materially uncertain.

### Supplier order / invoice — ORDERED

Run:

`supplier-order parser/intake → identity → classifier → cost normalizer → pricing only if cost/pricing review is needed → availability only if supplier availability evidence changed → metafields → exception gate → Shopify writer → QA auditor`

Do not increase available inventory from an order alone.

### Supplier order / invoice — RECEIVED

Run:

`supplier-order parser/intake → identity → barcode policy when label requested → classifier → cost normalizer → inventory state → pricing if required → availability → metafields → exception gate → Shopify writer/verifier → QA auditor → DYMO tank label when requested`

### Existing-product catalogue cleanup

Run only affected modules. Examples:

- description-only cleanup: `identity → classifier → facts research → description → exception gate → writer → QA`
- price review: `identity → classifier → cost normalizer → pricing → exception gate → writer → QA`
- inventory receipt: `identity → classifier → inventory state → availability → metafields → exception gate → writer → QA`
- tag/collection cleanup: `identity → classifier → merchandising → writer → QA`

Never run expensive modules merely because they exist.

### Individual Bettas / one-off livestock

Invoke the relevant Betta workflow, but enforce shared classification and availability rules:

- individually identified = true
- replenishable = false
- never automatically preorder eligible
- inventory normally represents the specific specimen

Betta image processing remains specialised and is not replaced by this orchestrator.

## Dependency rules

- Identity must be resolved before any write.
- When a DYMO label is requested, barcode policy runs only after exact variant identity is resolved. Existing non-empty Shopify barcodes are preserved. A missing barcode may be generated only as the internal `NTA-V-<legacyResourceId>` value, collision-checked, written through the verifier, and freshly read back before physical printing.
- Internal NTA barcodes are not GTIN/UPC/EAN/ISBN/MPN values and must never be represented to Google or another external channel as such.
- Classification must be resolved before category-specific description or pricing logic.
- Cost normalisation must complete before pricing when supplier cost is part of the decision.
- Physical inventory and customer availability are separate states.
- A zero inventory count does not, by itself, prove preorder eligibility.
- Description generation must consume verified facts rather than invent missing specifications.
- Shopify Writer must receive an explicit authorised field list.
- QA Auditor must independently re-read changed fields after writing.
- DYMO tank-label generation is read-only and occurs after QA in write mode so it consumes the verified `custom.arrival_date` and verified variant barcode. In dry-run mode it may consume a proposed internal barcode for preview only; physical printing of a newly generated barcode is blocked until Shopify write/read-back verification succeeds.

## Write safety

No child decision skill should directly mutate Shopify unless it is explicitly acting as the `nta-shopify-product-writer`.

Specialist legacy workflows may temporarily contain direct-write implementation details, but their canonical decision rules must come from the modules above and should be progressively refactored toward the writer boundary.

Before a write, build a change set containing:

- field
- current value
- proposed value
- source module
- confidence
- reason

The writer must not change unrelated fields.

## Exception gate

Before writing, run `nta-product-exception-gate`.

Possible outcomes:

- `AUTO_APPROVE` — safe to proceed.
- `AUTO_APPROVE_WITH_WARNING` — proceed and report warning.
- `REVIEW_REQUIRED` — do not write the affected uncertain field(s); deterministic safe fields may proceed only when independent.
- `BLOCK` — no product mutation.

Never turn missing evidence into invented certainty just to complete a workflow.

## Model eligibility and cost discipline

This orchestrator may decide whether a phase appears deterministic or model-eligible, but it must not choose the general provider/model itself.

Prefer deterministic code/rules for:

- GST arithmetic;
- pack conversion once units are known;
- inventory arithmetic;
- state comparisons;
- tag/metafield application;
- Shopify write verification.

Typical `LIGHT` or `STANDARD` capability hints include:

- straightforward extraction from clean supplier text;
- routine content drafting from verified facts;
- simple product-fact synthesis;
- low-ambiguity interpretation where deterministic evidence alone is insufficient.

Typical `DEEP` capability hints include:

- ambiguous identity;
- contradictory product evidence;
- non-obvious pack/variant mapping;
- pricing exceptions requiring judgment;
- uncertain biological/product facts;
- cross-module contradictions.

These are hints passed to `adaptive-model-router`, not local general model-selection rules. The router may return `NONE`, `LIGHT`, `STANDARD`, `DEEP`, or `CRITICAL_REVIEW` under its canonical policy.

Do not invoke a general model merely to perform arithmetic, formatting, exact comparison, deterministic API work, or read-back verification.

## Final completion rule

A job is complete only when:

1. all required modules returned a state;
2. exception status allows the intended action;
3. `nta-shopify-write-verifier` returned `VERIFIED` or an explicitly acceptable `VERIFIED_WITH_WARNING`;
4. expected and live values match for every changed field;
5. general model-bearing phases, if any, followed the `adaptive-model-router` contract;
6. unresolved warnings/review items are reported explicitly.

A successful API response alone is not proof of completion.
