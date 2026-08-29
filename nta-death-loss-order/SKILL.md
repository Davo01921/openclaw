---
name: "nta-death-loss-order"
description: "Auto-process clear fish/tank matches; clarify only genuine uncertainty."
---

# NTA death loss order

Use when David posts livestock deaths and asks to identify them, record the loss, or update Shopify.

Use the Shopify API access configured for Betta processing. Live Shopify is the source of truth.

## Required workflow

1. Inspect every supplied photo and message. Determine the best-guess species/strain, quantity, and tank if visible or stated.
2. Search live Shopify and match the exact active product and variant. Check nearby candidates and current inventory. Never guess an exact variant when the evidence is ambiguous.
3. When the fish or tank produces a clear exact Shopify match and quantity is known, proceed automatically without asking David for confirmation. Record the identification confidence and evidence in the order note.
4. Create the loss as a Shopify order:
   - customer: `NTA Losses`
   - exact matched variant and identified quantity
   - discount code: `Ntalosses`
   - total: `$0.00 AUD`
   - tags: `NTA Loss`, `Death`, and `Tank {tank}` when known
   - order note: fish, quantity, tank, cause, identification confidence, evidence, and source channel/context
5. Process the order as paid and fulfilled so Shopify records the loss and removes the inventory through the order workflow.
6. Reread the completed order and exact inventory item. Verify customer, line item, quantity, discount, zero total, paid status, fulfilment status, tags, note, and live available/on-hand/committed quantities.
7. Report the order number and verified before/after inventory values.

## Safety rules

- Do not make a separate inventory adjustment for the same death.
- If an earlier manual deduction already occurred, reverse it before processing the loss order, then verify the final net reduction occurs exactly once.
- Do not request confirmation when the fish or tank has a clear exact product/variant match and the quantity is known.
- If identification, quantity, customer, discount, location, or variant remains genuinely uncertain after checking available evidence and live Shopify, stop and ask only for the missing detail.
- If `Ntalosses` does not produce a zero total, do not complete the order.
- Do not report success until a live reread passes every verification.
- Preserve products, prices, descriptions, images, metafields, collections, handles, and status.
