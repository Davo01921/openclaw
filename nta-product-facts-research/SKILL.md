---
name: "nta-product-facts-research"
version: "1.0"
description: "Research and return verified NTA product facts and specifications for downstream descriptions and product decisions without writing Shopify."
---

# NTA Product Facts Research — v1.0

## Purpose

Return verified product facts for downstream skills. This module does not write descriptions, decide prices, or mutate Shopify.

## Source hierarchy

Use the strongest available source:

1. manufacturer specification;
2. trusted existing NTA data;
3. supplier documentation;
4. authoritative aquarium reference;
5. established specialist consensus;
6. existing listing only when no stronger source exists.

Existing Shopify content is evidence, not automatically truth.

## Required output

```yaml
facts:
  verified: {}
  qualified: {}
  omitted: []
  conflicts: []
  sources: []
  confidence: HIGH | MEDIUM | LOW
```

## Rules

- Never invent scientific names, dimensions, capacities, care parameters, compatibility, ingredients, dosage, wattage, voltage, flow rate, included components, warranties, origin, growth rate, CO2 requirements, or other factual specifications.
- Prefer omission or qualified wording over fabricated completion.
- Distinguish sale size from adult size, emersed from submerged plant appearance, and promotional-image contents from verified inclusions.
- If sources conflict on a purchase-critical fact, return the conflict for review rather than choosing silently.
- Use Australian English and metric units where applicable.

## Downstream use

`nta-product-description-standard` should consume these verified facts when generating or rewriting descriptions. Other product modules may consume facts where required, but must not reinterpret LOW-confidence facts as certain.
