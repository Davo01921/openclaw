# SOP — NTA daily StoreUse order

Owner: Nano Tanks Australia  
Skill: `nta-store-use-order`  
Version: 1.0  
Timezone: `Australia/Sydney`  
Daily close: 6:00 pm

## Purpose

Record products consumed internally by Nano Tanks Australia once, preserve the reason and source reference, and reduce Shopify inventory exactly once through one paid and fulfilled `$0.00 AUD` StoreUse order per Sydney date.

## Authorised intake

A StoreUse record must identify a real NTA product consumed for internal business use.

For every StoreUse record, capture:

- exact Shopify variant;
- exact positive quantity;
- reason for internal use;
- stable source reference;
- concise supporting evidence when available;
- one verified Shopify inventory location.

Examples of reasons include showroom use, tank maintenance, packing use, equipment maintenance, testing, or another explicit internal business purpose.

Never infer an item, variant, quantity, or reason when the report is ambiguous.

## Intake procedure

1. Identify one exact active Shopify ProductVariant.
2. Require a positive quantity, a non-empty reason, one unambiguous inventory location, and enough available stock.
3. Check the stable source reference for an existing completed StoreUse order or queue entry.
4. Preview the queue addition without `--execute`.
5. Add the record only after the preview returns `READY`.
6. Confirm the result is `QUEUED_VERIFIED` and report the batch date, item, quantity, and reason.
7. Tell staff that Shopify inventory remains unchanged until the 6:00 pm close.

StoreUse intake does not perform a manual inventory adjustment.

## Daily close procedure

The production scheduler checks the current Sydney-date StoreUse queue at 6:00 pm. It does not invoke Fred when no open items exist.

When a batch exists, the close process:

1. reacquires the queue lock and rechecks the queue;
2. searches Shopify for the daily idempotency tag;
3. freshly validates every exact variant, location, and available quantity;
4. resolves exactly one `NTA StoreUse` customer;
5. creates one order with all queued lines, the `NTAStoreUse` 100% item discount, `PAID` financial status, receipts disabled, and `DECREMENT_OBEYING_POLICY` inventory behavior;
6. reads Shopify's exact FulfillmentOrder and remaining line-item IDs;
7. calls `fulfillmentCreate` with those IDs and quantities, with customer notification disabled and no invented tracking;
8. freshly rereads the order and affected inventory;
9. marks the local queue closed only after all verification checks pass.

## Successful result

Success is `CLOSED_VERIFIED`. Report:

- the single Shopify order number;
- every StoreUse item, quantity, and reason;
- `$0.00 AUD` total;
- paid status;
- fulfilled status;
- the fulfilment result;
- each verified inventory delta.

`ALREADY_CLOSED` is a safe idempotent result only when the existing matching Shopify order is already fulfilled.

## Stop conditions

Stop without a mutation when any of these applies:

- variant identity is unresolved, ambiguous, or inactive;
- quantity, reason, source reference, customer, or location is invalid;
- inventory is insufficient;
- multiple orders share an idempotency tag;
- the dedicated StoreUse scheduled write gate is absent;
- persisted offline authentication or required Shopify capability is unverified;
- an existing daily order is not fulfilled;
- Shopify returns a mutation error or an indeterminate result;
- fresh post-write verification fails.

Never blindly retry an indeterminate write. Preserve any existing order number and escalate for reconciliation.

## Prohibited actions

- Do not create individual completed StoreUse orders outside the daily batch.
- Do not make a separate manual inventory adjustment for an item handled by this workflow.
- Do not notify the customer or invent tracking information.
- Do not create or modify Shopify customers as part of StoreUse processing.
- Do not create or modify merchant discount configuration as part of StoreUse processing.
- Do not modify product copy, price, media, status, metafields, collections, handles, or unrelated inventory.
- Do not print, copy, or commit credential values.

## Schedule changes

Change the existing OpenClaw scheduler record; do not add a duplicate scheduler or macOS cron entry.

The production declaration key is `nta-daily-store-use-close-v1`. Keep the timezone explicit, the StoreUse queue trigger intact, and the dedicated StoreUse batch write gate scoped only to the close process.
