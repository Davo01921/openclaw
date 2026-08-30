---
name: "nta-inventory-state"
version: "1.0"
description: "Interpret NTA physical stock quantities and determine safe Shopify inventory set/add actions independently from preorder availability."
---

# NTA Inventory State — v1.0

## Purpose

Determine the physical inventory action for an exact Shopify variant.

This module owns stock quantity interpretation only. It does not decide preorder eligibility, retail price, descriptions, tags, or supplier ETA.

## Required output

```yaml
inventory:
  current_available:
  current_on_hand:
  received_qty:
  operation: SET | ADD | NONE
  proposed_available:
  location:
  confidence: HIGH | MEDIUM | LOW
  notes: []
```

## Rules

- Work on the exact matched Shopify variant and inventory item.
- A purchase order is not received inventory.
- `ORDERED` jobs normally return `operation: NONE`.
- `RECEIVED` jobs use physically received quantity after supplier-pack to Shopify-sell-unit conversion.
- Short-supplied, damaged, substituted, or backordered items use physical usable quantity, not ordered quantity.
- Default an explicitly supplied physical count to `SET`, not `ADD`, unless the operator clearly says add/plus/another/increase by.
- Pair/trio/group variants remain their own Shopify units unless the exact selling unit says otherwise.
- Correct clearly corrupt/negative stock to verified physical quantity when authorised and report the exception.
- Do not change inventory policy here. That belongs to `nta-product-availability`.
- Never infer preorder eligibility from inventory quantity.

## Human review

Use LOW confidence where variant identity, stock location, sell-unit conversion, or physical received quantity is uncertain.
