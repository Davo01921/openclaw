---
name: "nta-product-metafields"
version: "1.0"
description: "Map approved NTA product state into canonical Shopify metafield changes without deciding the underlying business rules."
---

# NTA Product Metafields — v1.0

## Purpose

Translate already-decided product state into Shopify metafield changes.

This module does not decide availability, pricing, inventory, or product facts. It maps canonical state to store fields.

## Required output

```yaml
metafields:
  proposed:
    namespace.key: value
  preserve: []
  confidence: HIGH | MEDIUM | LOW
  notes: []
```

## Known canonical mappings

Where applicable and already decided upstream:

- `custom.preorder_eligible`
- `custom.preorder_status_override`
- `custom.arrival_date`
- `custom.in_store_location_tank_number`
- other structured product fields defined by the current NTA Shopify schema.

## Rules

- Never invent a metafield definition or value type.
- Read current Shopify definitions before writing unfamiliar fields.
- Preserve existing unrelated metafields.
- Do not encode a business rule in two places where one canonical field already exists.
- Arrival date must come from a confirmed/supplied date, not a guessed ETA.
- Tank/location fields must use the authorised NTA format.
- Availability mappings must consume `nta-product-availability` output rather than independently deciding preorder logic.

## Review triggers

Use LOW confidence when a field definition, allowed value, namespace/key, type, or product-vs-variant scope is uncertain.
