---
name: "nta-gumtree-listing"
description: "Prepare and track Nano Tanks Australia Gumtree livestock ads from current Shopify data using a deterministic manual-post operator queue."
---

# NTA Gumtree listing

Use when David asks to prepare, review, queue, record, or verify Gumtree ads for Nano Tanks Australia.

## Safety boundary

This skill does **not** automate Gumtree. It must not use Playwright, Selenium, Puppeteer, browser macros, scraping, private endpoints, or account automation against Gumtree unless Gumtree has explicitly approved an integration for this account and workflow.

The production model is:

`Shopify -> deterministic Python/registry -> operator queue -> David manually posts on Gumtree -> listing ID/URL recorded -> verification`

Hard rules:
- Gumtree posting is manual.
- No automated Gumtree draft creation, editing, publishing, pausing, deletion, relisting, or paid promotion.
- `publish_authority` is always `false`.
- `browser_automation` is always `false`.
- Queue generation is Thursday, Friday, and Saturday only in `Australia/Sydney`.
- Maximum three queue items per day.
- Sunday-Wednesday live runs return zero items.
- Unconfigured, uncertain, malformed, duplicate, or unmapped products fail closed.
- Existing Gumtree listing IDs cannot be silently remapped to another NTA advertisement.

## Shopify configuration

The twelve supported `nta.*` Gumtree metafields are:
1. `nta.gumtree_policy`
2. `nta.gumtree_priority`
3. `nta.gumtree_min_stock`
4. `nta.gumtree_stockout_policy`
5. `nta.gumtree_stockout_grace_days`
6. `nta.gumtree_price_override`
7. `nta.gumtree_title_override`
8. `nta.gumtree_description_override`
9. `nta.gumtree_desired_listing_count`
10. `nta.gumtree_campaign_start`
11. `nta.gumtree_campaign_end`
12. `nta.gumtree_availability_override`

`gumtree_availability_override` accepts only `AVAILABLE` or `UNAVAILABLE`. It is supplemental evidence and does not grant listing authority without a valid `gumtree_policy`.

## Production workflow

1. Obtain current Shopify product data through the approved/read-only Shopify adapter boundary.
2. Normalize identity, status, inventory, Gumtree metafields, price, description, images and any truthful Gumtree attributes.
3. Read the local SQLite registry.
4. Classify configuration and resolve deterministic availability.
5. Resolve the existing product-to-ad mapping. Only `MAPPED` or `MANAGED` products may enter the queue.
6. Build a frozen reconciliation snapshot and deterministic listing input.
7. Run `gumtree_queue_runner.py`, which calls the live Sydney-date queue guard.
8. Present at most three `READY_TO_POST` packages containing title, description, price, category, location, images and attributes.
9. David manually creates/posts the ad on Gumtree.
10. Record David's supplied Gumtree listing ID or URL with source `MANUAL_OPERATOR`.
11. Move the operator item from `READY_TO_POST` to `POSTED`.
12. After explicit successful verification, move `POSTED` to `VERIFIED`.

## Operator queue

Default command from the skill directory:

```bash
PYTHONPATH=scripts python3 scripts/gumtree_queue_runner.py \
  --input data/current-shopify-products.json \
  --db data/gumtree.db \
  --output data/operator-queue.json
```

The input must contain current normalized Shopify records. A product that lacks required description, price, image, identity, configuration, mapping, or trustworthy availability will be skipped rather than guessed.

## Registry

Runtime database: `data/gumtree.db`.

Runtime database files, queue artifacts, and backups are ignored by Git. Before material registry changes, create a local SQLite backup:

```bash
PYTHONPATH=scripts python3 scripts/gumtree_registry_backup.py \
  --db data/gumtree.db \
  --backup-dir data/backups
```

Manual existing-listing bootstrap uses `gumtree_manual_bootstrap.py`. Operator-supplied listings are recorded with source `MANUAL_OPERATOR`. A listing ID already mapped to a different `GT-NTA-*` ad must be rejected, not reassigned.

## Description/content rules

- Keep claims faithful to current Shopify facts.
- Use plain, readable Gumtree-safe text.
- Default category is `Fish` unless a more accurate configured category is supplied.
- Default location is `Croydon NSW 2132`.
- Never invent animal sex, quantity, size, availability, price, care parameters, shipping claims or stock.
- Product images must come from current approved Shopify data; if no valid image is available, block the item.

## Reporting

For each live queue run report:
- Sydney run date and whether it is an allowed day;
- number of `READY_TO_POST` items;
- skipped count and snapshot errors;
- each item's title, price, category, location and image count;
- `publish_authority: false`;
- `browser_automation: false`;
- `manual_post_only: true`.

When David supplies a Gumtree listing ID/URL after posting, record it and report the resulting registry instance ID and lifecycle state. Do not claim an ad is verified until verification explicitly succeeds.
