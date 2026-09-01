# NTA Dropship Polling — Production Activation Runbook

## Objective

Activate automatic detection of new paid Shopify orders containing live `custom.dropship=true` products, while preventing historical/backfill orders from being submitted to suppliers.

## Preconditions

Before enabling write mode:

1. `nta-dropship-order-trigger` v1.1 or later is loaded.
2. `nta-dropship-order-processing` v1.1 or later is loaded.
3. `nta-dropship-supplier-aqua-premium` is configured.
4. Shopify reads can access orders, line items, variants, products and custom metafields.
5. Shopify writes go only through `nta-shopify-write-verifier`.
6. Gmail supplier submission has a durable sent-message ID on success.
7. The runtime has durable storage for checkpoint and idempotency/audit records.

## Activation procedure

1. Record the exact current timestamp as `activation_at` in durable runtime configuration.
2. Set the initial polling checkpoint to the same timestamp.
3. Run one `dry_run` scan with a short overlap and confirm historical candidates are returned only as `HISTORICAL_REVIEW_REQUIRED`.
4. Confirm a no-dropship order is rejected without Shopify mutation.
5. Confirm an eligible test/new order produces a resolved payload containing only unfulfilled dropship lines.
6. Enable `write` mode only after the dry-run output has no unresolved product/supplier mappings.
7. Poll on the runtime's chosen cadence. A five-minute cadence is operationally adequate; the 10-minute overlap in the skill protects against checkpoint/clock edge cases.

## Production decision sequence

For each discovered order:

1. Reject cancelled orders.
2. Require paid/authorised financial state by default.
3. Compare `createdAt` with `activation_at`.
4. Fresh-read every line's product `custom.dropship` and `custom.dropship_supplier`.
5. Exclude lines with zero `unfulfilledQuantity`.
6. If no eligible lines remain, stop with `NO_ELIGIBLE_LINES`.
7. If historical, stop with `HISTORICAL_REVIEW_REQUIRED`.
8. Otherwise dispatch the order identity to `nta-dropship-order-processing`.
9. Never let the trigger itself email the supplier or mutate Shopify.

## Aqua Premium supplier-code rule

A Shopify SKU is not automatically assumed to be an Aqua Premium supplier code. Accept it only when one of these is true:

- an explicit supplier mapping exists; or
- the exact SKU/product pairing has been independently verified against an authoritative Aqua Premium source and the adapter records that evidence.

Example verified during the 2026-09-01 dry run: Aquael Ultra Heater 25W, Shopify SKU `102651`, matches Aqua Premium product code/SKU `102651`.

## Historical order handling

Never bulk-backfill supplier submissions.

A historical order may be manually recovered only after checking for external evidence such as:

- Aqua Premium sent/received email thread;
- Aqua Premium invoice/order reference;
- dispatch/tracking correspondence;
- existing Shopify note/tag/metafield;
- other durable supplier-order evidence.

If evidence is ambiguous, do not resend.

## Current dry-run finding (2026-09-01)

The recent-order scan identified Shopify order `#17154` as a useful regression case:

- paid;
- partially fulfilled;
- multiple products currently marked for Aqua Premium dropship;
- two dropship-labelled lines already have zero unfulfilled quantity and must be excluded;
- Aquael Ultra Heater 25W remains unfulfilled with Shopify SKU `102651`;
- `102651` was independently matched to Aqua Premium's current product code;
- because the order predates production activation, it must remain `HISTORICAL_REVIEW_REQUIRED` and must not be automatically emailed to Aqua Premium.

## Webhook migration later

The connected Shopify app had no `ORDERS_CREATE` or `ORDERS_PAID` shop-scoped webhook subscriptions during the 2026-09-01 check.

When a verified OpenClaw HTTPS webhook receiver is deployed:

1. register `ORDERS_PAID` (preferred default) or deliberately add `ORDERS_CREATE`;
2. verify Shopify origin/signature at the receiver;
3. treat the payload only as a wake-up signal;
4. fresh-read the live Shopify order through this same trigger/processor path;
5. keep the polling job temporarily as a safety net until webhook delivery is proven;
6. then disable routine polling, preserving manual recovery mode.

## Rollback

To stop automatic supplier submissions without losing audit state:

1. disable the polling scheduler/runtime invocation;
2. do not delete checkpoints or idempotency records;
3. leave skills and Shopify metadata intact;
4. investigate any `AMBIGUOUS`, `REVIEW_REQUIRED`, or `HISTORICAL_REVIEW_REQUIRED` jobs manually.
