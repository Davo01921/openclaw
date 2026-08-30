---
name: "nta-product-availability"
version: "1.0"
description: "Resolve NTA customer orderability, preorder eligibility, inventory policy, ETA-TBC and disabled states independently from physical inventory."
---

# NTA Product Availability — v1.0

## Purpose

Decide whether customers may buy an exact Shopify variant and which availability state should be shown.

This module owns preorder/orderability state. It does not own physical inventory arithmetic.

## Required output

```yaml
availability:
  preorder_eligible: true | false
  inventory_policy: CONTINUE | DENY
  status_override: automatic | eta_tbc | disabled
  customer_state: IN_STOCK | PREORDER | AVAILABLE_TO_ORDER_ETA_TBC | UNAVAILABLE
  eta:
  confidence: HIGH | MEDIUM | LOW
  notes: []
```

## Inputs

Use exact variant identity, classification/replenishability, physical inventory, supplier availability evidence, and any explicit operator override.

## Canonical rules

- Individually identified Bettas/one-off livestock, discontinued, clearance-only, internal-use and non-replenishable lines are not automatically preorder eligible.
- Replenishable + inventory > 0: normally `preorder_eligible=true`, `automatic`; customer state is IN_STOCK.
- Replenishable + inventory <= 0 + normal replenishment expected: `preorder_eligible=true`, `CONTINUE`, `automatic`; customer state is PREORDER.
- Replenishable + orderable but supplier/restock timing is uncertain or extended: `preorder_eligible=true`, `CONTINUE`, `eta_tbc`; customer state is AVAILABLE_TO_ORDER_ETA_TBC.
- Cannot source/discontinued/NTA does not want further orders: `preorder_eligible=false`, `disabled`, normally `DENY`; customer state is UNAVAILABLE.
- When reliable supply resumes or received stock moves above zero, clear a temporary `eta_tbc` back to `automatic` unless an explicit warning should remain.

## Safeguards

- Zero inventory alone does not prove preorder eligibility.
- A purchase-order date is not an ETA.
- Never invent a restock date from historical delivery timing.
- If supplier wording is ambiguous, preserve existing availability state and lower confidence rather than silently changing it.
- Valid status overrides are only `automatic`, `eta_tbc`, and `disabled`.
