---
name: "nta-dropship-order-trigger"
version: "1.1"
description: "Detect recent Shopify orders that may contain dropship items and dispatch them idempotently to the NTA dropship order processor."
---

# NTA Dropship Order Trigger

## Purpose

Provide the runtime-facing entry point for dropship order processing when a direct Shopify webhook receiver is not available. The trigger is deliberately transport-neutral so the same dispatch contract can later be called by Shopify `orders/create` or `orders/paid` webhooks without changing downstream supplier logic.

This module detects candidate orders only. It never sends supplier orders and never decides product eligibility itself; those responsibilities remain with `nta-dropship-order-processing`.

## Supported trigger modes

- `poll` — query recent Shopify orders on a schedule or manual run.
- `webhook` — accept a verified Shopify order event and dispatch the referenced order.
- `manual` — dispatch a specifically supplied Shopify order ID/name for testing or recovery.

Until a verified public webhook receiver exists, use `poll` as the production-compatible fallback.

## Activation boundary

Production configuration MUST set a durable `activation_at` timestamp before automatic supplier hand-off is enabled.

- Orders with `createdAt >= activation_at` may follow normal automatic processing.
- Orders created before `activation_at` are historical/backfill items and MUST NOT automatically submit to a supplier, even when their dropship metadata is valid and no Shopify supplier status is recorded.
- Historical candidates may be evaluated in `dry_run` or `manual` mode and returned as `HISTORICAL_REVIEW_REQUIRED`.
- Changing or removing `activation_at` must not be used to force a resend. A historical order needs an explicit manual recovery decision after checking external supplier evidence.

This boundary protects against duplicate supplier orders that were handled manually before this automation existed.

## Polling contract

Default scan window: orders created or updated since the last successful checkpoint, with a 10-minute overlap to protect against clock skew and delayed writes.

Persist a checkpoint containing:

```yaml
checkpoint:
  activation_at:
  last_successful_scan_at:
  last_seen_order_created_at:
  last_seen_order_id:
```

Never advance the checkpoint past an order whose dispatch result is indeterminate.

## Candidate query

Read recent orders from Shopify including at minimum:

- order ID and name
- created/updated timestamps
- cancelled state
- payment/financial status
- tags
- `custom.dropship_status`
- `custom.supplier_order_number`
- all line-item IDs, quantities and exact product/variant identities
- live product `custom.dropship`
- live product `custom.dropship_supplier`

The runtime may use Shopify GraphQL, a native Shopify connector, or an equivalent verified store adapter. It must read live product metafields; vendor name alone is not a qualification signal.

### Validated Shopify Admin GraphQL read shape

This query shape was schema-validated against the connected Shopify Admin API on 2026-09-01:

```graphql
query DropshipDryRun($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on Order {
      id
      name
      createdAt
      updatedAt
      cancelledAt
      displayFinancialStatus
      displayFulfillmentStatus
      tags
      dropshipStatus: metafield(namespace: "custom", key: "dropship_status") {
        value
        type
      }
      supplierOrderNumber: metafield(namespace: "custom", key: "supplier_order_number") {
        value
        type
      }
      lineItems(first: 50) {
        nodes {
          id
          title
          variantTitle
          sku
          currentQuantity
          unfulfilledQuantity
          product {
            id
            title
            vendor
            dropship: metafield(namespace: "custom", key: "dropship") {
              value
              type
            }
            dropshipSupplier: metafield(namespace: "custom", key: "dropship_supplier") {
              value
              type
            }
          }
          variant {
            id
            title
            sku
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
  }
}
```

If `lineItems.pageInfo.hasNextPage` is true, the candidate is incomplete until all pages are read. Do not make a supplier hand-off decision from a truncated order.

## Fast rejection rules

Skip without downstream dispatch when any of the following is true:

1. order is cancelled;
2. order contains no current line whose product has `custom.dropship == true`;
3. `custom.dropship_status == SUPPLIER_ACKNOWLEDGED`;
4. `custom.dropship_status == SENT_TO_SUPPLIER` and there is durable supplier submission evidence for the same idempotency key;
5. every qualifying line has zero current/unfulfilled quantity.

Do not use `supplier_order_number` alone to infer fulfilment.

An order older than `activation_at` is not a fast rejection; return `HISTORICAL_REVIEW_REQUIRED` so it remains visible without automatic submission.

## Dispatch rules

For every remaining candidate created at or after `activation_at`:

1. Create an orchestrator job with `source: shopify` and workflow `nta-dropship-order-processing`.
2. Use Shopify order ID as the trigger correlation key.
3. Pass the exact order identity; do not copy supplier logic into this trigger.
4. Let `nta-dropship-order-processing` recalculate the line-level idempotency key from the live order.
5. Record the returned state for the polling checkpoint/audit log.

## Webhook compatibility

When a webhook receiver is introduced, require Shopify-origin verification before accepting the event. A webhook event is only a wake-up signal: after verification, re-read the complete live Shopify order before processing. Never trust webhook payload line data as the sole source of truth for current dropship metafields or fulfilment state.

Recommended events:

- `orders/create` for earliest detection; and/or
- `orders/paid` when NTA chooses to require payment before supplier submission.

The business rule controlling whether an unpaid order may be sent must be explicit. Default production policy for this module is **paid/authorised orders only** unless NTA deliberately configures otherwise.

## Duplicate-event protection

Shopify can deliver duplicate events and polling can rediscover the same order. Duplicate detection therefore occurs at two layers:

- trigger layer: Shopify order ID + event/checkpoint history;
- processor layer: Shopify order ID + supplier + sorted qualifying line-item IDs.

A trigger-layer duplicate may safely dispatch for re-evaluation only if the processor can independently prove no successful external hand-off exists.

## Failure handling

- Shopify read failure: `BLOCKED`, retain checkpoint.
- Partial line-item/metafield read: `REVIEW_REQUIRED`, do not send supplier request.
- Historical qualifying order: `HISTORICAL_REVIEW_REQUIRED`, no automatic supplier submission.
- Processor returns `AMBIGUOUS`/`BLOCKED`/`REVIEW_REQUIRED`: retain the affected order in the retry/review queue and do not advance irreversibly past it.
- Processor returns `NO_ELIGIBLE_LINES`, `SENT_TO_SUPPLIER`, or `SUPPLIER_ACKNOWLEDGED`: record result and continue.

## Output

```yaml
trigger_result:
  mode: poll | webhook | manual
  activation_at:
  scan_started_at:
  scan_completed_at:
  orders_scanned:
  candidates_dispatched:
  skipped:
    no_dropship_lines:
    cancelled:
    already_sent:
    acknowledged:
  historical_review_orders: []
  review_orders: []
  blocked_orders: []
  checkpoint_committed: true | false
```

## Safety boundary

This trigger never:

- emails a supplier;
- mutates Shopify;
- marks fulfilment;
- invents a supplier SKU;
- retries an ambiguous external submission;
- auto-submits historical orders from before `activation_at`.

All consequential actions remain in the specialist processor and supplier adapter behind `nta-shopify-write-verifier`.