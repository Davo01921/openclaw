---
name: "betta-picture-processing"
description: "Process labelled Betta photos into studio heroes, update matched Shopify products, verify, and archive the batch."
user-invocable: true
---

# NTA Betta Picture Processing

Process one Discord thread as one traceable batch. Produce a polished studio hero and a natural reference for each identifiable fish, change only the authorised Shopify fields, verify fresh live state, then archive.

## Non-negotiable contract

- Match every fish through `Discord attachment → source hash → physical tank/date → exact Shopify Product ID`.
- Create a catalogue-style hero matching [references/image-standard.md](references/image-standard.md); do not require pixel-identical pose preservation.
- Change the product title to the accepted photo-based suggestion.
- Preserve the complete description, live retail price, live cost, vendor, product type, handle, and status exactly.
- Set `custom.arrival_date` from the physical photo label in `YYYY-MM-DD`.
- Set individual-fish inventory to exactly `1`.
- Keep the natural source-derived reference as Image 2.
- Stop before Shopify whenever identity, image QA, authorised changes, or required runtime components are unresolved.
- Never create a product, alter protected fields, or archive a failed item.

Read [references/state-machine.md](references/state-machine.md) before processing and [references/shopify-contract.md](references/shopify-contract.md) before any Shopify write.

Use `scripts/vision_review.py` for recorded catalogue/QA inference and `scripts/betta_batch.py` as the authoritative transition and evidence validator. A model's prose verdict never substitutes for a successful validator exit.

## 1. Intake and traceability

Accept source photographs only from the designated private Discord processing thread or `/Users/davidlo/Documents/Betta Processing`. Treat one thread as one batch; never mix messages, threads, prior batches, or filesystem ordering.

Save originals without overwriting and record batch/thread/message/attachment IDs, local path, MIME type, byte size, and SHA-256. Reject non-images from fish identification while retaining their ledger entries.

**Complete when:** every candidate source has a stable ID and hash and the accepted source set is unique.

## 2. Visual catalogue

Use the cheapest configured image-capable model for the first pass. For each source return structured tank ID, physical photo date, one-fish visibility, proposed title, optional sex, field confidences, and uncertainty reasons.

Normalize tank IDs (`2 BT 14` → `2BT14`) and dates (`21/8/2026` → `2026-08-21`). Never infer an adjacent tank.

Build the title only from visible dominant colour, visible pattern, and apparent tail form. Add `Male` or `Female` only at confidence `>= 0.85`; otherwise omit sex. Do not claim genetics, lineage, grade, colour stability, or a specialist variety that the photograph does not support.

Accept tank/date at confidence `>= 0.90`. At `0.70–0.89`, run one focused cheap retry. Below `0.70`, retry once and then escalate the minimal evidence to the configured reasoning reviewer. If unresolved, mark `BLOCKED_VISUAL`.

Send David the mapping preview:

`source → tank → photo date → proposed new title → sex/confidence`

Routine accepted mappings do not require approval unless David asks for an approval gate.

**Complete when:** every item is accepted with evidence or explicitly blocked, and the preview has been sent before writes.

## 3. Shopify discovery

Resolve each accepted tank against live Shopify. Require exactly one existing individual-Betta product; never create one implicitly. Record the Product ID and a full pre-write snapshot: title, description, price, cost, vendor, product type, handle, status, media/order, inventory state, and arrival date.

Use Product ID as primary identity. Treat stale-looking handles or conflicting titles as evidence to diagnose, not permission to switch products. Follow [references/batch-integrity.md](references/batch-integrity.md).

**Complete when:** every accepted tank maps unambiguously to one snapshotted Product ID or is `BLOCKED_PRODUCT`.

## 4. CSV

Write `/Users/davidlo/Documents/Betta Processing/betta-inventory.csv` with exactly:

`Tank Number,Proposed Title,Cost,Retail Price`

Use the accepted tank and proposed new title. Copy cost and retail from the live pre-write Shopify snapshot; do not insert fixed recommendations. Verify exact headers, four fields per row, one unique row per accepted tank, and CSV tank-set equality.

**Complete when:** deterministic validation passes and no CSV value authorizes a Shopify price or cost change.

## 5. Image production

Create:

- `<Tank ID>.png` — 2048 × 2048 studio hero.
- `<Tank ID> Reference.png` — source-derived natural reference, 2048 × 2048 where practical.

Follow [references/image-standard.md](references/image-standard.md). The hero may use controlled image editing to achieve the approved studio presentation; the reference must remain documentary source evidence.

Persist source, candidate, reference, renderer/editor method, version, and hashes. Never reuse hard-coded tank IDs, dates, crop coordinates, masks, or geometry across fish.

**Complete when:** exactly one versioned hero/reference pair exists for each accepted source.

## 6. Mandatory image QA

Run deterministic checks and one recorded full-resolution visual comparison per source/hero/reference triple. Validate dimensions, filenames, label content, framing, source-specific processing, and clean composition.

Evaluate hero identity using stable characteristics: body proportions, head/body relationship, distinctive scale layout, unique markings, colour distribution, tail type, and visible anatomical integrity. A changed pose, fin spread, isolation, crop, or exposure is allowed when plausible and consistent with the source fish; it is not by itself a failure. Reject changed identity, invented identifying markings, implausible anatomy, wrong tail form, materially recoloured regions, plastic texture, severe halos, or unsupported detail presented as fact.

Persist provider/model/call ID, timestamp, hashes, per-assertion results, overall outcome, and retry/escalation evidence. Missing evidence or zero comparison calls is automatic `FIX_REQUIRED`.

**Complete when:** the ledger schema validates and every mandatory assertion is PASS; otherwise no upload is permitted.

## 7. Authorised Shopify update

Build an explicit per-product change set containing only:

- `title` → accepted proposed title;
- `custom.arrival_date` → accepted physical photo date;
- inventory → `1`;
- approved hero/reference media and ordering.

Upload only the QA-approved file hashes. Feature the hero as Image 1 and place the genuine reference as Image 2. Preserve useful genuine extra angles; remove only the specifically superseded old hero after its replacement is READY.

Require the pre-write snapshot and contract validator to pass before mutation. Inspect transport errors, top-level GraphQL errors, and every `userErrors` array; any material error stops the item.

**Complete when:** every submitted change is authorised and every response is error-free.

## 8. Fresh read-back verification

Query Shopify again independently and assert:

- Product ID and tank mapping unchanged;
- title equals the accepted proposed title;
- description, price, cost, vendor, product type, handle, and status equal the pre-write snapshot;
- arrival date equals the physical photo date;
- inventory equals `1`;
- approved hero hash/version is featured at Image 1;
- natural reference is Image 2;
- no unintended media loss occurred.

Record exact expected/actual values. Prose cannot convert a failed assertion to PASS.

**Complete when:** every assertion passes from fresh live data or the item is `FIX_REQUIRED`.

## 9. Archive and Discord result

Archive only when every item is PASS. Rename originals to `<Tank ID> Original <ARCHIVE-DATE>.<extension>` using the current Australia/Sydney archive date, which is separate from the physical photo/arrival date. Move the completed source set and CSV under `Archived Bettas/YYYY-MM-DD/Betta Processing` and outputs under `Archived Bettas/YYYY-MM-DD/Betta Processed`; verify file hashes and tank-set equality after moving.

Reply in the originating thread with counts, PASS tanks/photo dates/new titles, preserved price/cost/description confirmation, inventory, arrival date, media status, storefront links from final live handles, model-call telemetry, genuine exceptions, and the CSV attachment.

**Complete when:** the archive is verified, the ledger is saved with it, and the Discord result accurately reflects live read-back.

## Runtime readiness

Before a live batch, verify an approved image-capable reviewer, Shopify resolver/writer/read-back operations, executable `scripts/betta_batch.py` ledger validation, and dry-run mode are available. Prefer the configured cheap worker; a recorded Sol review is an allowed fallback when the cheap worker is unavailable. If no approved reviewer or validator is available, remain in dry-run and report the blocker. Never substitute an unrecorded manual PASS.
