# SOP — NTA daily death-loss order

Owner: Nano Tanks Australia  
Skill: `nta-death-loss-order`  
Version: 1.3  
Timezone: `Australia/Sydney`  
Daily close: 6:00 pm

## Purpose

Record confirmed livestock deaths once, preserve the evidence, and reduce Shopify inventory exactly once through one paid and fulfilled `$0.00 AUD` loss order per Sydney date.

## Authorised intake

Accept an automatic record only from NTA's configured deaths channel and an authorised staff sender. For another source, present the proposed record to David and wait for approval.

For every loss, capture:

- exact quantity;
- tank identifier;
- fish description;
- cause, or `Unknown` when not stated;
- stable source reference;
- concise supporting evidence.

Never infer a fish from an empty-tank photograph. A photograph or free-form description is evidence, not authority to write to Shopify.

## Intake procedure

1. Resolve the report to one exact active Shopify variant.
2. Require `HIGH` confidence, a positive quantity, one unambiguous inventory location, and enough available stock.
3. Check the stable source reference for an existing completed order or queue entry.
4. If a prior manual inventory deduction is known or suspected, stop for explicit reconciliation.
5. Preview the queue addition without `--execute`.
6. Add the record only after the preview returns `READY`.
7. Confirm the result is `QUEUED_VERIFIED` and report the batch date, fish, tank, and quantity.
8. Tell staff that Shopify inventory remains unchanged until the 6:00 pm close.

## Daily close procedure

The production scheduler checks the current Sydney-date queue at 6:00 pm. It stays silent when no open items exist.

When a batch exists, the fixed command:

1. reacquires a lock and rechecks the queue;
2. searches Shopify for the daily idempotency tag;
3. freshly validates every exact variant, location, and available quantity;
4. resolves exactly one `NTA Losses` customer;
5. creates one order with all queued lines, the `Ntalosses` 100% item discount, `PAID` financial status, receipts disabled, and `DECREMENT_OBEYING_POLICY` inventory behavior;
6. reads Shopify's exact FulfillmentOrder and remaining line-item IDs;
7. calls `fulfillmentCreate` with those IDs and quantities, with customer notification disabled and no invented tracking;
8. freshly rereads the order and affected inventory;
9. marks the local queue closed only after all verification checks pass.

## Successful result

Success is `CLOSED_VERIFIED`. Report:

- the single Shopify order number;
- every recorded fish, tank, and quantity;
- `$0.00 AUD` total;
- paid status;
- fulfilled status;
- the fulfilment result;
- each verified inventory delta.

`ALREADY_CLOSED` is a safe idempotent result only when the existing Shopify order is already fulfilled.

## Stop conditions

Stop without a mutation when any of these applies:

- identity is unresolved, ambiguous, inactive, or below `HIGH` confidence;
- quantity, tank, source reference, customer, or location is invalid;
- inventory is insufficient;
- a possible prior manual deduction is unresolved;
- multiple orders share an idempotency tag;
- the dedicated scheduled write gate is absent;
- persisted offline authentication or required Shopify capability is unverified;
- an existing daily order is not fulfilled;
- Shopify returns a mutation error or an indeterminate result;
- fresh post-write verification fails.

Never blindly retry an indeterminate write. Preserve any existing order number and escalate for reconciliation.

## Prohibited actions

- Do not create individual death orders outside the daily batch.
- Do not make a separate inventory adjustment for the same loss.
- Do not reverse a previous manual adjustment automatically.
- Do not notify the customer or invent tracking information.
- Do not modify product copy, price, media, status, metafields, collections, handles, or unrelated inventory.
- Do not print, copy, or commit credential values.

## Schedule changes

Change the existing OpenClaw scheduler record; do not add a duplicate macOS cron entry. Keep the timezone explicit and keep the job as a fixed command with only the dedicated death-batch gate.
