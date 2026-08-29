# Detailed NTA inventory workflow

Owner: Nano Tanks Australia (NTA)  
Source version: 1.0

## Defaults

Unless David specifies otherwise:

- Arrival date: today
- Tank/location: `OFFLOCATION1`
- Vendor: exactly as supplied
- Preserve existing category, status, description, images, handle, collections, and valid historical setup
- Preserve retail unless strong Australian market evidence supports a change
- Update cost only when Shopify differs from supplied cost
- Set inventory to received quantity unless David explicitly requests an addition

## Quantity interpretation

- “10 pairs” means pair-variant inventory = 10.
- Do not create 10 male and 10 female inventory from 10 pairs.
- Individual livestock targets the single/default variant.
- “Arrived” or “received” means set inventory.
- Only “add,” “plus,” “increase by,” or “another … on top” means increment.
- If live inventory is negative or corrupted, set it to the physical received quantity and disclose the correction.

## Live Shopify discovery

Search by product name and confirm:

- exact product title and GID
- actual handle
- vendor and status
- all variants and titles
- retail prices
- inventory
- costs
- relevant metafields

When similar products exist, select the active like-for-like strain and size. Never create a new product until duplicates are ruled out.

## Inventory safety

Before writing, retrieve:

- `inventoryItemId`
- `locationId`
- available
- committed
- on-hand

Record the current available quantity. Update the correct location and variant, pass the current available quantity as comparison value when supported, set the new available quantity, and use reason `received`.

## Cost and vendor

Compare supplier cost in the same unit as the target variant:

- identical: no write; report “Cost already correct”
- different: update and reread to verify

Set the relevant product vendor to the exact supplied name. Do not rename unrelated products or suppliers.

## Australian retail review

Use multiple credible Australian aquarium retailers where possible. Compare like-for-like:

- strain and grade
- size
- sex
- each vs pair vs group
- standard vs ribbon/dumbo/longfin form
- availability
- regular vs sale price
- bulk vs single pricing

Do not blindly use out-of-stock prices or unit-mismatched listings. Change retail only when the evidence is strong; otherwise preserve the live price and provide a recommendation.

## Metafields

Where used, set:

- `custom.arrival_date`: supplied date or today
- `custom.in_store_location_tank_number`: supplied tank or `OFFLOCATION1`

If established NTA rules require preserving an active tank assignment, preserve it and explain that choice.

## Labels

For standard intake labels include:

- product name
- vendor
- cost
- retail
- arrival date
- tank/location

Physical label counts follow received units: 10 pairs = 10 labels, 200 shrimp = 200 labels. If David asks for a two-line livestock shelf label, use the existing NTA two-line convention. Do not mix formats without instruction.

## Mandatory final audit

Reread all changed Shopify products and compare expected versus live for:

- vendor
- cost
- retail
- exact variant inventory
- arrival date
- tank/location
- active status
- actual handle

Fix mismatches before reporting completion. If they cannot be fixed, report an exception and do not call the batch complete.

Use the actual handle to construct:

`https://nanotanksaustralia.com.au/products/{LIVE_SHOPIFY_HANDLE}`

Never derive a handle from the title.

## Completion report

For each product report:

- vendor before → after
- cost before → after, or already correct
- retail before → after, or unchanged
- inventory before → after
- expected vs live with PASS/FAIL
- arrival date
- tank
- actual product link

Also report the observed Australian market range, whether retail changed, recommendation if unchanged, and genuine exceptions such as corrected negative inventory, old handles, duplicates, weak evidence, missing metafields, or variant ambiguity.

A batch succeeds only when every item is correctly matched, costs/vendor are correct, market pricing is reviewed, inventory is written and live-verified, labels are generated, actual links are supplied, and exceptions are disclosed.