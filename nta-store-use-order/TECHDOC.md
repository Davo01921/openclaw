# TECHDOC — NTA StoreUse order

Version: 1.1  
Runtime owner: Fred/OpenClaw  
Canonical repository: `Davo01921/openclaw-skills`

## System overview

The StoreUse workflow records NTA inventory consumed internally and closes those records as one daily Shopify order.

The production implementation consists of:

1. `SKILL.md`, which defines Fred's operational behavior and safety boundaries;
2. `scripts/daily_batch.py`, which owns date assignment, durable queueing, idempotency, close orchestration, fulfilment, and post-write verification;
3. `scripts/store_use_order.py`, which provides the persisted Shopify session bridge adapter and allowlisted Shopify read/write operations;
4. OpenClaw scheduler `nta-daily-store-use-close-v1`, which conditionally invokes Fred at 6:00 pm Sydney when the current StoreUse queue is open and non-empty.

A model may interpret a staff StoreUse request and identify the intended product, but exact Shopify variant identity, location, inventory state, mutation quantities, fulfilment IDs, and verification evidence are obtained from deterministic Shopify reads.

## Production locations

- Fred deployed skill: `~/.openclaw/agents/fred/agent/workshop-skills/nta-store-use-order`
- Queue state: `~/.openclaw/workspace/fred/state/nta-store-use-batches`
- Canonical repository clone: `~/.openclaw/workspace/fred/openclaw-skills/nta-store-use-order`
- Session bridge: `~/.openclaw/workspace/nta-fred-shopify-auth/nta-betta-picture-processor/scripts/shopify-session-bridge.mjs`
- Existing configuration source: `~/.openclaw/workspace/nta-betta-picture-processor/.env`

Only environment-variable names are documented. Credential values MUST NOT appear in logs, documentation, tests, or commits.

## Scheduler

OpenClaw declaration:

`nta-daily-store-use-close-v1`

Job name:

`NTA daily store use close`

Production configuration:

- enabled: true;
- schedule: `0 18 * * *`;
- timezone: `Australia/Sydney`;
- staggering: disabled;
- session target: `isolated`;
- agent: `fred`;
- model: `openai/gpt-5.6-sol`;
- agent timeout: 600 seconds;
- delivery: Discord channel `1529445740261277807`;
- scheduled tool policy: trusted;
- condition: fire only when the current Sydney-date StoreUse queue has status `OPEN` and contains at least one item.

The agent command is:

`NTA_SHOPIFY_STORE_USE_BATCH_WRITE_ENABLED=true python3 ~/.openclaw/agents/fred/agent/workshop-skills/nta-store-use-order/scripts/daily_batch.py close --execute`

The actual scheduler stores the absolute deployed path.

If the trigger observes no open items, Fred is not invoked.

## Date behavior

`daily_batch.py` uses `Australia/Sydney`.

For intake without an explicit date:

- before 18:00 Sydney, assign the current date;
- at or after 18:00 Sydney, assign the next date.

The scheduled close targets the current Sydney date.

## Durable queue

Queue files are stored under:

`~/.openclaw/workspace/fred/state/nta-store-use-batches`

Each date uses one JSON queue file.

Writes are atomic and protected by a filesystem lock.

Queue records preserve:

- stable source reference;
- deterministic StoreUse reference tag;
- exact Shopify variant ID;
- authoritative product/variant title and SKU;
- quantity;
- reason;
- optional evidence;
- Shopify location ID and name;
- intake inventory quantity;
- intake available quantity;
- queue timestamp.

## Idempotency

Idempotency is enforced with:

- one daily tag: `StoreUseBatch-YYYY-MM-DD`;
- one deterministic hashed tag: `StoreUseRef-<hash>` for each stable source event;
- source-reference checks against completed Shopify orders;
- source-reference checks against the durable queue;
- a pre-write daily-tag lookup;
- another daily-tag lookup while holding the queue lock;
- recovery lookup after uncertain order creation;
- refusal when multiple matching orders exist.

An existing fulfilled matching order is a safe `ALREADY_CLOSED` result.

An existing unfulfilled matching order blocks automatic processing.

## Shopify identity

Customer:

`NTA StoreUse`

The workflow requires exactly one matching Shopify customer.

The tested read-only production preflight resolved exactly one existing customer.

The workflow does not create or modify customers.

## Discount behavior

The order uses an inline 100% item percentage discount labelled:

`NTAStoreUse`

The percentage is supplied directly to `orderCreate`.

The StoreUse workflow does not require creation or modification of a merchant-managed discount object.

## Shopify write sequence

1. Freshly validate each queued variant and inventory location.
2. Aggregate quantities by exact Shopify variant.
3. Resolve exactly one `NTA StoreUse` customer.
4. Run `orderCreate`.
5. Set financial status to `PAID`.
6. Apply `NTAStoreUse` at 100% item percentage.
7. Use `DECREMENT_OBEYING_POLICY`.
8. Disable order and fulfilment receipts.
9. Freshly read Shopify FulfillmentOrders.
10. Submit `fulfillmentCreate` using exact returned IDs and remaining quantities.
11. Set `notifyCustomer: false`.
12. Supply no invented tracking.
13. Freshly reread the completed order.
14. Freshly reread each affected variant/location.
15. Verify both available and aggregate inventory deltas.
16. Mark the queue closed only after all checks pass.

There is no separate manual inventory adjustment.

## Write gates

Three flags form the scoped mutation boundary:

1. `NTA_SHOPIFY_STORE_USE_BATCH_WRITE_ENABLED` authorises the StoreUse daily close.
2. `daily_batch.py` sets `NTA_SHOPIFY_ORDER_WRITE_ENABLED` only inside the authorised close process before `orderCreate`.
3. `daily_batch.py` sets `NTA_SHOPIFY_FULFILMENT_WRITE_ENABLED` only inside the authorised close process before `fulfillmentCreate`.

The dedicated StoreUse gate is checked before the generic child gates are enabled.

The dedicated StoreUse gate MUST NOT be globally exported.

## Authentication

Shopify access uses the existing persisted offline-session bridge.

The bridge verifies the persisted session and expected Shopify shop and does not expose credential values in normal output.

StoreUse reuses the existing allowlisted Shopify transport rather than introducing another token or authentication path.

## Verification and failure semantics

A successful GraphQL response is not completion.

`CLOSED_VERIFIED` requires:

- one matching order;
- `$0.00 AUD`;
- `PAID`;
- `FULFILLED`;
- exact `NTA StoreUse` customer;
- expected daily and source-reference tags;
- expected available inventory decrease;
- expected aggregate inventory quantity decrease.

The workflow fails closed on ambiguous identity, insufficient inventory, missing locations, multiple matching orders, missing write authorization, Shopify errors, missing fulfilment state, or verification mismatch.

An indeterminate order creation MUST be reconciled by lookup rather than blindly retried.

## Production validation completed before activation

The initial StoreUse deployment was validated with non-destructive and local-state tests:

- Python syntax: pass;
- persisted Shopify session: pass;
- exact `NTA StoreUse` customer lookup: one match;
- exact active variant read: pass;
- inventory/location read: pass;
- dry-run StoreUse intake: `READY`;
- executed local queue intake: `QUEUED_VERIFIED`;
- duplicate source-ref replay: `ALREADY_QUEUED`;
- queue item count remained one;
- dry-run close: `READY_TO_CLOSE`;
- test queue removed before production;
- fresh Shopify variant reread confirmed inventory had not changed during testing;
- StoreUse scheduler created disabled and inspected before activation;
- scheduler subsequently enabled and verified at exact 18:00 Australia/Sydney.

No fake Shopify StoreUse order was created during deployment testing.

## Production mutation proof

The complete production path has subsequently been exercised with an authorised real StoreUse event for **1 × Seachem Prime 100 mL**. Intake, execute and daily-close behaviour completed successfully through the StoreUse workflow, providing the production mutation proof that was still pending at initial deployment.

The production contract therefore remains: one idempotent `$0.00 AUD`, paid and fulfilled `NTA StoreUse` order per Sydney date, with Shopify inventory decremented through the order path and verified by fresh read-back. The system must continue to fail closed on ambiguity, missing authorization or verification mismatch.
