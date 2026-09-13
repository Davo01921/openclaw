# NTA Betta Picture Processing — Technical Design Document

**Status:** Current implementation baseline  
**Version:** 2.1  
**Date:** 2026-09-13  
**Repository:** `Davo01921/openclaw-skills`  
**Skill:** `nta-betta-picture-processing-v2` / runtime name `betta-picture-processing`

## 1. Technical objective

The system converts labelled Betta photographs into verified Shopify updates while separating probabilistic visual judgement from deterministic identity, title, mutation, verification, telemetry and archival controls.

The design principle is:

> Models observe and classify; deterministic code decides what may be written.

The implementation is fail-closed and checkpointed.

## 2. Primary components

### `SKILL.md`

Operator/runtime contract consumed by OpenClaw/Fred. Defines allowed behaviour, sequencing, title policy, Shopify mutation scope, image rules, telemetry requirements and throughput rules.

### `scripts/vision_review.py`

Runs auditable catalogue and image-QA inference through configured OpenClaw model providers. Records model/provider identity, call ID, hashes, structured output and usage data when available.

### `scripts/vision_batch.py`

Provides bounded parallel execution for visual-review work.

### `scripts/grok_hero.py`

Generates the catalogue hero through xAI/Grok image editing. Records source/output hashes, provider/model, usage data and Grok cost metadata.

Current fallback image cost:

`USD 0.07 per Grok image generation/edit call`

Provider-reported cost takes priority over the fallback.

### `scripts/betta_batch.py`

Authoritative deterministic state, title, evidence, transition and mutation validator.

Responsibilities include:

- deterministic Shopify-title construction;
- Female confidence threshold enforcement;
- source/hero hash validation;
- protected-field contract enforcement;
- mutation-envelope validation;
- fresh read-back validation;
- duplicate Product ID protection;
- fork/join preparation planning;
- bounded execution planning;
- checkpoint-safe resume behaviour.

### `scripts/betta_telemetry.py`

Persistent per-Betta operational telemetry store using SQLite.

Default database:

`~/Documents/Betta Processing/betta-telemetry.sqlite3`

The database is the live source of truth. CSV exports may be committed to GitHub/archive for audit/history; the SQLite binary should not be treated as a Git-based operational database.

### `scripts/betta_metrics.py`

Produces rolling efficiency summaries from telemetry, including onboarding-time distribution, retry rate, token usage, Grok spend and bottleneck-state metrics.

### Shared NTA services

The workflow integrates conceptually with:

- `nta-product-resolver` for product identity resolution;
- `nta-shopify-write-verifier` for mutation/read-back safety;
- `nta-automation-orchestrator` for higher-level routing.

## 3. Data flow

```text
Discord / local source photograph
        |
        v
Source save + SHA-256 + date_entered
        |
        v
Vision catalogue
        |
        v
Deterministic title assembly
        |
        v
VISUAL_ACCEPTED
        |
        +--------------------+
        |                    |
        v                    v
Shopify resolve        Grok hero generation
+ pre-write snapshot   + generation telemetry
        |                    |
        +---------+----------+
                  |
                  v
              JOIN GATE
                  |
                  v
CSV + image QA
                  |
                  v
Authorised Shopify mutation
                  |
                  v
Fresh independent read-back
                  |
                  v
Telemetry write
                  |
                  v
PASS / archive / report
```

## 4. Identity model

Every fish must preserve this chain:

`source attachment → source SHA-256 → tank ID/date evidence → Shopify Product ID`

The Product ID becomes the primary Shopify identity once resolved.

The system must not:

- infer identity from adjacent labels;
- switch products because an old title/handle looks stale;
- resolve more than one fish to the same Product ID within a batch;
- create a missing product implicitly.

## 5. Deterministic title engine

Required output:

`<Tank Number> - <Fish Name> <Tail Type> <Male/Female>`

The catalogue model supplies components, not the final authoritative title.

`betta_batch.py` reconstructs the expected title from:

- `tank_id`;
- `fish_name`;
- `tail_type`;
- canonical sex.

### Canonical sex

`Female` is permitted only when:

- returned sex is Female; and
- `sex_confidence >= 0.85`.

All other outcomes become `Male`.

The validator rejects titles where:

- tank differs from item ID;
- fish name is missing;
- tail type is missing;
- fish name/tail type contains sex;
- fish name duplicates tail type;
- final title differs from deterministic reconstruction.

This validation occurs before mutation and again during fresh read-back.

## 6. State model

Core item states currently include:

- `DISCOVERED`
- `SAVED`
- `VISUAL_PENDING`
- `VISUAL_ACCEPTED`
- `PRODUCT_RESOLVED`
- `CSV_READY`
- `IMAGE_CANDIDATE_READY`
- `IMAGE_QA_PENDING`
- `IMAGES_READY`
- `MUTATION_PENDING`
- `MUTATED`
- `VERIFIED`
- `PASS`
- `ARCHIVED`

Terminal/error states include:

- `BLOCKED_VISUAL`
- `BLOCKED_PRODUCT`
- `FIX_REQUIRED`

`betta_batch.py` remains the authoritative transition gate.

## 7. Parallel preparation design

`VISUAL_ACCEPTED` acts as a fork checkpoint.

Two operations can proceed independently:

### Shopify branch

Produces a valid product record containing:

- exact Product ID;
- complete protected-field pre-write snapshot;
- media/order/inventory/arrival-date snapshot.

### Hero branch

Produces a valid hero record containing:

- file path;
- SHA-256;
- renderer/model evidence;
- generation telemetry.

### Join condition

The workflow may progress past preparation only when both branches are valid.

The join is deterministic. Completion of one branch does not imply completion of the other.

## 8. Checkpoint/resume semantics

On rerun, the execution planner inspects persisted evidence.

If Shopify evidence exists and is valid:

- do not rerun Shopify resolution.

If hero evidence exists and is valid:

- do not regenerate the hero.

If only one branch is missing:

- schedule only the missing branch.

Passed QA/mutation/read-back stages must likewise be reused where safe rather than recomputed simply because the process was restarted.

This is both a throughput and cost-control requirement.

## 9. Concurrency

Default maximum external-operation concurrency is `4`.

The execution planner must enforce the ceiling across parallel preparation and other stage work. The design prioritises bounded stage-level concurrency rather than processing a large number of fish as independent end-to-end pipelines.

The concurrency limit should not be raised until production telemetry demonstrates that the external providers, Shopify, local runtime and retry rate can support it safely.

## 10. Image generation contract

Hero target:

- 2048 × 2048;
- premium catalogue presentation;
- near-black clean background;
- one fish;
- complete fin framing;
- realistic anatomy/texture;
- faithful identity/markings/colour distribution;
- no labels/text/props in the hero image.

Image 2 must be the original source bytes, unchanged.

No crop, resize, recompression, label replacement or conversion is permitted for Image 2.

## 11. Image QA contract

QA contains deterministic and visual evidence.

Deterministic checks include dimensions, filenames, label/framing rules and exact source/reference integrity.

Visual assertions include identity, anatomy, markings, colour distribution, fins/tail, framing, texture and composition.

The source/hero/original input hashes used during QA are persisted. Missing evidence is a failure.

## 12. Shopify mutation boundary

Authorised keys only:

- `title`;
- `arrival_date`;
- `inventory`;
- `media`.

Protected keys include:

- description;
- price;
- cost;
- vendor;
- product type;
- handle;
- status.

Mutation validation requires:

- title equals deterministic title;
- arrival date equals accepted physical photo date;
- inventory equals `1`;
- media hashes equal approved hero then source hash.

Fresh read-back independently verifies all changed and protected fields.

## 13. Telemetry model

One logical telemetry row is stored per `(batch_id, tank_number)`.

Current fields include:

- `batch_id`
- `tank_number`
- `date_entered`
- `arrival_date`
- `onboarding_started_at`
- `shopify_verified_at`
- `onboarding_seconds`
- `archive_completed_at`
- `end_to_archive_seconds`
- `model_calls`
- `retry_count`
- `grok_calls`
- `grok_cost_unknown_calls`
- `slowest_state`
- `slowest_state_seconds`
- `state_durations_json`
- `tokens_input`
- `tokens_output`
- `grokai_cost`
- `grokai_cost_currency`
- `grokai_cost_source`
- `provider`
- `model`
- `product_id`
- `title`
- `updated_at`

Schema migration logic adds newer columns to an existing local database without requiring a destructive rebuild.

## 14. Cost accounting

### Grok

Priority:

1. provider-reported billed cost;
2. configured/default per-image fallback;
3. unknown/null if neither is available.

Current fallback rate: `USD 0.07` per Grok image call.

Unknown cost must not be represented as `$0`.

### Tokens

For text/vision calls, sum input/output tokens across attributable calls and retries when provider/runtime usage exists.

Do not fabricate token values when usage is unreported.

## 15. Timing model

Primary KPI:

`onboarding_seconds = first ledger-entry timestamp → VERIFIED transition`

This measures first intake to successful fresh Shopify verification.

Secondary timing:

`end_to_archive_seconds = first ledger entry → ARCHIVED transition`

State-duration metrics identify the slowest state and quantify where wall-clock time accumulates.

## 16. Metrics layer

Rolling metrics should be inspected after real production samples, especially after approximately 20–30 Bettas.

Useful indicators include:

- median onboarding time;
- mean onboarding time;
- p90 onboarding time;
- fastest/slowest onboarding;
- retry rate;
- mean model-call count;
- mean input/output tokens;
- Grok calls/cost;
- top time-consuming states.

Optimisation decisions should be based on these measures rather than assumptions.

## 17. Persistence and archive

Operational state resides locally in the batch ledger, source/output files and SQLite telemetry database.

GitHub contains:

- skill contracts;
- deterministic scripts;
- tests;
- CI;
- documentation;
- optional CSV audit snapshots.

Do not use GitHub as the live transactional database for per-fish processing.

## 18. CI

GitHub Actions workflow:

`.github/workflows/betta-ci.yml`

Current CI performs:

1. Python compilation for Betta scripts.
2. `unittest` discovery for `nta-betta-picture-processing-v2/tests/test_*.py`.

Tests cover title invariants, Female threshold/default-Male behaviour, protected-field safety, hash integrity, duplicate Shopify Product IDs, concurrency, fork/join readiness, checkpoint resume behaviour and telemetry calculations.

A code change is not considered ready for live testing unless Betta CI succeeds.

## 19. Runtime readiness

Before processing live Shopify data, verify:

- local repository/skill copy is current;
- OpenClaw sees `betta-picture-processing`;
- configured vision provider is working;
- Grok/xAI API access is working;
- Shopify resolution/write/read-back operations are available;
- telemetry database path is writable;
- validator and scripts compile;
- no test failure is outstanding.

## 20. Known implementation boundary

GitHub CI validates the repository implementation, but it does not prove that David's local OpenClaw runtime has pulled the latest commit or that every live external credential/provider is healthy.

Therefore the first production validation remains a one-Betta live test with full evidence capture before scaling to a larger batch.
