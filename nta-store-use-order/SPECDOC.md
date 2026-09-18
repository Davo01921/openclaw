# SPECDOC — NTA StoreUse order

Version: 1.0  
Status: production-enabled with explicit scheduled write gate

Normative words `MUST`, `MUST NOT`, `SHOULD`, and `MAY` indicate requirement strength.

## Objective

The system MUST convert exactly resolved internal StoreUse records into at most one Shopify StoreUse order per Sydney date. The order MUST total `$0.00 AUD`, be paid and fulfilled, retain source and reason information, and decrement affected inventory exactly once.

## Inputs

Each record MUST contain:

- `source_ref`: stable unique source identifier matching the accepted format;
- `variant_id`: exact Shopify ProductVariant GID;
- `quantity`: integer from 1 through 100;
- `reason`: non-empty internal-use reason, maximum 160 characters;
- `location_id`: one verified Shopify location, selected explicitly or unambiguously.

Each record MAY contain:

- `evidence`: concise supporting evidence, maximum 500 characters.

Product title, variant title, SKU, inventory baseline, available quantity, and location name MUST be read authoritatively from Shopify rather than supplied as mutation authority by the reporter.

## Date assignment

The logical batch timezone MUST be `Australia/Sydney`.

- Before 18:00, an intake without an explicit date belongs to the current Sydney date.
- At or after 18:00, it belongs to the next Sydney date.
- The close job MUST target the current Sydney calendar date.

## Queue contract

The queue MUST be durable, date-keyed, atomically written, and protected by an exclusive lock.

Production queue path:

`~/.openclaw/workspace/fred/state/nta-store-use-batches`

The same `source_ref` MUST NOT be appended twice. A closed batch MUST NOT accept additional records.

Multiple records MAY share a Shopify variant. Source references, reasons, and evidence MUST remain distinct in the audit record while mutation quantities MAY be aggregated by variant.

## Order contract

The created Shopify order MUST use:

- customer display identity: `NTA StoreUse`;
- discount label: `NTAStoreUse`;
- discount type: item percentage;
- discount percentage: `100`;
- financial status: `PAID`;
- expected total: `0.00 AUD`;
- source name: `NTA StoreUse`;
- base tags: `NTA StoreUse`, `Store Use`, and `StoreUseBatch-YYYY-MM-DD`;
- one deterministic `StoreUseRef-<hash>` tag per source record;
- inventory behavior: `DECREMENT_OBEYING_POLICY`;
- order and fulfilment receipts disabled.

The order note MUST preserve each record's quantity, item identity, reason, source reference, and evidence.

The order mutation MUST NOT request a separate manual inventory adjustment.

## Fulfilment contract

After order creation, the system MUST freshly read Shopify FulfillmentOrders.

It MUST submit `fulfillmentCreate` using only exact returned FulfillmentOrder IDs, exact FulfillmentOrderLineItem IDs, and positive `remainingQuantity` values.

`notifyCustomer` MUST be false.

Tracking information MUST be omitted unless a separate verified source and policy explicitly authorise it. This workflow provides no such authority.

The system MUST NOT mark the queue closed until a fresh Shopify read reports the order as `FULFILLED`.

## Authentication and capability contract

Production Shopify requests MUST use the persisted offline-session bridge.

The bridge MUST verify offline session identity, expected shop, and token freshness. Secrets MUST NOT be returned in public output.

Before live use, capability checks MUST positively support:

- exact variant and inventory reads;
- order lookup and creation;
- customer lookup;
- merchant-managed fulfilment reads;
- merchant-managed fulfilment writes;
- verified offline authentication.

## Authorization contract

The close mutation MUST require all of:

- the `--execute` command mode;
- `NTA_SHOPIFY_STORE_USE_BATCH_WRITE_ENABLED=true` in the scheduled close process;
- the internal order write gate before `orderCreate`;
- the internal fulfilment write gate before `fulfillmentCreate`;
- all deterministic preflight checks.

The dedicated StoreUse flag MUST NOT be exported globally by the OpenClaw gateway wrapper.

## Idempotency contract

The workflow MUST search Shopify by `StoreUseBatch-YYYY-MM-DD` before writing and again while holding the queue lock.

More than one matching order MUST block.

Each stable source event MUST produce a deterministic `StoreUseRef-<hash>` tag.

An existing fulfilled matching order MAY produce `ALREADY_CLOSED` and synchronize local queue state.

An existing unfulfilled matching order MUST block for manual reconciliation.

An indeterminate result MUST NOT be blindly retried.

## Verification contract

`CLOSED_VERIFIED` MUST require fresh evidence for:

- exactly one order identity;
- `0.00 AUD` total;
- `PAID` financial state;
- `FULFILLED` fulfilment state;
- exact `NTA StoreUse` customer identity;
- daily tag and every source reference;
- expected available-inventory delta per variant;
- expected aggregate inventory-quantity delta per variant.

Failure of any check MUST return a non-success status and MUST NOT be reported as completion.

## Status contract

- `READY`: preview/preflight is valid; no mutation occurred.
- `QUEUED_VERIFIED`: intake was durably stored once.
- `NO_BATCH`: no current open items; no mutation occurred.
- `CLOSED_VERIFIED`: order, fulfilment, and inventory were freshly verified.
- `ALREADY_CLOSED`: an existing fulfilled idempotent order was found.
- `ALREADY_QUEUED` / `ALREADY_COMPLETED`: safe duplicate no-op.
- `BLOCKED`: a safety or authorization prerequisite failed.
- `INDETERMINATE_EXISTING`: an order may exist after an uncertain result; manual review required.
- `FAILED`: Shopify or post-write verification failed.

## Protected state

The workflow MUST NOT alter unrelated products, variants, locations, pricing, descriptions, media, product status, vendor, metafields, collections, or handles.

It MUST NOT perform a second/manual inventory adjustment for the same StoreUse event.

It MUST NOT create or modify Shopify customers or merchant discount configuration.

## Acceptance criteria

The release is acceptable when:

1. Python syntax checks pass;
2. read-only persisted Shopify authentication succeeds;
3. exactly one `NTA StoreUse` customer is resolvable;
4. exact variant and inventory preflight succeeds;
5. dry-run intake returns `READY`;
6. executed queue intake returns `QUEUED_VERIFIED`;
7. replaying the same source reference returns `ALREADY_QUEUED` without duplication;
8. dry-run close returns `READY_TO_CLOSE`;
9. test queue cleanup leaves Shopify inventory unchanged;
10. the active scheduler is exact at 18:00 Australia/Sydney and uses the dedicated StoreUse gate and StoreUse queue trigger;
11. no secret value appears in tracked files or test output;
12. a deliberately authorised real StoreUse batch can create exactly one order, complete `fulfillmentCreate`, and return `CLOSED_VERIFIED` after fresh read-back.
