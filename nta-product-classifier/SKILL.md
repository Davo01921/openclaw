---
name: "nta-product-classifier"
version: "1.0"
description: "Classify NTA products into canonical category, subtype, replenishment, and one-off states for downstream rules."
---

# NTA Product Classifier — v1.0

## Purpose

Classify what the product commercially and operationally is. This module does not write Shopify or decide price, stock, descriptions, or preorder state.

## Required output

```yaml
classification:
  primary: LIVESTOCK | PLANTS | DRY_GOODS
  subtype:
  pricing_category:
  replenishable: true | false | unknown
  individually_identified: true | false
  tissue_culture: true | false
  confidence: HIGH | MEDIUM | LOW
  evidence: []
```

## Classification evidence order

Use the combined evidence from:

1. exact product/variant identity;
2. Shopify product type/category;
3. verified vendor/manufacturer information;
4. tags and metafields;
5. title/scientific/common name;
6. supplier documentation.

Do not classify from one keyword when stronger evidence contradicts it.

## Canonical primary categories

### LIVESTOCK
Fish, shrimp, snails, crayfish/crabs, and other aquatic livestock.

### PLANTS
Stem, rosette, rhizome, carpet, moss, floating, tissue culture, and other aquarium plants.

### DRY_GOODS
Aquarium/tank, stand/cabinet, equipment, food, water treatment, aquascaping, consumables, medication, spare parts, accessories, and other non-live goods.

## Replenishment rules

`replenishable = false` for individually numbered/photographed one-off livestock, discontinued lines, clearance-only products, explicit internal-use products, and products NTA has determined cannot be reordered.

Do not assume zero stock means non-replenishable.

## Pricing category

Where pricing is required, map to the closest canonical category defined in `nta-retail-pricing-standard`. Do not copy margin ranges into this skill; the pricing standard remains the source of truth.

## Human review

Use LOW confidence where identity/category evidence conflicts or where classification materially changes pricing, availability, or content requirements.
