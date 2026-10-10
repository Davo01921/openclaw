---
name: "betta-picture-processing"
version: "2.1"
description: "Process labelled Betta photos into studio heroes, update matched Shopify products, verify, record per-tank timing/usage/cost telemetry, and archive the batch."
user-invocable: true
---

# NTA Betta Picture Processing

Process one Discord thread as one traceable batch. Every fish must keep a stable source-to-tank-to-Shopify identity, receive one QA-approved hero, receive only authorised Shopify changes, pass fresh read-back verification, and finish with a per-tank telemetry row.

## Non-negotiable contract

- Match every fish through `Discord attachment → source hash → physical tank/date → exact Shopify Product ID`.
- The Shopify title is deterministic and MUST be exactly:

  `<Tank Number> - <Fish Name> <Tail Type> <Male/Female>`

- Example: `4BT41 - Turquoise White Red Marble Halfmoon Male`.
- Example: `2BT14 - Galaxy Koi Halfmoon Plakat Female`.
- `Fish Name` is visible colour/pattern/descriptive naming only. It must not contain the tank number, tail type, or sex.
- `Tail Type` is separate and required, written in full such as `Halfmoon` or `Halfmoon Plakat`; do not use final-title abbreviations such as `HM` or `HMPK`.
- Sex defaults to `Male`. Use `Female` only when visual evidence confidently supports Female at the configured threshold. If sex cannot be determined, use `Male`.
- A model may identify `fish_name`, `tail_type`, and sex evidence, but deterministic code owns final title assembly and validation.
- If tank number, fish name, or tail type is unresolved, stop before Shopify.
- Create a catalogue-style hero matching [references/image-standard.md](references/image-standard.md).
- Preserve description, live retail price, live cost, vendor, product type, handle, and status exactly.
- Set `custom.arrival_date` from the physical photo label in `YYYY-MM-DD`.
- Set individual-fish inventory to exactly `1`.
- Upload the complete uncropped original attachment as Image 2; bytes and SHA-256 must equal the saved source.
- Never create a product implicitly, alter protected fields, accept a deviated title, fabricate usage/cost values, or archive a failed item.

Read [references/state-machine.md](references/state-machine.md) before processing and [references/shopify-contract.md](references/shopify-contract.md) before any Shopify write.

Use `scripts/vision_review.py` for catalogue/QA inference, `scripts/vision_batch.py` for bounded parallel review, `scripts/betta_batch.py` as the authoritative state/title/fork-join/evidence validator, `scripts/betta_shopify_batch.py` for manifest-bound Shopify batch upload/resume/verification, and `scripts/betta_telemetry.py` for persistent per-tank timing/usage/cost records.

## Model-routing contract

All interchangeable vision-inference, extraction and reasoning/review calls in this workflow must resolve through `adaptive-model-router` before dispatch, even when this skill is invoked directly.

This workflow may declare the required capability and confidence/escalation condition; it does not independently choose OpenAI, Qwen, another general provider, or a model slug.

`grok_hero` is different: it is a fixed specialist image-generation operation owned by this workflow. Grok/xAI may remain bound to that generation step under the specialised-service boundary in `adaptive-model-router`; it must not be reused as an unapproved general reasoning or review route.

## 1. Intake and traceability

Accept source photographs only from the designated private Discord processing thread or `/Users/davidlo/Documents/Betta Processing`. Treat one thread as one batch; never mix messages, threads, prior batches, or filesystem ordering.

Save originals without overwriting and record batch/thread/message/attachment IDs, local path, MIME type, byte size, SHA-256, and immutable `date_entered` in Australia/Sydney. `date_entered` is the onboarding start timestamp; it is separate from the physical photo/arrival date.

Reject non-images from fish identification while retaining their ledger entries.

**Complete when:** every candidate source has a stable ID/hash, immutable `date_entered`, and the accepted source set is unique.

### Batch lifecycle and isolation

Every new intake is a new, uniquely identified batch. Use `scripts/betta_batches.py`:

```
python3 scripts/betta_batches.py new --label "<free-text batch label>"
python3 scripts/betta_batches.py list
python3 scripts/betta_batches.py active
python3 scripts/betta_batches.py status <batch_id>
python3 scripts/betta_batches.py close <batch_id>
python3 scripts/betta_batches.py register-historical <approved-manifest.json>
```

- A new batch gets a generated id (`betta-YYYYMMDD-HHMMSS-<token>`) and its own workspace: `intake/ evidence/ manifest/ state/ reports/ receipts/ archive/` under `~/Documents/Betta Processing/batches/<batch_id>/`.
- Manifests, processing state, approvals, receipts and archives are isolated per batch. Never reuse a batch id, and never write a new batch into a completed batch's workspace.
- Completed batches are immutable history. `assert_batch_writable` refuses writes to a `COMPLETE`/`ABANDONED` batch, and `register-historical` records an already-finished batch (reading only its own manifest) so it can never block or contaminate new work.
- Nothing about a previous batch (tank numbers, dates, image filenames) is hardcoded. A historical batch is referenced only by its own id.
- Historical batches are read-only evidence. Do not reset, reopen, or delete them; the generic flow always starts a fresh batch.

### V2.2 orchestration (prepared, disabled until activated)

`scripts/betta_process.py` provides the single `process_batch` orchestrator (resumable, idempotent, crash-safe, per-fish quarantine, standing-authorisation gate). `scripts/betta_adapters.py` wires it to the existing components (generation, hero finishing, QA, Shopify uploader, archive, telemetry) with batch-scoped, injectable runners. `scripts/betta_watch.py` provides automatic intake and `scripts/betta_policy.py` holds the standing Shopify authorisation bound to an exact manifest SHA-256. The existing Grok/xAI generation engine and prompts are unchanged. Live Shopify writes and paid generation are refused unless explicitly enabled; automatic intake and standing Shopify writes are DISABLED by default. See docs/V2.2_LIVE_INTEGRATION_2026-10-10.md.

## 2. Visual catalogue and deterministic title

Request a first-pass route from `adaptive-model-router` with image/vision-inference capability and use the lowest sufficient routing class it returns. Do not choose a provider/model locally. Return structured:

- `tank_id` and confidence;
- physical `photo_date` and confidence;
- one-fish visibility;
- `fish_name`;
- `tail_type`;
- sex evidence/confidence;
- uncertainty reasons.

Do not ask the model to freely compose the Shopify title.

Normalize tank IDs (`2 BT 14` → `2BT14`) and dates (`21/8/2026` → `2026-08-21`). Never infer an adjacent tank.

The code assembles:

`title = <tank_id> + " - " + <fish_name> + " " + <tail_type> + " " + <sex>`

The compatibility field `proposed_title` may remain only if it is populated from this deterministic title.

Accept tank/date at confidence `>= 0.90`. At `0.70–0.89`, run one focused retry through the router-resolved vision route. Below `0.70`, retry once and then request the smallest justified stronger vision-review class from `adaptive-model-router`, passing only the minimal unresolved evidence. If unresolved, mark `BLOCKED_VISUAL`.

Send David the mapping preview:

`source → tank → photo date → final deterministic title → sex/confidence`

**Complete when:** every accepted item has valid title components, the deterministic title validator passes, and the preview has been sent before writes.

## 3. Parallel preparation: Shopify resolution + Grok hero

Immediately after `VISUAL_ACCEPTED`, do not run Shopify discovery and image generation serially.

Call:

`python scripts/betta_batch.py execution-plan <ledger> --workers 4`

Consume `parallel_preparation.tasks`. `max_concurrency` is the total external-operation ceiling across both branches.

Two operations are independently runnable:

### A. `shopify_resolve`

Resolve the accepted tank against live Shopify. Require exactly one existing individual-Betta product and record Product ID plus the full pre-write snapshot: title, description, price, cost, vendor, product type, handle, status, media/order, inventory state, and arrival date.

Use Product ID as primary identity. A stale title/handle is diagnostic evidence, not permission to switch products.

### B. `grok_hero`

Create `<Tank ID>.png` at 2048 × 2048 following [references/image-standard.md](references/image-standard.md). Keep the original source untouched for Image 2.

Persist provider/model, timestamp, output hash, usage payload, reported tokens when present, and Grok/xAI cost metadata.

Current NTA fallback Grok cost is **USD 0.07 per image call** when xAI does not report actual billed cost. Provider-reported billed cost always wins. Record the source of the cost; never turn unknown cost into `$0`.

### Resume rule

Persist each successful branch immediately and re-run `execution-plan`.

- Shopify success + Grok failure → retry only `grok_hero`.
- Grok success + Shopify failure → retry only `shopify_resolve`.
- Both success → item appears in `ready_to_join`; advance it to `PRODUCT_RESOLVED`.

Never regenerate or re-resolve a branch whose persisted output still validates against the same source/tank evidence.

**Complete when:** both branches validate and the item has crossed the preparation join.

## 4. CSV

Write `/Users/davidlo/Documents/Betta Processing/betta-inventory.csv` with exactly:

`Tank Number,Proposed Title,Cost,Retail Price`

`Proposed Title` is the deterministic final title. Copy cost and retail from the live pre-write Shopify snapshot. Verify exact headers, four fields per row, one unique row per accepted tank, and CSV tank-set equality.

**Complete when:** deterministic validation passes and no CSV value authorises a Shopify price or cost change.

## 5. Mandatory image QA

Run deterministic checks and one recorded full-resolution visual comparison per source/hero/original triple. The visual comparison is a general vision-review phase and must use an `adaptive-model-router`-resolved route; the fixed Grok hero generator does not automatically become the QA reviewer.

Validate hero dimensions, filenames, label content, framing, source-specific processing, clean composition, and exact original-reference hash equality.

Evaluate stable identity characteristics: body proportions, head/body relationship, scale layout, unique markings, colour distribution, tail type, and visible anatomy. A plausible changed pose/fin spread is allowed; changed identity, invented markings, implausible anatomy, wrong tail form, material recolouring, plastic texture, severe halos, or unsupported detail is not.

Persist routing class, requested route, actual provider/model/call ID when attested, timestamp, hashes, usage data, per-assertion results, overall outcome, fallback/retry/escalation evidence, and whether execution metadata proved the provider/model. Missing evidence or zero comparison calls is `FIX_REQUIRED`.

**Complete when:** every mandatory assertion is PASS.

## 6. Authorised Shopify update

Build a per-product change set containing only:

- `title` → exact deterministic title;
- `custom.arrival_date` → physical photo date;
- inventory → `1`;
- approved hero/reference media and ordering.

Before mutation, `scripts/betta_batch.py` must regenerate the expected title from `tank_id`, `fish_name`, `tail_type`, and sex and reject any mismatch.

Run the manifest-driven upload through `scripts/betta_shopify_batch.py`; see [docs/SHOPIFY_BATCH_UPLOADER.md](docs/SHOPIFY_BATCH_UPLOADER.md). Dry-run is the default. Live mode additionally requires batch and per-item authority plus the exact manifest SHA-256.

The uploader must attach the approved hero and complete uncropped original, wait for both media records to become `READY`, identify them independently by manifest-bound metadata, order HERO first and ORIGINAL second, then delete only the old media IDs captured at preflight. The final media set is exactly those two images. Inspect transport errors, top-level GraphQL errors, and every `userErrors` array; any material error stops the item.

Every mutation intent must be journalled before dispatch. An uncertain write is reconciled against fresh Shopify state and is never automatically replayed. Inventory uses `changeFromQuantity` compare-and-set and a persisted idempotency key.

**Complete when:** every submitted change is authorised and error-free.

## 7. Fresh read-back verification

Query Shopify independently and assert:

- Product ID/tank mapping unchanged;
- title equals deterministic expected title exactly;
- description, price, cost, vendor, product type, handle, and status match pre-write snapshot;
- arrival date equals physical photo date;
- inventory equals `1`;
- approved hero is Image 1;
- complete original is Image 2 and source hash matches;
- exactly two images remain in that order;
- inventory tracking remains enabled and policy remains `DENY`.

The successful `VERIFIED` transition is the end timestamp for the primary onboarding KPI.

**Complete when:** every assertion passes from fresh live data or the item is `FIX_REQUIRED`.

## 8. Per-tank telemetry database

Before `PASS`, write/update one row in:

`~/Documents/Betta Processing/betta-telemetry.sqlite3`

using `scripts/betta_telemetry.py`.

Record at least:

- tank number;
- `date_entered` / onboarding start;
- physical arrival date;
- Shopify verified time;
- `onboarding_seconds` from first intake to successful fresh read-back;
- archive completion separately;
- model-call count and retry count;
- input/output tokens from all attributable calls including retries when reported;
- router class/requested route for general model calls;
- actual provider/model for general model calls only when execution metadata attests them;
- fallback/escalation reason and execution-attestation state;
- Grok call count and total Grok/xAI cost as a separate fixed specialist-service record;
- cost currency/source;
- state durations and slowest state;
- batch ID, provider/model summary, Shopify Product ID, and final title.

Do not silently drop failed/retried calls that consumed usage. Do not invent token counts or actual provider/model identities when the runtime did not report them.

At the end of each batch export the DB to CSV. A GitHub CSV snapshot may be retained for audit/history; the live SQLite database is the operational source of truth.

Use `scripts/betta_metrics.py` to review rolling median/p90 onboarding time, retry rate, average tokens, Grok spend, and slowest states.

**Complete when:** every PASS fish has one current telemetry row and the batch CSV export exists.

## 9. Archive and Discord result

Archive only when every item is PASS and telemetry exists. Rename originals to `<Tank ID> Original <ARCHIVE-DATE>.<extension>` using Australia/Sydney archive date. Keep archive completion separate from onboarding time.

Move completed sources and inventory CSV under `Archived Bettas/YYYY-MM-DD/Betta Processing` and outputs under `Archived Bettas/YYYY-MM-DD/Betta Processed`; include the telemetry CSV export and verify hashes/tank-set equality.

### Archive command

Use `scripts/betta_archive.py` for a resumable, verified archive:

```
python3 scripts/betta_archive.py plan    --manifest <production-manifest.json> \
  --verify <verify-report.json> [--verify <more.json>] --inventory-csv <csv> \
  --archive-root "~/Documents/Archived Bettas" --state-root "<betta state root>" \
  [--exceptions <owner-exceptions.json>] [--out plan.json]
python3 scripts/betta_archive.py execute ... [--apply]
python3 scripts/betta_archive.py status  --archive-root "~/Documents/Archived Bettas" [--date YYYY-MM-DD]
python3 scripts/betta_archive.py resume  ... [--apply]
```

- Default is dry-run. Files are moved only with `--apply`.
- Before any move it requires, for every fish, an independent `FINAL_SHOPIFY_READBACK_PASS`. A fish that lacks one, or that has a failed assertion, is `NEEDS_REVIEW` and blocks the whole archive.
- Documented, owner-accepted exceptions (QA exceptions accepted by the owner, or an explicit `--exceptions` record) are preserved and recorded as `PASS_WITH_ACCEPTED_EXCEPTION`. A failed assertion is never converted into a plain pass.
- Files are copied, destination SHA-256 verified against the source, and only then are the specific source files removed. Existing destinations with different content are refused, never overwritten.
- The audit subfolder (`Archived Bettas/YYYY-MM-DD/Audit/`) preserves the production manifest, verification reports, QA evidence, receipts and owner-approved exceptions. Authentication data and unresolved Shopify mutation state are never moved or deleted.
- An immutable `archive-manifest.json` records source/destination paths, hashes and timestamps. Resume is idempotent and skips completed files.

Reply in the originating Discord thread with counts, tanks/photo dates/final titles, protected-field confirmation, inventory, arrival date, media status, storefront links, input/output tokens, Grok cost, onboarding time, retry count, genuine exceptions, and CSV attachment.

**Complete when:** archive, ledger, telemetry, and live Shopify read-back agree.

## Runtime readiness and throughput

Before a live batch, verify `adaptive-model-router` availability for general vision/review calls, the fixed Grok hero service, Shopify resolve/write/read-back operations, the existing authenticated Shopify bridge, `scripts/betta_batch.py`, `scripts/betta_runtime.py`, `scripts/betta_shopify_batch.py`, `scripts/betta_telemetry.py`, writable telemetry DB, Grok cost fallback, and dry-run mode. `scripts/betta_runtime.py` is the deterministic orchestration layer for serialized ledger writes, cross-batch intake deduplication, API-error classification, uncertain-write reconciliation, CSV validation and telemetry-before-PASS; `scripts/betta_shopify_batch.py` is the manifest-bound live Shopify writer (dry-run by default).

The generic live adapters (`scripts/betta_shopify_batch.py`, `scripts/betta_finish_heroes.py`, the authenticated bridge) currently exist only in the local canonical checkout and are not yet committed to this repository; see docs/RUNTIME_ADAPTER_STATUS_2026-10-09.md for the boundary. Offline helper and fixture completion is not live acceptance.

Use a global maximum of four simultaneous external operations initially. Run independent work as a queue, persist each result immediately, and refill available slots. Re-run `execution-plan` after branch completion/failure so only missing work is scheduled.

Never restart a fish from intake merely because a downstream stage failed. Resume from the last validated checkpoint whose hashes/evidence still match.

After 20-30 Bettas, review telemetry before considering a concurrency increase.

## Canonical closeout status — 2026-10-02

This V2.1 source is canonical. V3 quota/overnight work is deferred. Status is READY FOR FINAL LIVE ACCEPTANCE; do not report CLOSED until docs/CLOSEOUT.md's one-fish exercise passes. Enforce the updated fresh exact variant/location, zero-stock intake authority, independent readback and archive-hash gates in scripts/betta_batch.py. No paid test assets or invented intake events are authorized by closeout.
