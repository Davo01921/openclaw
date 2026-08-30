---
name: "nta-inventory-update"
description: "NTA livestock Shopify intake, cost, market pricing, preorder state, labels, and live inventory verification."
---

# NTA inventory update

Use when David supplies incoming livestock and asks to update Shopify, review costs or retail pricing, manage preorder state, or generate intake labels.

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
- Preorder behaviour is variant-level. Use `custom.preorder_eligible` and `custom.preorder_status_override`.
- Valid preorder overrides are `automatic`, `eta_tbc`, and `disabled` only.
- Bettas and other individually identified one-off livestock are never preorder eligible.
- Clearance, discontinued, internal-use, explicitly one-off, and clearly non-replenishable products must not be auto-enabled for preorder.
- Do not infer a confirmed ETA from a supplier order. If supply timing is uncertain, use `eta_tbc` rather than pretending a normal preorder ETA exists.

## Preorder decision engine

For each exact Shopify variant, resolve preorder state after inventory and supplier status are known:

1. If the product is a Betta, individually photographed/numbered livestock, discontinued, clearance, internal-use, explicitly one-off, or otherwise non-replenishable:
   - `custom.preorder_eligible = false`
   - `custom.preorder_status_override = disabled` when an explicit hard stop is required
   - inventory policy must not be switched to `CONTINUE` merely to keep it purchasable.
2. If the product is a normal replenishable line and stock is available:
   - keep `custom.preorder_eligible = true`
   - use `custom.preorder_status_override = automatic` unless a temporary exception is active.
3. If the product is replenishable, inventory is `<= 0`, and normal replenishment is reasonably expected:
   - `custom.preorder_eligible = true`
   - inventory policy = `CONTINUE`
   - `custom.preorder_status_override = automatic`
   - storefront state should resolve to **Pre-order**.
4. If the product is replenishable and can still be ordered but the supplier/restock date is uncertain or may be delayed for an extended period:
   - `custom.preorder_eligible = true`
   - inventory policy = `CONTINUE`
   - `custom.preorder_status_override = eta_tbc`
   - storefront state should resolve to **Available to Order – ETA TBC**.
5. When reliable supply resumes or received stock moves above zero, return `eta_tbc` to `automatic` unless David explicitly wants the warning retained.
6. If the supplier confirms the item cannot currently be sourced, is discontinued, or NTA decides not to accept further orders:
   - set `custom.preorder_status_override = disabled`
   - stop overselling by using inventory policy `DENY` where appropriate.

Never use inventory quantity alone to decide whether a product is permanently orderable.

## Workflow

1. Parse vendor, product, size, quantity/unit, supplier cost/unit, arrival date, tank, and any supplier availability/ETA information.
2. Find the live Shopify product; record product ID, actual handle, vendor, status, variants, prices, inventory, cost, inventory policy, `custom.preorder_eligible`, `custom.preorder_status_override`, and relevant metafields.
3. Identify the exact variant matching each/pair/trio/group.
4. Read its inventory item, Shopify location, available, committed, and on-hand values.
5. Compare supplier cost; write only if different, then verify.
6. Standardise only the relevant product vendor to the supplied vendor name.
7. Review multiple credible Australian like-for-like retail listings. Compare strain, size, sex, pack unit, form, availability, regular/sale price, and bulk/single pricing. Preserve retail unless evidence strongly supports a change.
8. Set inventory at the correct location using the received quantity, comparison value, and reason `received`.
9. Run the **Preorder decision engine** and update inventory policy / preorder metafields only when the product class and supplier state justify it.
10. Set `custom.arrival_date` to the supplied date or today, and `custom.in_store_location_tank_number` to the supplied tank or `OFFLOCATION1`. Preserve an active tank assignment when NTA rules require it and report why.
11. Generate the requested NTA label format. Intake labels include product, vendor, cost, retail, arrival date, and tank. Physical label count follows the received unit count unless David asks for a shelf label.
12. Reread every changed product and verify vendor, cost, retail, exact variant inventory, inventory policy, preorder metafields, active status, and actual handle.
13. Report changes, pricing evidence/conclusion, expected-versus-live inventory, preorder state, product links, and genuine exceptions.

## Progress checkpoints

Use these internal checkpoints for batches:

`[1/9] Product matched`
`[2/9] Variant identified`
`[3/9] Inventory read`
`[4/9] Cost/vendor audited`
`[5/9] Market checked`
`[6/9] Shopify updates written`
`[7/9] Preorder state resolved`
`[8/9] Labels generated`
`[9/9] Final inventory + preorder re-audit passed`

Do not mark `[9/9]` until live inventory, inventory policy, and preorder metafields match expected state.
