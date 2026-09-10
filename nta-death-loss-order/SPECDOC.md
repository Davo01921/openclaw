# SPECDOC — NTA death-loss order

Version: 1.3  
Status: production-enabled with explicit scheduled write gate

Normative words `MUST`, `MUST NOT`, `SHOULD`, and `MAY` indicate requirement strength.

## Objective

The system MUST convert authorised, exactly resolved livestock-loss records into at most one Shopify loss order per Sydney date. The order MUST total `$0.00 AUD`, be paid and fulfilled, retain source evidence, and decrement affected inventory exactly once.

## Inputs

Each record MUST contain:

- `source_ref`: stable unique source identifier;
- `variant_id`: exact Shopify ProductVariant GID;
- `quantity`: integer from 1 through 100;
- `tank`: valid tank identifier;
- `fish`: non-empty fish description;
- `cause`: stated cause or `Unknown`;
- `evidence`: non-empty concise evidence;
- `confidence`: exactly `HIGH`;
- `location_id`: one verified Shopify location, selected explicitly or unambiguously.

`prior_manual_deduction` MUST be false for automatic processing. A true or uncertain value MUST stop for reconciliation.

## Date assignment

The logical batch timezone MUST be `Australia/Sydney`.

- Before 18:00, an intake without an explicit date belongs to the current Sydney date.
- At or after 18:00, it belongs to the next Sydney date.
- The close job MUST target the current Sydney calendar date.

## Queue contract

The queue MUST be durable, date-keyed, atomically written, and protected by an exclusive lock.

The same `source_ref` MUST NOT be appended twice. A closed batch MUST NOT accept additional records. Multiple records MAY share a variant, but the source/tank/evidence records MUST remain distinct while mutation quantities MAY be aggregated by variant.

## Order contract

The created Shopify order MUST use:

- customer display identity: `NTA Losses`;
- discount code: `Ntalosses`;
- discount type: item percentage;
- discount percentage: `100`;
- financial status: `PAID`;
- expected total: `0.00 AUD`;
- source name: `NTA Losses`;
- base tags: `NTA Loss`, `Death`, and `DeathBatch-YYYY-MM-DD`;
- one deterministic reference tag per source record;
- inventory behavior: `DECREMENT_OBEYING_POLICY`;
- order and fulfilment receipts disabled.

The note MUST preserve each record's quantity, fish, tank, cause, source reference, and evidence. The order mutation MUST NOT request inline fulfilment in the deployed two-stage workflow.

## Fulfilment contract

After order creation, the system MUST freshly read Shopify FulfillmentOrders. It MUST submit `fulfillmentCreate` using only exact returned FulfillmentOrder IDs, exact FulfillmentOrderLineItem IDs, and positive `remainingQuantity` values.

`notifyCustomer` MUST be false. Tracking information MUST be omitted unless a separate verified source and policy explicitly authorise it; this workflow does not provide such authority.

The system MUST NOT mark the queue closed until a fresh Shopify read reports the order as `FULFILLED`.

## Authentication and capability contract

Production requests MUST use the persisted offline-session bridge. The bridge MUST verify offline session identity, expected shop, and token freshness. Secrets MUST NOT be returned in public output.

Before live use, capability checks MUST positively observe:

- order read/write capability;
- a qualifying merchant-managed fulfilment read scope;
- a qualifying merchant-managed fulfilment write scope;
- inventory read capability;
- verified offline authentication.

## Authorization contract

The close mutation MUST require all of:

- the `--execute` command mode;
- `NTA_SHOPIFY_DEATH_BATCH_WRITE_ENABLED=true` in the fixed scheduled process;
- the internal order write gate before `orderCreate`;
- the internal fulfilment write gate before `fulfillmentCreate`;
- all deterministic preflight checks.

The dedicated flag MUST NOT be exported globally by the OpenClaw gateway wrapper.

## Idempotency contract

The workflow MUST search Shopify by the daily tag before writing and again under the queue lock. More than one match MUST block.

An existing fulfilled matching order MAY produce `ALREADY_CLOSED` and synchronize local queue state. An existing unfulfilled matching order MUST block for manual reconciliation. An indeterminate result MUST NOT be blindly retried.

## Verification contract

`CLOSED_VERIFIED` MUST require fresh evidence for:

- exactly one order identity;
- `0.00 AUD` total;
- `PAID` financial state;
- `FULFILLED` fulfilment state;
- exact `NTA Losses` customer identity;
- daily tag and every source reference;
- expected available-inventory delta per variant;
- expected aggregate inventory-quantity delta per variant.

Failure of any check MUST return a non-success status and MUST NOT be reported as completion.

## Status contract

- `READY`: a preview/preflight is valid; no mutation occurred.
- `QUEUED_VERIFIED`: intake was durably stored once.
- `NO_BATCH`: no current open items; no mutation occurred.
- `CLOSED_VERIFIED`: order, fulfilment, and inventory were freshly verified.
- `ALREADY_CLOSED`: an existing fulfilled idempotent order was found.
- `ALREADY_QUEUED` / `ALREADY_COMPLETED`: safe duplicate no-op.
- `BLOCKED`: a safety or authorization prerequisite failed.
- `INDETERMINATE_EXISTING`: an order may exist after an uncertain result; manual review required.
- `FAILED`: Shopify or post-write verification failed.

## Protected state

The workflow MUST NOT alter unrelated products, variants, locations, pricing, descriptions, media, product status, vendor, metafields, collections, or handles. It MUST NOT perform a second/manual inventory adjustment for the same loss.

## Acceptance criteria

The release is acceptable when:

1. all deterministic dry runs and bridge self-tests pass;
2. the read-only capability probe verifies persisted offline authentication and required scopes;
3. the active scheduler is a fixed 18:00 Sydney command with the dedicated gate only;
4. no secret value appears in tracked files or test output;
5. a deliberately authorised production batch can create exactly one order, complete `fulfillmentCreate`, and return `CLOSED_VERIFIED` after fresh read-back.
