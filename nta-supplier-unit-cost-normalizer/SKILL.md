---
name: "nta-supplier-unit-cost-normalizer"
version: "1.0"
description: "Normalize supplier cost, GST basis, pack quantity and Shopify sell units into reliable NTA unit-cost inputs without deciding retail price."
---

# NTA Supplier Unit Cost Normalizer — v1.0

## Purpose

Convert supplier purchasing data into reliable per-Shopify-selling-unit cost data.

This module owns cost arithmetic only. It does not decide retail price, inventory, availability, vendor identity or descriptions.

## Required output

```yaml
cost:
  supplier_cost:
  gst_basis: INC_GST | EX_GST | UNKNOWN
  supplier_order_qty:
  supplier_pack_size:
  shopify_sell_unit:
  ordered_base_units:
  unit_purchase_cost_ex_gst:
  attributable_unit_cost_ex_gst:
  landed_cost_ex_gst:
  confidence: HIGH | MEDIUM | LOW
  notes: []
```

## Rules

- Never assume supplier order quantity equals Shopify sellable quantity.
- Resolve pack/carton/pair/trio/dozen/box/tray/case/bonus/free-goods wording before unit cost is used downstream.
- If supplier cost includes GST, divide by 1.10 to obtain ex-GST cost. If already ex GST, do not remove GST again.
- If GST basis materially affects the result and cannot be established, return LOW confidence and block automatic pricing changes.
- If Shopify sells the supplier pack as one unit, do not divide the pack into individuals.
- If Shopify sells individual units from a supplier pack, divide by the actual number of Shopify retail units produced.
- For free goods such as `12 + 2 FREE`, allocate purchase cost over physical sellable units received unless an explicit accounting rule overrides it.
- Do not arbitrarily allocate general overhead. Include only directly attributable acquisition costs where reliably known.

## Formulae

`unit purchase cost = supplier-line economic cost / Shopify retail units produced`

`landed cost = unit purchase cost ex GST + directly attributable unit acquisition cost`

## Human-review triggers

Review when pack size, Shopify selling unit, assorted allocation, GST basis, bonus units, substitution or received quantity is ambiguous.

This module supplies normalized cost to `nta-retail-pricing-standard`; it does not copy that skill's margin or market rules.
