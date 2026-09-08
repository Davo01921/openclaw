---
name: "nta-product-classifier"
version: "1.1"
description: "Deterministically classify NTA products from authoritative structured evidence, escalating only ambiguous or conflicting cases."
---

# NTA Product Classifier — v1.1

## Purpose

Classify what an already-resolved NTA product commercially and operationally is.

This module owns classification only. `nta-product-resolver` owns product/variant identity. `nta-retail-pricing-standard` owns margin and pricing rules. This skill does not write Shopify, decide retail price, change stock, set preorder state, or create content.

## Design principle

Use deterministic rules wherever authoritative structured evidence is sufficient.

Do not use AI to classify cases that can be decided from explicit Shopify product type/category, verified supplier category, or explicit workflow flags.

Titles, common names, scientific names and free-form supplier wording are evidence only. They must not silently determine commercially important states when stronger structured evidence is absent or conflicting.

If evidence is insufficient or conflicting, return `REVIEW_REQUIRED` rather than guessing.

Unknown is not false. Tri-state fields must preserve `true`, `false`, or `unknown` where the distinction can affect downstream behaviour.

## Implementation

Production files:

```text
nta-product-classifier/
├── SKILL.md
└── scripts/
    ├── classifier.py
    └── dry_run.py
```

`scripts/classifier.py` is deterministic Python. It performs no Shopify writes, network calls, or model calls.

## Input contract

Provide resolved product evidence as structured fields where available:

```yaml
shopify_product_type:
shopify_category:
verified_supplier_category:
authoritative_primary: null
authoritative_subtype: null
pricing_category: null
reorderable: null
individually_identified: null
tissue_culture: null
premium_rare: null
specialist_niche: null
commodity_branded: null
low_cost_accessory: null
discontinued: null
clearance_only: null
internal_use: null
title: null
```

The exact product/variant must already have been resolved by `nta-product-resolver` before this classifier is used for write-sensitive downstream work.

## Output contract

Return:

```yaml
status: CLASSIFIED | REVIEW_REQUIRED
classification:
  primary: LIVESTOCK | PLANTS | DRY_GOODS
  subtype:
  pricing_category:
  replenishable: true | false | unknown
  individually_identified: true | false | unknown
  tissue_culture: true | false
  evidence: []
missing_or_conflicting_fields: []
notes: []
```

`classification` may contain a safe partial result when the primary category is known but a downstream-significant field still requires review.

## Evidence priority

Use authoritative evidence in this order:

1. explicit canonical primary/subtype supplied by a trusted workflow;
2. Shopify product type/category;
3. verified supplier/manufacturer category;
4. explicit structured flags/metafields;
5. title/scientific/common name and free-form supplier wording only as non-authoritative evidence.

Do not classify from one title keyword when stronger evidence is missing or contradictory.

## Canonical primary categories

### LIVESTOCK
Fish, bettas, shrimp, snails, crayfish/crabs and other aquatic livestock.

### PLANTS
Aquarium plants including stem, rosette, rhizome, carpet, moss, floating and tissue-culture plants.

### DRY_GOODS
Aquariums/tanks, stands/cabinets, equipment, food, water treatment, medication, consumables, aquascaping goods, spare parts and accessories.

## Pricing-category mapping

The classifier may map only to canonical category names owned by `nta-retail-pricing-standard`:

- `COMMON_LIVESTOCK`
- `PREMIUM_RARE_LIVESTOCK`
- `INDIVIDUAL_BETTAS`
- `SHRIMP_SPECIALIST_INVERTEBRATES`
- `AQUARIUM_PLANTS`
- `TISSUE_CULTURE`
- `FOOD_CONSUMABLES`
- `COMMODITY_BRANDED_EQUIPMENT`
- `SPECIALIST_NICHE_EQUIPMENT`
- `LOW_COST_ACCESSORIES`

This skill must not copy margin percentages or price rules from the pricing standard.

### Important safeguards

- `Betta` does not by itself mean `INDIVIDUAL_BETTAS`.
- When authoritative evidence establishes livestock/fish and the title or subtype indicates Betta, but `individually_identified` is unknown, retain the safe livestock/fish classification but return `REVIEW_REQUIRED`, leave `pricing_category` null, and preserve `individually_identified: unknown`.
- Only explicit `individually_identified: true` may drive `INDIVIDUAL_BETTAS`.
- Explicit `individually_identified: false` may permit the non-individual livestock path where no other review gate applies.
- `Premium`, `rare`, or similar wording in a title does not by itself mean `PREMIUM_RARE_LIVESTOCK`; use an explicit trusted flag/category.
- Generic equipment does not automatically become commodity or specialist equipment. That distinction requires explicit structured evidence.
- Tissue culture should come from an explicit structured flag or authoritative category/type, not a casual title keyword.

## Replenishment rules

Set `replenishable = false` when any authoritative state says the product is:

- individually identified/one-off livestock;
- discontinued;
- clearance-only;
- internal-use only;
- explicitly not reorderable.

Set `replenishable = true` only where the product is explicitly reorderable and no non-replenishable condition applies.

Otherwise return:

```yaml
replenishable: unknown
```

Zero stock alone must never mean non-replenishable.

## Status rules

### CLASSIFIED
Use when authoritative structured evidence is internally consistent and sufficient for the required classification.

### REVIEW_REQUIRED
Use when:

- primary-category evidence conflicts;
- only weak/free-form title evidence exists;
- a Betta context exists but individual-identification state is unknown;
- a pricing category materially affects downstream pricing but cannot be established safely;
- tissue-culture or individual-identification flags conflict with the primary category;
- an explicit canonical category value is invalid;
- another material classification field would require guessing.

Do not replace these review gates with `HIGH`, `MEDIUM`, or `LOW` confidence labels for deterministic decisions.

## AI boundary

Target model usage:

```text
Known structured classification: 0 model calls
Known subtype/category mapping: 0 model calls
Replenishment from explicit state: 0 model calls
Ambiguous free-form interpretation: optional upstream AI/human review only
```

If AI is required to interpret genuinely ambiguous supplier wording or product text, it should produce structured evidence for review. The deterministic classifier should then be rerun. AI must not silently bypass conflicting authoritative fields.

## Shopify and side-effect boundary

This skill performs:

```text
Shopify writes: 0
Network calls required by classifier: 0
Pricing decisions: 0
Inventory changes: 0
Model calls required for deterministic classification: 0
```

## Regression test

Run:

```bash
python3 scripts/dry_run.py
```

The regression suite covers:

- common livestock with explicit non-individual state;
- tissue culture;
- fish food;
- individually identified one-off Betta;
- Betta with unknown individual-identification state;
- title-only ambiguity;
- conflicting primary-category evidence;
- generic dry-goods pricing ambiguity;
- zero Shopify writes/network/model calls.

A successful run starts with:

```text
DRY_RUN_PASS: deterministic-first product classifier
```
