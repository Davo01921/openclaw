---
name: "nta-product-availability"
version: "1.1"
description: "Deterministically resolve NTA customer orderability, preorder eligibility, inventory policy, ETA-TBC and disabled states independently from physical inventory arithmetic."
---

# NTA Product Availability — v1.1

## Purpose

Decide whether customers may buy an exact Shopify variant and which availability state should be shown.

This module owns customer orderability, preorder eligibility, inventory policy, ETA-TBC and disabled state. It does not own physical inventory arithmetic, product identity resolution, retail pricing, descriptions, tags, or supplier ETA interpretation from free-form text.

Normal execution is deterministic and side-effect free: no Shopify writes, network calls, or model calls.

## Required input

Use structured authoritative evidence only.

```yaml
availability_input:
  variant_resolved: true | false
  replenishable: true | false | unknown
  individually_identified: true | false | unknown
  discontinued: true | false | unknown
  clearance_only: true | false | unknown
  internal_use: true | false | unknown
  nta_wants_further_orders: true | false | unknown
  available_qty:
  supplier_source_state: NORMAL | ORDERABLE_TIMING_UNCERTAIN | CANNOT_SOURCE | UNKNOWN
  authoritative_eta: null
  explicit_status_override: null | automatic | eta_tbc | disabled
```

Free-form supplier wording must be interpreted upstream before invoking this deterministic decision engine.

## Required output

```yaml
status: READY | REVIEW_REQUIRED
availability:
  preorder_eligible: true | false | unknown
  inventory_policy: CONTINUE | DENY | null
  status_override: automatic | eta_tbc | disabled | null
  customer_state: IN_STOCK | PREORDER | AVAILABLE_TO_ORDER_ETA_TBC | UNAVAILABLE | null
  eta:
  notes: []
missing_or_conflicting_fields: []
```

Do not use fuzzy HIGH/MEDIUM/LOW confidence.

## Canonical rules

- Work on an exact resolved Shopify variant.
- Physical inventory quantity is authoritative only as an input from `nta-inventory-state` or a verified Shopify read-back; this module does not perform inventory arithmetic.
- Individually identified Bettas/one-off livestock, discontinued, clearance-only, internal-use, explicit `nta_wants_further_orders=false`, and non-replenishable lines are not preorder eligible.
- Physical stock above zero may still be sold even when future replenishment is blocked. In that case use `IN_STOCK`, `DENY`, and `preorder_eligible=false` so remaining stock can sell without overselling.
- Replenishable + inventory > 0: normally `preorder_eligible=true`, `CONTINUE`, `automatic`, customer state `IN_STOCK`.
- Replenishable + inventory = 0 + supplier source `NORMAL`: `preorder_eligible=true`, `CONTINUE`, `automatic`, customer state `PREORDER`.
- Replenishable + inventory = 0 + supplier source `ORDERABLE_TIMING_UNCERTAIN`: `preorder_eligible=true`, `CONTINUE`, `eta_tbc`, customer state `AVAILABLE_TO_ORDER_ETA_TBC`.
- Cannot source, discontinued, non-replenishable, internal-use, clearance-only, or NTA-does-not-want-further-orders + inventory = 0: `preorder_eligible=false`, `DENY`, `disabled`, customer state `UNAVAILABLE`.
- Replenishability unknown + inventory = 0: `REVIEW_REQUIRED`; never infer preorder eligibility from zero stock.
- Supplier source state `UNKNOWN` + inventory = 0: `REVIEW_REQUIRED` before enabling `CONTINUE`.
- If inventory > 0 but replenishment is unknown, current stock may be sold with `DENY`; do not enable overselling.
- An explicit `disabled` operator override disables future ordering. Existing positive physical stock may remain `IN_STOCK`, but inventory policy becomes `DENY` and preorder eligibility is false.
- Negative physical inventory is invalid availability input and must be repaired upstream before availability is decided.

## ETA rules

- A purchase-order date is not an ETA.
- Never invent an ETA from historical supplier timing.
- `authoritative_eta` may only be passed through when supplied by an authoritative upstream source.
- `ORDERABLE_TIMING_UNCERTAIN` does not require a guessed date; `eta_tbc` is the safe state.
- When reliable supply resumes or received stock moves above zero, temporary `eta_tbc` normally clears to `automatic` unless an explicit warning/override remains.

## Inventory policy boundary

This module decides proposed `CONTINUE` or `DENY` customer orderability policy, but does not write Shopify itself. A writer component performs any mutation after validation.

Physical inventory and availability remain separate concerns:

- `nta-inventory-state` decides physical quantity state.
- `nta-product-availability` decides whether customers may order beyond current stock and which availability state is shown.

## Safeguards

- Zero inventory alone does not prove preorder eligibility.
- `DENY` does not mean hide a product with physical stock; it means do not sell beyond available inventory.
- Do not silently convert unknown replenishment or unknown supplier state into preorder eligibility.
- Valid status overrides are only `automatic`, `eta_tbc`, and `disabled`.
- If structured inputs are missing, invalid, or materially conflicting, return `REVIEW_REQUIRED` rather than guessing.
- This decision module must not write Shopify, call the network, or call a language model.

## Deterministic implementation

Production logic:

```text
scripts/availability.py
```

Regression suite:

```text
scripts/dry_run.py
```

Run locally:

```bash
python3 scripts/dry_run.py
```
