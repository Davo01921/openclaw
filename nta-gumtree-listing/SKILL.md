---
name: "nta-gumtree-listing"
description: "Create Nano Tanks Australia Gumtree livestock ads from current Shopify product data."
---

# NTA Gumtree listing

Use when David asks to create or prepare a Gumtree ad for a Nano Tanks Australia livestock product.

## Workflow

1. Use the browser-automation skill and the connected Chrome profile.
2. Find the exact product on nanotanksaustralia.com.au or the open Shopify admin.
3. Read current product data before drafting:
   - exact product name and URL
   - current price and available quantity tiers
   - availability
   - description, livestock size, benefits, care parameters, shipping restrictions
   - primary product image
4. Draft a clear Gumtree title and sales-focused description. Keep claims faithful to the product page.
5. Gumtree descriptions accept only basic English/ASCII characters. Use plain hyphens, straight quotes, and ASCII units. Avoid bullets such as "•", en/em dashes, degree symbols, and decorative emoji.
6. Include this pickup block in every description:

   Nano Tanks Australia
   41 Croydon Ave
   Croydon NSW 2132

7. Create the Gumtree listing using:
   - category: Fish
   - state: NSW
   - location field: Croydon NSW 2132 (select Gumtree's validated suburb result)
   - website: exact product URL
   - price: current per-unit or lowest advertised price
   - no paid add-ons unless David explicitly requests them
8. Choose required Fish attributes accurately:
   - shrimp: quantity 1 when price is per shrimp, gender Both, type Crustacea
   - other livestock: choose the closest truthful options; do not invent details
9. Download the primary Shopify product image. Convert AVIF/WebP to JPEG if needed, place the upload copy in OpenClaw's inbound media directory, and attach it as the main photo.
10. Verify title, Fish category, price, photo, description, address block, website, attributes, and validated Croydon location.
11. Select Save & close and verify the Gumtree page shows the listing under "Continue" as a saved draft.
12. Do not click Post ad or select paid upgrades without David's explicit confirmation in the current conversation.

## Reporting

Report the saved draft's title, price, category, attributes, address inclusion, photo status, and that it was not published. Mention any Gumtree field limitation or substituted closest-fit attribute.
