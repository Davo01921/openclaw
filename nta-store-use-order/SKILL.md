---
name: "nta-store-use-order"
description: "NTA products consumed for internal store use: queue verified inventory usage locally, then create one idempotent paid/fulfilled Shopify StoreUse order at 6 pm Sydney."
---

# NTA daily store-use order

1. Accept a StoreUse report only when the item, quantity, and internal-use intent are clear. Record a concise reason such as `Showroom use`, `Tank maintenance`, `Packing use`, or another explicit reason. Never infer an item or quantity when ambiguous; complete only when the intended product and quantity are known.

2. Identify the exact active Shopify variant for the reported item. StoreUse may apply to any inventory-tracked NTA product. Never choose between ambiguous variants automatically. Complete only when one exact `gid://shopify/ProductVariant/...` is established.

3. Build a stable `source_ref` for every StoreUse event. For Discord reports, prefer `discord-<channel_id>-<message_id>` and append a stable item suffix when one message contains multiple StoreUse records. Never reuse a source reference for a different event.

4. Run `python3 {baseDir}/scripts/daily_batch.py add` without `--execute`, supplying the exact variant ID, quantity, source ref, reason, and optional concise evidence/location ID. Complete when the item returns `READY`, `ALREADY_QUEUED`, or `ALREADY_COMPLETED`.

5. For each `READY` item, rerun the identical command with `--execute`. The helper must append it once to the Sydney-date durable StoreUse queue with its source reference, exact variant, reason, inventory baseline, and Shopify location. Complete only when it returns `QUEUED_VERIFIED`.

6. Report the batch date and queued StoreUse item/quantity/reason. State that Shopify inventory remains unchanged until the daily StoreUse order closes at 6:00 pm. Never make a separate inventory adjustment or individual completed StoreUse order.

7. At 6:00 pm Australia/Sydney, run `NTA_SHOPIFY_STORE_USE_BATCH_WRITE_ENABLED=true python3 {baseDir}/scripts/daily_batch.py close --execute`. Create one idempotent Shopify order for all queued StoreUse items under customer `NTA StoreUse`, apply `NTAStoreUse` at 100%, mark it paid and fulfilled without customer notification, and use Shopify's order inventory decrement. For `NO_BATCH`, stay silent.

8. Reread the completed order and every affected variant. Complete only when the helper returns `CLOSED_VERIFIED`; report the single order number, all StoreUse items/quantities/reasons, $0.00 AUD total, paid/fulfilled status, and each verified inventory delta.

## Safety boundaries

- Never create an individual completed StoreUse order; StoreUse inventory is deducted only through the daily batch close.
- Never make a separate manual inventory deduction for an item queued through this skill.
- Never process an ambiguous variant, missing quantity, missing reason, missing location, inactive product, or insufficient inventory at intake or close.
- Never merge audit details: preserve every source reference and reason in the order note even when multiple StoreUse records share a Shopify variant.
- Never create more than one completed StoreUse order for a Sydney batch date.
- Never perform the close mutation unless `NTA_SHOPIFY_STORE_USE_BATCH_WRITE_ENABLED=true` is explicitly scoped to the scheduled close process.
- Never change products, variants, prices, descriptions, images, metafields, collections, handles, or product status.
- Never create or modify Shopify customers or merchant discount configuration as part of this workflow.
- Never expose Shopify credentials or print environment-file contents.
