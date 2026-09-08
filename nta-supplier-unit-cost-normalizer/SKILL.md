---
name: "nta-supplier-unit-cost-normalizer"
version: "1.1"
description: "Deterministically normalize resolved supplier cost, GST basis, pack quantity and Shopify sell units into reliable NTA unit-cost inputs without deciding retail price."
---

# NTA Supplier Unit Cost Normalizer — v1.1

## Purpose

Convert already-resolved supplier purchasing data into reliable per-Shopify-selling-unit cost data.

This module owns cost arithmetic only. It does not decide retail price, inventory, availability, vendor identity, descriptions, pack interpretation or supplier-text meaning.

## Execution rule

Use `scripts/normalizer.py` for normalization. The normalizer is deterministic and must not call an AI model, network service, Shopify, printer or pricing engine.

If supplier wording such as `pair`, `trio`, `case of 24`, `12 + 2 FREE`, assorted allocation, substitution or pack structure has not yet been resolved into explicit numeric fields, stop and return `REVIEW_REQUIRED` upstream. A separate low-cost parsing/reasoning step may resolve genuinely ambiguous supplier text, but the arithmetic normalizer itself remains model-free.

## Required input

```yaml
cost_input:
  supplier_cost:                 # total supplier line economic cost before attributable costs
  gst_basis: INC_GST | EX_GST
  supplier_order_qty:            # positive integer supplier order units purchased
  supplier_pack_size:            # positive integer base units in each paid supplier order unit
  shopify_sell_unit:             # positive integer base units contained in one Shopify retail unit
  bonus_base_units: 0            # non-negative integer free/bonus base units received
  attributable_line_cost_ex_gst: 0 # directly attributable acquisition cost for the whole line, ex GST
```

All pack wording and selling-unit semantics must be resolved before this module is called.

Examples:

- Supplier pack of 10 fish, Shopify sells individuals: `supplier_pack_size: 10`, `shopify_sell_unit: 1`.
- Supplier pack of 5 sold by Shopify as one pack: `supplier_pack_size: 5`, `shopify_sell_unit: 5`.
- `12 + 2 FREE` sold individually: `supplier_pack_size: 12`, `bonus_base_units: 2`, `shopify_sell_unit: 1`.

## Required output

Successful result:

```yaml
status: READY
cost:
  supplier_cost:
  gst_basis: INC_GST | EX_GST
  supplier_order_qty:
  supplier_pack_size:
  shopify_sell_unit:
  bonus_base_units:
  ordered_base_units:
  shopify_retail_units_produced:
  supplier_line_cost_ex_gst:
  unit_purchase_cost_ex_gst:
  attributable_unit_cost_ex_gst:
  landed_cost_ex_gst:
missing_or_invalid_fields: []
notes: []
```

Invalid or unresolved result:

```yaml
status: REVIEW_REQUIRED
cost: null
missing_or_invalid_fields: []
notes: []
```

## Deterministic rules

- Never assume supplier order quantity equals Shopify sellable quantity.
- Do not interpret pack/carton/pair/trio/dozen/box/tray/case/bonus/free-goods wording inside the arithmetic normalizer; require it to be resolved upstream.
- If supplier cost includes GST, divide by `1.10` to obtain ex-GST supplier-line cost.
- If supplier cost is already ex GST, do not remove GST again.
- `UNKNOWN` GST basis is not accepted by the deterministic normalizer; return `REVIEW_REQUIRED` rather than guessing.
- `paid_base_units = supplier_order_qty × supplier_pack_size`.
- `ordered_base_units = paid_base_units + bonus_base_units`.
- `shopify_retail_units_produced = ordered_base_units ÷ shopify_sell_unit`.
- The division above must be exact. If base units cannot be divided exactly into the stated Shopify selling unit, return `REVIEW_REQUIRED`.
- If Shopify sells the supplier pack as one unit, set `shopify_sell_unit` equal to the base units in that pack; do not divide it into individuals.
- If Shopify sells individual units from a supplier pack, set `shopify_sell_unit: 1`.
- For free goods such as `12 + 2 FREE`, allocate supplier purchase cost over all physical sellable base units received unless an explicit accounting rule upstream says otherwise.
- Include only directly attributable acquisition costs that are reliably known and already supplied ex GST.
- Do not arbitrarily allocate general overhead.
- Do not round or infer supplier inputs. Monetary outputs may be rendered to four decimal places for operational use.

## Formulae

`supplier line cost ex GST = supplier_cost / 1.10` when `gst_basis = INC_GST`

`supplier line cost ex GST = supplier_cost` when `gst_basis = EX_GST`

`unit purchase cost ex GST = supplier_line_cost_ex_gst / shopify_retail_units_produced`

`attributable unit cost ex GST = attributable_line_cost_ex_gst / shopify_retail_units_produced`

`landed cost ex GST = unit_purchase_cost_ex_gst + attributable_unit_cost_ex_gst`

## Review triggers

Return `REVIEW_REQUIRED` when any critical field is missing or invalid, including:

- GST basis unknown;
- supplier order quantity unclear;
- supplier pack size unclear;
- Shopify selling unit unclear;
- bonus/free units unclear;
- assorted allocation unresolved;
- substitution changes the received unit structure;
- received structure cannot be divided exactly into Shopify retail units;
- directly attributable cost is malformed if supplied.

Do not express vague model confidence such as HIGH/MEDIUM/LOW for arithmetic. Either the required structured state is sufficient (`READY`) or it is not (`REVIEW_REQUIRED`).

## Scope boundary

This module supplies normalized cost to `nta-retail-pricing-standard`. It does not copy that skill's margin, market, merchandising or pricing rules.

It performs:

`VALIDATE → CALCULATE → RETURN`

It does not perform:

`INTERPRET SUPPLIER TEXT → PRICE → WRITE SHOPIFY → CHANGE INVENTORY`

## Regression test

Run:

```bash
cd /Users/davidlo/.openclaw/workspace/skills/nta-supplier-unit-cost-normalizer
python3 scripts/dry_run.py
```

Expected prefix:

```text
DRY_RUN_PASS: deterministic supplier unit-cost normalizer
```
