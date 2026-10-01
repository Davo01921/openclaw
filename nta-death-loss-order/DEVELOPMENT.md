Deterministic hardening and deployment — 1 October 2026

This branch adds the deployed Python helpers to the canonical skill directory and hardens their boundaries. After David approved rollout, these helpers and the additive bridge read patch were installed in Fred’s live skill. The existing 18:00 Sydney job was converted to a native command payload; no second scheduler was added. A private backup retains the previous skill, bridge, scheduler and queue snapshot. No production `.env`, queue contents or credentials are included in this branch. No Shopify test orders, manual Shopify mutations or test Discord messages were performed during rollout.

**Architecture and risks**

AI continues to interpret staff text/photos and ask for clarification. Python receives structured, authorized intake and exact Shopify IDs. Python owns normalized identity matching, quantities, deduplication, amendments, stock checks, durable queue state, mutation intent and independent audits. The existing persisted-session bridge remains the only Shopify transport.

Priority defects addressed: tank-only identity authority; a close plan built before locking; CLOSED persisted before inventory audits; weak existing-order adoption; uncertain mutation retries; duplicate intake across dates; amendments without an audit/idempotency mechanism; incomplete/paginated reads treated as complete; ambient write gates and raw error logging.

The main planner now rejects malformed request types, non-GID variants, boolean/out-of-range quantities, low confidence and invalid evidence. Its idempotency key is based on the stable source event, so a quantity amendment cannot create a second logical order key. The production batch path retains existing `DeathRef-*` and `DeathBatch-*` tags; **existing reference tags are not renamed**. Any external consumer of the old planner-generated key must reconcile legacy keys before switching planners. No live consumer was changed.

**Files and behavior**

- `scripts/death_loss_order.py`: existing named bridge operations, exact fish normalization, scored candidates/reasons, secret-safe errors and child-scoped write gates. The standalone individual-order mutation entry point is disabled. Unknown synonyms and truncated searches require review rather than fuzzy automatic selection.
- `scripts/daily_batch.py`: add/amend/close, strict legacy-compatible queue reads, unique-temp atomic replacement with file/directory fsync, source deduplication across all dated queues and configured Discord sender/channel checks. All mutation planning and execution occur under the same exclusive queue lock.
- `scripts/configuration.py` and `config.example.json`: validated non-secret paths, exact customer/location IDs, authorized Discord IDs, timezone and cutoff. Required configuration is explicit; sample placeholders intentionally fail validation.
- `integration/shopify-session-bridge.patch`: additive read-query fields only. Authentication, credentials, supported operations and mutation inputs remain owned by the original bridge.
- `scripts/scheduled_close.py`: direct command adapter, bounded child execution, private machine-readable result journals, native empty-batch silence and concise success/recovery alerts. OpenClaw owns Discord delivery.
- `tests/test_runtime.py` and `tests/test_scheduled_close.py`: 53 offline tests using temporary queues and a fake Shopify transport, plus the existing planner regression.

Runtime prerequisites are Python 3.10+ with Sydney timezone data and Node 20+ for the existing bridge. The patched bridge's offline authentication/write-gate self-test passed using Node 24 in a temporary development copy with existing dependencies. The shell's default Node was older, so deployment must pin or verify the actual executable rather than assume the shell default is suitable.

The resolver requires one unique normalized fish identity. Tank context contributes a score but cannot authorize HIGH confidence. A unique exact fish match can override stale tank context and returns `STALE_OR_UNVERIFIED_TANK_CONTEXT`; a tank-only/mismatching result returns REVIEW_REQUIRED. Multiple exact fish matches also require review, even if only one has the reported tank label.

New records receive stable record IDs. Multi-item intake should use one source event plus stable `--item-key` values, distinguishing separate variants even in the same tank. Do not change item keys on retries. Legacy source references and unknown queue fields are preserved.

Amendments set an absolute quantity, require the expected current quantity and a stable amendment event ID, recheck aggregate outstanding demand against **available** stock, preserve source and audit history, and verify read-back. Replaying an older amendment after a newer one returns ALREADY_AMENDED without reverting the newer quantity. A reused amendment ID with a different target is blocked. Batches whose order creation has started cannot accept intake or amendments.

Recovery states are additive: OPEN → ORDER_CREATING → ORDER_CREATED → FULFILLING → VERIFYING → CLOSED. Any unresolved mutation or verification result leaves RECONCILIATION_REQUIRED with the exact known order and frozen inventory snapshot. The helper never resubmits order creation after persisted mutation intent, even if the order is not yet visible. A prior uncertain fulfilment attempt is polled and never blindly repeated.

An existing fulfilled legacy order can be adopted only after auditing exact order ID, customer, lines/quantities, discount code, zero AUD total/outstanding balance, financial state, cancellation state and required tags/references. If a historical baseline is unavailable, ALREADY_CLOSED explicitly reports `inventory_verified: false`; it does not claim newly verified historical inventory. New CLOSED_VERIFIED results require the saved pre-write baseline and fresh available/aggregate inventory deltas. Later sales do not invalidate a previously verified closed batch; its fresh order contract is re-audited while historical inventory proof is identified as historical.

Fulfilment verifies exact returned IDs, remaining quantities and assigned location. It polls the order projection with 2/4/8-second capped backoff within a 45-second deadline, including limiting each Python bridge-child read timeout to remaining time. A timeout reports pending consistency and the existing order, not a new-order retry. No tracking or customer notification is introduced.

**Commands for review**

All commands below are examples. Keep the config outside the queue directory and repository. Neither example supplies real credentials or authorizes deployment.

```sh
python3 -B -m unittest discover -s nta-death-loss-order/tests -v
python3 -B nta-death-loss-order/scripts/dry_run.py

python3 -B nta-death-loss-order/scripts/death_loss_order.py \
  --config /absolute/path/to/config.json resolve --fish "Exact product name" --tank TT21

python3 -B nta-death-loss-order/scripts/daily_batch.py \
  --config /absolute/path/to/config.json add \
  --variant-id gid://shopify/ProductVariant/111 --quantity 1 --tank TT21 \
  --fish "Exact product name" --confidence HIGH --evidence "Verified staff report" \
  --source-ref discord-channel-message --item-key item1 \
  --channel-id 123456789 --sender-id 987654321

python3 -B nta-death-loss-order/scripts/daily_batch.py \
  --config /absolute/path/to/config.json amend \
  --source-ref discord-channel-message-item1 --expected-quantity 1 --quantity 2 \
  --amendment-id discord-amendment-message-item1 \
  --channel-id 123456789 --sender-id 987654321

python3 -B nta-death-loss-order/scripts/daily_batch.py \
  --config /absolute/path/to/config.json close --date YYYY-MM-DD
```

Without `--execute`, add/amend/close do not create lock files, modify queues or mutate Shopify. Their bridge reads may use the existing session's normal token refresh. Add/amend `--execute` perform local queue writes only. A close mutation requires both `--execute` and the dedicated `NTA_SHOPIFY_DEATH_BATCH_WRITE_ENABLED=true` flag plus verified offline authentication and explicit read/write/inventory/merchant-managed-fulfilment scopes. Ambient generic writer flags cannot enable a mutation. CLI errors do not log raw exception text.

**Incremental installation and rollback**

1. Review the branch, tests and bridge patch. Retain the current live workflow while reviewing; do not run two schedulers or two versions of the helper against the same queue.
2. Validate configured customer/location/channel/senders by read-only inspection. Test normalization against representative real names; unresolved synonyms deliberately require review. Confirm 18:00 is the intended cutoff.
3. Make a reviewed backup of the live helper directory, bridge, scheduler declaration and queue state in private storage. This must happen before any authorized installation.
4. Apply the additive bridge patch to a **development copy of the auth project first**, using `git apply --check` and its existing `--self-test`. The patch was generated against bridge SHA256 `7019e5518733d3c6b866792c24bfab7a3be67d57d3b9a040f9cd5e0c5106daa1`; re-review if the installed bridge has changed. Apply it to production only after explicit approval. Adding read fields can be rolled back independently before helper installation.
5. Review the sample config, replace every placeholder with a verified non-secret value and store it privately. Do not copy credentials into this JSON file. The existing auth `.env` stays outside version control.
6. After approval, install all four runtime Python modules together and update skill command instructions to include the explicit config and authorized Discord source arguments. Keep source references stable. Existing queue files need no bulk conversion; record IDs are derived on read and written only during an authorized local update.
7. Run read-only preflights on a snapshot/development queue and compare exact expected plans before any real close. Until rollout approval, leave the current live scheduler unchanged.
8. After explicit rollout approval, convert the existing job to a native command payload, preserving its delivery target and Sydney timezone. Scope the dedicated write flag and supported Node executable to this job. Remove the old AI trigger; the command handles empty batches and reconciliation states. Re-enable the same job only after installed-helper read-only checks pass. Approval to continue the established daily workflow covers its real scheduled batches; synthetic orders and manual Shopify writes require separate explicit approval. Observe the next nonempty scheduled close and its independent audit.

Rollback before any new mutation restores the previous modules/config references/bridge. **After an order attempt, never simply restore an OPEN queue or run the old helper:** preserve the recovery journal and exact order identity and reconcile Shopify first. The older helper does not understand all new recovery states. Retain the hardened reconciliation path for those batches until their status is settled. If new amendments were used, preserve their histories and final absolute quantities.

**Read-only validation checklist**

- Run all offline tests and the deterministic planner regression; review the diff and scan tracked files for live credentials/exports.
- Verify the config schema and timezone/cutoff; confirm no placeholder passes validation.
- Inspect all legacy queue files with `load_queue` only, checking hashes before/after. All 12 existing files passed this check in development.
- In a development auth-project copy, check bridge patch applicability, JavaScript syntax and its non-network self-test.
- With the upgraded read adapter available and mutation flags unset, verify named product/variant/customer/order/fulfilment reads and connection `pageInfo` completeness. Confirm discount/outstanding/line-item fields are returned.
- Run add/amend/close without `--execute` against snapshot state and compare file hashes. Do not point an executable development close at production queues.
- Recheck the live scheduler declaration and next Sydney run without editing it. Current receipt success is not independent inventory proof.

**Explicitly approved live rollout checklist**

- Approval must cover installation/configuration changes and continuation of the established scheduled Shopify close. Development authorization alone does not authorize installation, synthetic orders or manual Shopify writes.
- Ensure one scheduler, no concurrent old helper, a verified backup, no unresolved earlier manual deductions and a preflight matching the real queue.
- Observe order intent, exact order ID, fulfilment attempt/result and fresh audits. On FAILED/INDETERMINATE, retain the journal and alert for reconciliation; never blindly repeat creation or fulfilment.
- Confirm one paid/fulfilled $0 order with exact customer, lines, references, discount and balance, then expected inventory deltas and CLOSED_VERIFIED read-back.
- Reconcile stale OPEN queues only against independently verified existing orders, without another deduction. September 21 was locally reconciled against #17330 using a client that prohibits mutations; its historical inventory baseline is explicitly marked unavailable.

**Scheduler boundary and token estimate**

The installed OpenClaw 2026.9.4 implementation supports `payload.kind="command"`, verified against its CLI and `src/cron/command-runner.ts`, and suppresses native `NO_REPLY` output in `src/gateway/server-cron.ts`. The existing job invokes the absolute Python executable with an argv array, private config path and `--execute`; no shell interpolation or model call is required. Its schedule remains `0 18 * * *` in `Australia/Sydney`, with zero staggering and normal daylight-saving handling. No generic operating-system cron task was added.

Without `--execute`, `scheduled_close.py --config <config>` emits the helper’s deterministic JSON and never sends messages. During the scheduled run, an empty close returns NO_BATCH before constructing an authenticated client; the adapter prints `NO_REPLY` and creates no result journal. For nonempty execution, it atomically persists JSON under the configured state directory’s `results/` and emits only concise notification text. Native OpenClaw delivery sends that text to the configured Discord channel. BLOCKED/FAILED/INDETERMINATE results exit nonzero, include recovery guidance and preserve native failure alerts. Existing-order summaries explicitly distinguish fresh inventory proof, previously verified evidence and an unavailable historical baseline.

Installed-helper read-only validation confirmed required scopes, the configured NTA Losses customer, exact product/variant identities and complete inventory connections. Both historical orders #17330 and #17396 passed every order contract check. Representative recent fish resolved correctly despite stale tank labels. Queue hashes were unchanged during validation; the separate authorized September 21 reconciliation changed only its local queue. The actual upgraded mutation path remains to be observed on the next real scheduled batch; fake-transport tests and historical read audits do not prove that future mutation.
Using Fred's unverified estimate of roughly 15,000 uncached input tokens per active AI-powered close, direct scheduling eliminates that model run and is estimated to save roughly 15,000 uncached input tokens plus cached context and model output per active close. At 30 active closes/month, that is about 450,000 uncached input tokens/month. Dollar savings depend on the actual model, billing/cache rates and active-close count. Intake's AI interpretation is unaffected.

Documented Shopify fields and fulfilment semantics were checked against [Order](https://shopify.dev/docs/api/admin-graphql/latest/objects/order), [orders pagination](https://shopify.dev/docs/api/admin-graphql/latest/queries/orders), [FulfillmentOrder](https://shopify.dev/docs/api/admin-graphql/latest/objects/FulfillmentOrder), and [fulfillmentCreate](https://shopify.dev/docs/api/admin-graphql/latest/mutations/fulfillmentCreate). Deployment must still prove compatibility with the installed bridge's pinned API version and real permissions; offline tests do not prove a live mutation.
