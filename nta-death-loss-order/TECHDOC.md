# TECHDOC — NTA death-loss order
**Closeout status (2026-10-02): READY FOR FINAL LIVE ACCEPTANCE.** See [evidence and the single scheduled acceptance action](docs/CLOSEOUT.md).


Version: 1.4.1
Runtime owner: Fred/OpenClaw  
Canonical repository: `Davo01921/openclaw-skills`

## System overview

The workflow has two layers:

1. Repository policy and deterministic planning in `nta-death-loss-order`, `nta-shopify-order-writer`, `nta-shopify-fulfilment-writer`, and their auditors.
2. Fred's deployed daily-batch helper, which owns the durable queue, fixed 6:00 pm close, Shopify orchestration, and fresh verification.

The production scheduler invokes deterministic code directly. A model may interpret intake evidence, but it does not choose Shopify mutation inputs or live retry behavior.

## Production locations

- Fred skill: `~/.openclaw/agents/fred/agent/workshop-skills/nta-death-loss-order`
- Queue state: `~/.openclaw/workspace/fred/state/nta-death-loss-batches`
- Session bridge: `~/.openclaw/workspace/nta-fred-shopify-auth/nta-betta-picture-processor/scripts/shopify-session-bridge.mjs`
- Private validated non-secret config: `~/.openclaw/workspace/fred/config/nta-death-loss.json`
- Existing credential source: `~/.openclaw/workspace/nta-betta-picture-processor/.env`

Only environment-variable names are documented. Credential values must never appear in logs, documentation, tests, or commits.

## Scheduler

OpenClaw job: `NTA daily deaths close`

- schedule: `0 18 * * *`;
- timezone: `Australia/Sydney`;
- staggering: disabled;
- payload: fixed command, not an agent turn;
- command: absolute Python executable and `scripts/scheduled_close.py --config <private-config> --execute`;
- condition: the wrapper handles an empty queue without auth/network and emits native `NO_REPLY`; no AI trigger is retained;
- delivery: configured deaths channel;
- timeout: 600 seconds, with the helper child bounded to 540 seconds.

The job environment scopes the dedicated non-secret authorization flag `NTA_SHOPIFY_DEATH_BATCH_WRITE_ENABLED=true` and pins the existing bridge executable through `NTA_SHOPIFY_SESSION_BRIDGE_NODE`. The gateway-wide generic fulfilment gate remains unset.

## Authentication

All production Shopify traffic uses the local allowlisted session bridge.

The bridge:

- loads one persisted offline Shopify session;
- verifies offline identity and expected shop;
- checks token expiry;
- rotates an expiring token under a filesystem lock when a refresh token is available;
- stores rotated credentials back into the session database;
- returns only safe authentication attestations;
- never returns access-token or refresh-token values.

Supported configuration aliases are:

- `SHOPIFY_STORE` or the bridge's domain aliases;
- `SHOPIFY_CLIENT_ID` or `SHOPIFY_API_KEY`;
- `SHOPIFY_CLIENT_SECRET` or `SHOPIFY_API_SECRET`.

No duplicate permanent Admin API token is introduced.

## Allowlisted operations

The death-loss path uses only named bridge operations for:

- product search;
- exact variant read;
- existing-order lookup;
- customer lookup;
- capability query;
- order creation;
- order fulfilment-state read;
- fulfilment creation;
- exact inventory/fulfilment verification reads.

Arbitrary GraphQL supplied by a model is not accepted.

## Write gates

Three flags form a scoped boundary:

1. `NTA_SHOPIFY_DEATH_BATCH_WRITE_ENABLED` authorises only the scheduled death-batch close process.
2. The deterministic helper sets `NTA_SHOPIFY_ORDER_WRITE_ENABLED` only in the bridge child environment after authorizing `orderCreate`.
3. The helper sets `NTA_SHOPIFY_FULFILMENT_WRITE_ENABLED` only in the bridge child environment after authorizing `fulfillmentCreate`.

The bridge independently rejects order or fulfilment mutations when the corresponding generic gate is absent. An order request that attempts inline fulfilment also requires the fulfilment gate.

## Durable queue and idempotency

Queue files are keyed by Sydney date and written atomically through a temporary file plus rename. A filesystem lock serializes intake, amendments and close operations. Planning is done after acquiring that same lock. Stable record IDs are derived from legacy source references; existing queues require no bulk conversion.

Idempotency is enforced with:

- one daily tag: `DeathBatch-YYYY-MM-DD`;
- one hashed reference tag per stable source event;
- a pre-write Shopify lookup;
- a second lookup while holding the queue lock;
- post-error recovery lookup;
- refusal when multiple matching orders exist.

Mutation intent and the frozen inventory baseline are persisted before creation; exact order identity and fulfilment intent are persisted before the next mutation. The queue is not marked closed for an unverified partial result. Recovery never blindly repeats uncertain mutations. Quantity amendments set an absolute value, validate the expected current value and use stable amendment IDs plus audit history. See DEVELOPMENT.md for detailed states and recovery limitations.

## Shopify write sequence

1. `orderCreate` creates one paid loss order with exact variants and quantities.
2. The order uses a 100% item-percentage `Ntalosses` discount and explicit `DECREMENT_OBEYING_POLICY` inventory behavior.
3. A fresh fulfilment-state read returns exact FulfillmentOrder and line-item IDs plus remaining quantities.
4. `fulfillmentCreate` submits those exact IDs and quantities with `notifyCustomer: false` and no tracking.
5. Bounded backoff polls for up to 45 seconds; a fresh order lookup must show `FULFILLED`.
6. Fresh exact variant reads must prove the expected available and aggregate inventory deltas.

## Verification and failure semantics

`CLOSED_VERIFIED` requires every check to pass. A successful GraphQL response alone is not completion.

The helper fails closed on transport errors, scope errors, Shopify user errors, missing fulfilment IDs, unexpected existing orders, and verification mismatch. If an order may exist after an indeterminate response, the workflow reports the order and stops rather than issuing an unsafe duplicate.

## Tests

Required non-mutating checks are:

- deterministic loss-plan regression;
- fulfilment writer planner and adapter dry runs;
- bridge self-test, including secret-redaction and explicit write-gate tests;
- Python syntax/import checks;
- live read-only capability probe;
- live read-only product, variant, customer, order, fulfilment-order, and inventory reads as applicable;
- scheduler configuration and next-run verification.

No synthetic test order is permitted without explicit approval. Validate mutation behavior through the approved real scheduled workflow or a separately approved manual real batch. Capability probes and dry runs must never be described as proof that a new mutation occurred.
