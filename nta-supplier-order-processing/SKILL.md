---
name: "nta-supplier-order-processing"
description: "Process supplier purchase orders from Discord, understand packs/combo deals, match Shopify products, audit cost/vendor/retail, and update inventory safely."
---

# NTA supplier order processing

Use when a supplier order, invoice, screenshot, PDF, CSV, or Discord message needs to be reconciled against Shopify.

Read [references/workflow.md](references/workflow.md) before making Shopify changes.

## Purpose

Turn a supplier document into a verified Shopify change set without blindly assuming that supplier order quantities equal Shopify sellable units.

The workflow must understand packs, cartons, trays, pairs, trios, assorted bundles, bonus quantities, free goods, and other supplier ordering units.

## Non-negotiable rules

- Shopify is the live source of truth for existing products, variants, inventory units, vendor, cost and retail.
- Never create a new Shopify product merely because a supplier line cannot be matched. Flag it for review unless creation was explicitly requested.
- SKU/barcode/vendor SKU match wins over title matching. Exact product + variant match is next. Fuzzy title matching may suggest a candidate but must not silently write when ambiguous.
- Supplier **order quantity** and Shopify **sellable quantity** are different concepts. Resolve the unit conversion before any inventory write.
- Do not assume a line containing `10 PACK`, `6PK`, `PAIR`, `TRIO`, `DOZEN`, `BOX`, `TRAY`, `CARTON`, `CASE`, `ASSORTED`, `BONUS`, or similar is one sellable unit.
- Conversely, do not multiply a supplier pack if Shopify itself sells that exact pack as one variant. Match the Shopify selling unit first.
- Supplier line subtotal must be divided by the supplier units actually purchased before comparing unit cost. Then convert cost again if the Shopify selling unit differs from the supplier unit.
- Detect whether prices are ex-GST or inc-GST from the document totals or explicit wording. Never mix GST-inclusive and GST-exclusive cost bases.
- Retail price must not change automatically just because supplier cost changed. Review margin and like-for-like market evidence first. Auto-change retail only when an explicit NTA pricing rule authorises it.
- Vendor can be corrected automatically only when the supplier identity is clear and the Shopify match is high confidence.
- A purchase order is not proof that stock has physically arrived. `ORDERED` and `RECEIVED` are separate states.
- In `ORDERED` state, update cost/vendor/audit data as appropriate but do not increase Shopify available inventory merely because goods were ordered.
- In `RECEIVED` state, convert supplier units to Shopify sellable units, then update inventory using the received quantity.
- If part of an order is short supplied, damaged, substituted or backordered, inventory must use the physically received quantity, not the ordered quantity.
- The same supplier order must be idempotent. Build a fingerprint from supplier + order/invoice number where available, otherwise supplier + document date + normalized line items + total. Refuse a duplicate inventory application unless explicitly overridden.
- Never report completion until every write is re-read from Shopify and verified.

## Pack and combo intelligence

For every supplier line determine four separate values:

1. `supplier_order_qty` — how many supplier packs/lines were ordered.
2. `supplier_pack_size` — how many base units are inside one supplier pack.
3. `shopify_sell_unit` — what one Shopify inventory unit represents.
4. `shopify_inventory_delta_or_set` — the actual quantity Shopify should receive.

Example:

`10 PACK CRYPT ASSORTED EMERSE 3CM | Qty 2 | Subtotal $91.22`

Possible interpretations:

- If Shopify sells the crypts **individually**, supplier pack size = 10, ordered base units = 20, and the cost per individual is `$91.22 / 2 / 10` before any required GST conversion.
- If Shopify has a variant called **10 Pack**, Shopify inventory received is 2 packs and the cost per Shopify unit is `$91.22 / 2` before any required GST conversion.
- If the supplier line is an assorted pack that maps to multiple different Shopify products, do not invent the split. Require a packing list, explicit breakdown, or manual confirmation.

Other examples:

- `PAIR x 6` can mean 6 Shopify pair units or 12 individual fish depending on the Shopify variant.
- `TRIO x 4` can mean 4 trio units or 12 individual fish depending on the Shopify selling unit.
- `12 + 2 FREE` means 14 received base units if all arrived, but cost is allocated over the 14 physical units unless accounting policy says otherwise.
- `BOX OF 24 x 3` means 72 base units only when Shopify sells individual units.

## Discord intake

Treat one Discord thread/message group as one supplier-order job.

Recommended trigger:

`@FRED process supplier order`

Optional operator phrases:

- `ordered` — document is a purchase order/inbound order; do not add available inventory.
- `received` — stock is physically present; inventory may be updated after unit conversion.
- `received partial` — use only quantities explicitly confirmed as received.
- `dry run` — prepare the full proposed change set but make no Shopify writes.

If state is genuinely unclear, default to `ORDERED` rather than falsely increasing available inventory.

## Output

Post a concise Discord reconciliation report containing:

- supplier and order/invoice identifier
- detected GST basis
- number of lines parsed
- exact matches / ambiguous matches / unmatched lines
- pack conversions used
- cost changes
- vendor changes
- retail changes or recommendations
- inventory action and whether it was withheld because the order is not yet received
- duplicate-order status
- Shopify verification result

Flag any line requiring human review rather than guessing.
