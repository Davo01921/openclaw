# OpenClaw implementation notes

## Recommended architecture

Do **not** implement the skill as a single giant prompt that lets the active model execute every operation.

Use a deterministic orchestrator for state, validation, timing, retries, and mutation authority. Use model workers only where visual judgement or image generation is required.

```text
Discord batch collector
        |
        v
deterministic orchestrator
        |
        +--> cheap vision catalogue
        |        |
        |        +--> focused retry / Sol exception review
        |
        v
   VISUAL_ACCEPTED
        |
        +--------------------+
        |                    |
        v                    v
Shopify exact resolve     Grok hero generation
        |                    |
        +---------+----------+
                  |
                  v
          preparation join
          PRODUCT_RESOLVED
                  |
                  v
          CSV + image QA
                  |
                  v
       authorised Shopify write
                  |
                  v
          fresh read-back
                  |
                  v
        telemetry + archive
```

## Why the fork matters

Shopify product resolution and Grok hero generation depend on the accepted tank identity, but they do not depend on each other. Running them serially wastes wall-clock time.

After `VISUAL_ACCEPTED`, call:

```text
python scripts/betta_batch.py execution-plan <ledger> --workers 4
```

The returned `parallel_preparation.tasks` are independently runnable. Dispatch at most `max_concurrency` total tasks across both branches. Persist every successful result immediately, then re-run the planner.

A valid branch is never repeated merely because the other branch failed. This is the main checkpoint-resume rule:

- Shopify already resolved → do not resolve it again;
- hash-valid Grok hero already exists → do not regenerate it;
- both exist → advance the item to `PRODUCT_RESOLVED`;
- one is missing/invalid → schedule only that branch.

This makes retry cost proportional to the failed work instead of the entire fish workflow.

## Suggested implementation boundary

`scripts/betta_batch.py` is the authoritative local validation, title, transition, fork/join, and mutation-envelope gate. Runtime adapters remain responsible for Discord, image generation/editing, and Shopify API calls.

Typed operations should include:

- `collect_discord_batch(thread_id)`
- `save_source_attachment(...)`
- `hash_source(path)`
- `load_or_create_batch_ledger(batch_id)`
- `cheap_visual_catalogue(image_paths)`
- `cheap_visual_retry(image_path, field)`
- `sol_review(exception_packet)`
- `resolve_nta_product(identity_evidence)`
- `shopify_find_exact_tank(tank_id)`
- `prepare_hero(item)`
- `build_inventory_csv(items)`
- `bind_original_reference(item)`
- `shopify_find_ready_file(asset)`
- `shopify_upload_missing_file(asset)`
- `shopify_apply_betta_media(product_id, ...)`
- `shopify_set_arrival_date(product_id, date)`
- `shopify_set_inventory(product_id, 1)`
- `shopify_readback(product_id)`
- `assert_product_state(expected, actual)`
- `record_betta_telemetry(item)`
- `archive_passed_batch(batch_id)`
- `render_discord_report(batch_id)`

## Important authority split

The vision worker returns observations only: tank/date, `fish_name`, `tail_type`, and sex evidence. It must never authorise a free-form Shopify title.

The deterministic title builder owns:

```text
<Tank Number> - <Fish Name> <Tail Type> <Male/Female>
```

Sex defaults to `Male`; only a confident Female result at or above the configured threshold changes it to `Female`.

The model workers must not:

- issue Shopify mutations;
- create products;
- ignore API errors;
- alter price/cost/description or other protected fields;
- bypass title validation;
- archive;
- invent missing mappings.

For every Shopify mutation, create the shared verifier operation record with the batch ID as job ID and a stable per-fish idempotency key. Betta-specific checks supplement, but never bypass, `nta-shopify-write-verifier` fresh read-back.

## Timing and efficiency telemetry

The per-tank telemetry database is the operational source of truth:

```text
~/Documents/Betta Processing/betta-telemetry.sqlite3
```

For each fish record at least:

- tank number;
- `date_entered` / onboarding start;
- Shopify verified timestamp;
- onboarding seconds (`date_entered` → successful fresh read-back);
- archive completion time separately;
- model calls and retries;
- input/output tokens;
- Grok call count and Grok cost;
- state durations and slowest state;
- final title and Shopify Product ID.

Current NTA fallback Grok cost is **USD 0.07 per image call** when xAI does not report an actual billed cost. Provider-reported billed cost always wins. Never convert unknown provider usage into a fake zero.

Use `scripts/betta_metrics.py` for rolling summaries such as median onboarding time, p90 time, retry rate, average tokens, total Grok spend, and slowest states. Review the last 20-30 fish before changing concurrency.

## Throughput model

Keep the global external-operation ceiling at `4` initially. That ceiling includes Shopify resolution and Grok generation together.

Use a work-queue model rather than fixed serial waves:

1. ask `execution-plan` for runnable work;
2. fill up to four external-operation slots;
3. persist each result as soon as it completes;
4. refill free slots from remaining work;
5. re-run the planner after failures or branch completions;
6. advance `ready_to_join` items to `PRODUCT_RESOLVED`;
7. continue later states stage-wise.

Batch catalogue and QA calls only when each fish remains individually addressable in the output. Never combine different fish into one fidelity-QA evidence record.

Do deterministic work once per batch. Cache source hashes and Shopify READY-file lookups. Reuse passed images, snapshots, classification evidence, and QA records when their exact input hashes remain unchanged.

## Rollout/test sequence

1. Confirm `openclaw skills list` sees `betta-picture-processing`.
2. Run repository CI and require all Betta tests to pass.
3. Dry-run one fish with Shopify mutation disabled.
4. Confirm title components and final deterministic title.
5. Confirm `execution-plan` exposes both `shopify_resolve` and `grok_hero` after visual acceptance.
6. Simulate one branch failure and verify the next plan schedules only the failed/missing branch.
7. Confirm Grok fallback cost records USD 0.07 when provider cost is absent.
8. Enable live Shopify write for one fish.
9. Confirm fresh read-back, telemetry row, onboarding duration, media order, inventory, arrival date, protected fields, and archive evidence.
10. After 20-30 fish, inspect median/p90 onboarding time and slowest states before increasing concurrency.

## Do not over-optimise too early

The largest wins are eliminating repeated successful work, overlapping independent I/O, and keeping expensive reasoning out of the normal path. Do not raise concurrency until the telemetry shows where the bottleneck actually is.
