---
name: "nta-product-merchandising"
version: "1.0"
description: "Determine NTA Shopify tags and collection membership from canonical product classification without changing unrelated product data."
---

# NTA Product Merchandising — v1.0

## Purpose

Determine product tags and collection membership from verified product identity/classification.

This module does not own price, inventory, availability, description, or metafield rules.

## Required output

```yaml
merchandising:
  tags_add: []
  tags_remove: []
  collections_add: []
  collections_remove: []
  confidence: HIGH | MEDIUM | LOW
  notes: []
```

## Rules

- Add only tags supported by actual product state or classification.
- Keep operational/workflow tags separate from customer-facing taxonomy where practical.
- Tissue Culture products must carry the Tissue Culture tag when that classification is verified.
- Do not use tags as a substitute for canonical metafields where a structured field exists.
- Do not remove existing tags/collections unless the calling workflow explicitly authorises cleanup or the current state is demonstrably wrong.
- Collection routing must be based on actual product/category/variant facts, not keyword coincidence.
- Dynamic Shopify collections may not require explicit membership writes; respect the store's collection mechanism.

## Review triggers

Use LOW confidence where collection membership depends on ambiguous classification, product use, compatibility, or promotional intent.
