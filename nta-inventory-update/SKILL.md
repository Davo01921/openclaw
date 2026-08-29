---
name: "nta-inventory-update"
description: "NTA livestock Shopify intake, cost, market pricing, labels, and live inventory verification."
---

# NTA inventory update

Use when David supplies incoming livestock and asks to update Shopify, review costs or retail pricing, or generate intake labels.

Read [references/workflow.md](references/workflow.md) before making changes.

## Non-negotiable rules

- Treat live Shopify as the source of truth.
- Match an existing product and exact variant; rule out duplicates before creating anything.
- Preserve descriptions, images, handles, collections, category, and status unless explicitly asked to change them.
- Treat inventory as a separate write from vendor, cost, price, and metafield changes.
- Default received quantities to **set**, not add. Add only when David explicitly says add, plus, another, or increase by.
- Pair quantities target the pair variant. Never split pairs into male/female inventory unless explicitly instructed.
- Correct negative/corrupt inventory to the supplied physical quantity and report the exception.
- Never guess storefront handles or URLs.
- Do not change retail based on weak or mismatched market evidence.
- Never report completion until a final live reread confirms expected inventory.

## Workflow

1. Parse vendor, product, size, quantity/unit, supplier cost/unit, arrival date, and tank.
2. Find the live Shopify product; record product ID, actual handle, vendor, status, variants, prices, inventory, cost, and relevant metafields.
3. Identify the exact variant matching each/pair/trio/group.
4. Read its inventory item, Shopify location, available, committed, and on-hand values.
5. Compare supplier cost; write only if different, then verify.
6. Standardise only the relevant product vendor to the supplied vendor name.
7. Review multiple credible Australian like-for-like retail listings. Compare strain, size, sex, pack unit, form, availability, regular/sale price, and bulk/single pricing. Preserve retail unless evidence strongly supports a change.
8. Set inventory at the correct location using the received quantity, comparison value, and reason `received`.
9. Set `custom.arrival_date` to the supplied date or today, and `custom.in_store_location_tank_number` to the supplied tank or `OFFLOCATION1`. Preserve an active tank assignment when NTA rules require it and report why.
10. Generate the requested NTA label format. Intake labels include product, vendor, cost, retail, arrival date, and tank. Physical label count follows the received unit count unless David asks for a shelf label.
11. Reread every changed product and verify vendor, cost, retail, exact variant inventory, metafields, active status, and actual handle.
12. Report changes, pricing evidence/conclusion, expected-versus-live inventory, product links, and genuine exceptions.

## Progress checkpoints

Use these internal checkpoints for batches:

`[1/8] Product matched`
`[2/8] Variant identified`
`[3/8] Inventory read`
`[4/8] Cost/vendor audited`
`[5/8] Market checked`
`[6/8] Shopify updates written`
`[7/8] Labels generated`
`[8/8] Final inventory re-audit passed`

Do not mark `[8/8]` until live inventory matches expected.
