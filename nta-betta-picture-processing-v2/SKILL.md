---
name: "betta-picture-processing"
description: "Process labelled Betta photos into studio heroes, update matched Shopify products, verify, record per-tank usage/cost telemetry, and archive the batch."
user-invocable: true
---

# NTA Betta Picture Processing

Process one Discord thread as one traceable batch. Every fish must keep a stable source-to-tank-to-Shopify identity, receive one QA-approved hero, receive only authorised Shopify changes, pass fresh read-back verification, and finish with a per-tank telemetry row.

## Non-negotiable contract

- Match every fish through `Discord attachment → source hash → physical tank/date → exact Shopify Product ID`.
- Create a catalogue-style hero matching [references/image-standard.md](references/image-standard.md); do not require pixel-identical pose preservation.
- The Shopify title is deterministic. It MUST be exactly:

  `<Tank Number> - <Fish Name> <Tail Type> <Male/Female>`

- Example structure: `4BT41 - Turquoise White Red Marble Halfmoon Male`.
- Example structure: `2BT14 - Galaxy Koi Halfmoon Plakat Female`.
- `Fish Name` is the visible colour/pattern/descriptive name only. It must not contain the tank number, tail type, or sex.
- `Tail Type` is a separate required component written in full, for example `Halfmoon` or `Halfmoon Plakat`. Do not use abbreviations such as `HM` or `HMPK` in the final title.
- Sex defaults to `Male`. Use `Female` only when visual evidence confidently supports Female. If sex cannot be determined, the final title MUST use `Male`.
- A model may identify `fish_name`, `tail_type`, and sex evidence, but it must never freely compose or authorise the Shopify title. Deterministic code owns final title assembly and validation.
- If tank number, fish name, or tail type is unresolved, stop before Shopify. Do not improvise a title.
- Preserve the complete description, live retail price, live cost, vendor, product type, handle, and status exactly.
- Set `custom.arrival_date` from the physical photo label in `YYYY-MM-DD`.
- Set individual-fish inventory to exactly `1`.
- Upload the complete, uncropped original attachment as Image 2; its bytes and SHA-256 must equal the saved source.
- Stop before Shopify whenever identity, image QA, authorised changes, required title components, or required runtime components are unresolved.
- Never create a product, alter protected fields, accept a deviated title, or archive a failed item.

Read [references/state-machine.md](references/state-machine.md) before processing and [references/shopify-contract.md](references/shopify-contract.md) before any Shopify write.

Use `scripts/vision_review.py` for catalogue/QA inference, `scripts/vision_batch.py` for bounded parallel review, `scripts/betta_batch.py` as the authoritative state/title/evidence validator, and `scripts/betta_telemetry.py` for persistent per-tank usage/cost records. A model's prose verdict never substitutes for a successful validator exit.

## 1. Intake and traceability

Accept source photographs only from the designated private Discord processing thread or `/Users/davidlo/Documents/Betta Processing`. Treat one thread as one batch; never mix messages, threads, prior batches, or filesystem ordering.

Save originals without overwriting and record batch/thread/message/attachment IDs, local path, MIME type, byte size, SHA-256, and `date_entered`. `date_entered` is the Australia/Sydney timestamp when that fish first enters the processing ledger. It is not the same as the physical arrival/photo date.

Reject non-images from fish identification while retaining their ledger entries.

**Complete when:** every candidate source has a stable ID/hash, an immutable `date_entered`, and the accepted source set is unique.

## 2. Visual catalogue and deterministic title

Use the cheapest configured image-capable model for the first pass. For each source return structured:

- `tank_id` and confidence;
- physical `photo_date` and confidence;
- one-fish visibility;
- `fish_name`;
- `tail_type`;
- sex evidence/confidence;
- uncertainty reasons.

Do not ask the model to freely write the final Shopify title.

Normalize tank IDs (`2 BT 14` → `2BT14`) and dates (`21/8/2026` → `2026-08-21`). Never infer an adjacent tank.

`fish_name` may describe only supported visible colour/pattern traits. Do not claim genetics, lineage, grade, colour stability, or specialist variety without sufficient evidence. `tail_type` must be separate and written in full.

For sex, a confident Female classification may produce `Female`; every other outcome, including unknown/uncertain, resolves to `Male` under the NTA rule.

The code must assemble:

`title = <tank_id> + " - " + <fish_name> + " " + <tail_type> + " " + <sex>`

The existing compatibility field `proposed_title` may remain, but it must be populated from this deterministic title and never from free-form model prose.

Accept tank/date at confidence `>= 0.90`. At `0.70–0.89`, run one focused cheap retry. Below `0.70`, retry once and then escalate only the minimal evidence to the configured reasoning reviewer. If unresolved, mark `BLOCKED_VISUAL`.

Send David the mapping preview:

`source → tank → photo date → final deterministic title → sex/confidence`

Routine accepted mappings do not require approval unless David asks for an approval gate.

**Complete when:** every accepted item has valid title components, the deterministic title validator passes, and the preview has been sent before writes.

## 3. Shopify discovery

Resolve each accepted tank against live Shopify. Require exactly one existing individual-Betta product; never create one implicitly. Record the Product ID and a full pre-write snapshot: title, description, price, cost, vendor, product type, handle, status, media/order, inventory state, and arrival date.

Use Product ID as primary identity. Treat stale-looking handles or conflicting titles as evidence to diagnose, not permission to switch products. Follow [references/batch-integrity.md](references/batch-integrity.md).

**Complete when:** every accepted tank maps unambiguously to one snapshotted Product ID or is `BLOCKED_PRODUCT`.

## 4. CSV

Write `/Users/davidlo/Documents/Betta Processing/betta-inventory.csv` with exactly:

`Tank Number,Proposed Title,Cost,Retail Price`

`Proposed Title` is the deterministic final title. Copy cost and retail from the live pre-write Shopify snapshot; do not insert fixed recommendations. Verify exact headers, four fields per row, one unique row per accepted tank, and CSV tank-set equality.

**Complete when:** deterministic validation passes and no CSV value authorises a Shopify price or cost change.

## 5. Image production

Create:

- `<Tank ID>.png` — 2048 × 2048 studio hero;
- the original attachment — unchanged source bytes for Shopify Image 2.

Follow [references/image-standard.md](references/image-standard.md). Use the saved original itself as the reference asset. Never reuse hard-coded tank IDs, dates, crop coordinates, masks, or geometry across fish.

For every image-model call, retain provider/model, call timestamp, input/output token usage when reported, provider usage payload, and Grok/xAI cost when reported. `scripts/grok_hero.py` must report Grok/xAI cost from provider data when available. If provider cost is absent, use `BETTA_GROK_COST_USD_PER_IMAGE` only when explicitly configured. Otherwise record cost as unknown/null; never turn an unknown cost into `$0`.

**Complete when:** exactly one versioned hero exists, the reference record byte-matches the complete original, and image-generation telemetry is retained for the fish.

## 6. Mandatory image QA

Run deterministic checks and one recorded full-resolution visual comparison per source/hero/original triple. Validate hero dimensions, filenames, label content, framing, source-specific processing, clean composition, and exact original-reference hash equality.

Evaluate hero identity using stable characteristics: body proportions, head/body relationship, distinctive scale layout, unique markings, colour distribution, tail type, and visible anatomical integrity. A changed pose, fin spread, isolation, crop, or exposure is allowed when plausible and consistent with the source fish; it is not by itself a failure.

Reject changed identity, invented identifying markings, implausible anatomy, wrong tail form, materially recoloured regions, plastic texture, severe halos, or unsupported detail presented as fact.

Persist provider/model/call ID, timestamp, hashes, usage data, per-assertion results, overall outcome, and retry/escalation evidence. Missing evidence or zero comparison calls is automatic `FIX_REQUIRED`.

**Complete when:** the ledger schema validates and every mandatory assertion is PASS; otherwise no upload is permitted.

## 7. Authorised Shopify update

Build an explicit per-product change set containing only:

- `title` → exact deterministic title;
- `custom.arrival_date` → accepted physical photo date;
- inventory → `1`;
- approved hero/reference media and ordering.

Before mutation, `scripts/betta_batch.py` must independently regenerate the expected title from `tank_id`, `fish_name`, `tail_type`, and sex and reject any mismatch.

Upload only QA-approved file hashes. Feature the hero as Image 1 and place the complete uncropped original attachment as Image 2. Preserve useful genuine extra angles; remove only the specifically superseded old hero or derived/cropped reference after its replacement is READY.

Inspect transport errors, top-level GraphQL errors, and every `userErrors` array; any material error stops the item.

**Complete when:** every submitted change is authorised, exact-title validation passes, and every response is error-free.

## 8. Fresh read-back verification

Query Shopify again independently and assert:

- Product ID and tank mapping unchanged;
- title equals the deterministic expected title exactly;
- description, price, cost, vendor, product type, handle, and status equal the pre-write snapshot;
- arrival date equals the physical photo date;
- inventory equals `1`;
- approved hero is featured as Image 1;
- the complete original attachment is Image 2 and its hash equals the source hash;
- no unintended media loss occurred.

Record exact expected/actual values. Prose cannot convert a failed assertion to PASS.

**Complete when:** every assertion passes from fresh live data or the item is `FIX_REQUIRED`.

## 9. Per-tank telemetry database

Before an item may become `PASS`, write or update one row in:

`~/Documents/Betta Processing/betta-telemetry.sqlite3`

using `scripts/betta_telemetry.py`.

At minimum each row must contain:

- `tank_number`;
- `date_entered` — first ledger-entry timestamp in Australia/Sydney;
- `arrival_date` — physical photo/arrival date when available;
- `tokens_input` — sum of input tokens for every model call attributable to this fish, including retries and QA;
- `tokens_output` — sum of output tokens for every model call attributable to this fish, including retries and QA;
- `grokai_cost` — sum of Grok/xAI image-generation/edit costs attributable to this fish;
- `grokai_cost_currency`;
- `grokai_cost_source` (`provider`, `configured`, or `unavailable`);
- batch ID, provider/model summary, Shopify Product ID, and final title for auditability.

Do not silently drop failed/retried calls from token totals if they consumed provider usage. Do not invent token counts or Grok costs when the provider/runtime did not report them.

At the end of each completed batch, export the database to CSV with `scripts/betta_telemetry.py export`. Keep the batch/archive copy with the processing evidence. A GitHub copy of the CSV may be used as an audit/history snapshot, but the live SQLite database is the source of truth; do not use a committed SQLite binary as the operational database.

**Complete when:** every PASS fish has exactly one up-to-date row for that batch/tank and the batch CSV export exists.

## 10. Archive and Discord result

Archive only when every item is PASS and the telemetry row exists. Rename originals to `<Tank ID> Original <ARCHIVE-DATE>.<extension>` using the current Australia/Sydney archive date, which is separate from both `date_entered` and physical photo/arrival date.

Move completed sources and CSV under `Archived Bettas/YYYY-MM-DD/Betta Processing` and outputs under `Archived Bettas/YYYY-MM-DD/Betta Processed`; verify hashes and tank-set equality after moving. Include the telemetry CSV export with the archived batch evidence.

Reply in the originating Discord thread with counts, PASS tanks/photo dates/final titles, preserved price/cost/description confirmation, inventory, arrival date, media status, storefront links from final live handles, token input/output totals, Grok/xAI cost status, genuine exceptions, and the inventory CSV.

**Complete when:** archive, ledger, telemetry, and live Shopify read-back all agree.

## Runtime readiness

Before a live batch, verify an approved vision reviewer, Shopify resolve/write/read-back operations, `scripts/betta_batch.py`, `scripts/betta_telemetry.py`, writable telemetry DB path, and dry-run mode. Prefer the cheap worker; allow recorded Sol fallback. Without a reviewer, validator, or telemetry writer, remain in dry-run. Never substitute an unrecorded manual PASS.

## Batch throughput

Run stage-wise bounded concurrency following [IMPLEMENTATION.md](IMPLEMENTATION.md), not one fish end-to-end at a time. Use `scripts/betta_batch.py execution-plan <ledger> --workers 4`; run only its next independent wave. Use `scripts/vision_batch.py` for parallel catalogue/QA calls. Keep evidence per fish, reuse validated stages/files on retry, and retain the all-PASS archive gate.

**Complete when:** no stage exceeds four concurrent external operations and retries resume at the last validated state.
