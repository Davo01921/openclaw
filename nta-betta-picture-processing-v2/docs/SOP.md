# NTA Betta Picture Processing — Standard Operating Procedure

**Status:** Canonical V2.1 — READY FOR FINAL LIVE ACCEPTANCE
**Version:** 2.1  
**Date:** 2026-09-13  
**System:** `betta-picture-processing`

## 1. Purpose

This SOP defines the operational process for onboarding one or more individual Bettas from labelled source photographs into Shopify while preserving traceability, image fidelity, title consistency, inventory accuracy, telemetry, and audit evidence.

The workflow is fail-closed. If a required identity, title component, image QA assertion, Shopify mapping, mutation verification, or runtime dependency is unresolved, the affected fish must not be written to Shopify.

## 2. Required outcome

Every successfully onboarded Betta must finish with:

- one exact Shopify product mapping;
- one deterministic Shopify title;
- `custom.arrival_date` set from the physical photo label;
- inventory set to exactly `1`;
- approved hero as Image 1;
- complete original source photograph as Image 2;
- protected Shopify fields unchanged;
- fresh read-back verification PASS;
- one per-tank telemetry record;
- archived batch evidence.

## 3. Deterministic title rule

The Shopify title MUST be exactly:

`<Tank Number> - <Fish Name> <Tail Type> <Male/Female>`

Examples:

- `4BT41 - Turquoise White Red Marble Halfmoon Male`
- `2BT14 - Galaxy Koi Halfmoon Plakat Female`

Rules:

- `Fish Name` contains only the supported visible colour/pattern/descriptive name.
- `Tail Type` is a separate required component and must be written in full, for example `Halfmoon` or `Halfmoon Plakat`.
- Do not use abbreviations such as `HM` or `HMPK` in the final Shopify title.
- Sex defaults to `Male`.
- Use `Female` only when visual evidence supports Female at confidence `>= 0.85`.
- If sex is unknown, uncertain, missing, or below the Female threshold, use `Male`.
- The model may identify components, but deterministic code constructs the final title.
- If tank number, fish name, or tail type is unresolved, stop before Shopify.

## 4. Intake

Accepted sources:

- the designated private Discord Betta-processing thread; or
- `/Users/davidlo/Documents/Betta Processing`.

For each fish:

1. Save the original source without overwriting.
2. Record the source path, size, MIME type, SHA-256, batch/thread/message/attachment IDs where available.
3. Record immutable `date_entered` in Australia/Sydney time when the fish first enters the processing ledger.
4. Never mix photographs from separate batches or infer identity from filesystem ordering.

`date_entered` is not the same as `arrival_date`.

## 5. Visual catalogue

For each source image, the vision stage must determine:

- tank ID and confidence;
- physical photo date and confidence;
- one-fish visibility;
- fish name;
- tail type;
- sex evidence and confidence;
- uncertainty reasons.

Normalize tank IDs such as `2 BT 14` to `2BT14` and dates such as `21/8/2026` to `2026-08-21`.

Do not infer an adjacent tank. Do not invent lineage, genetics, grade, colour stability, or specialist variety unsupported by the photograph.

Tank/date confidence handling:

- `>= 0.90`: accept;
- `0.70–0.89`: one focused cheap retry;
- `< 0.70`: retry once, then minimal-evidence escalation;
- unresolved: `BLOCKED_VISUAL`.

After acceptance, code constructs and validates the deterministic title.

## 6. Parallel preparation fork

After `VISUAL_ACCEPTED`, two independent branches may run in parallel:

### Branch A — Shopify resolution

1. Resolve the tank against live Shopify.
2. Require exactly one existing individual-Betta product.
3. Never create a product implicitly.
4. Record Product ID and full pre-write snapshot including title, description, price, cost, vendor, product type, handle, status, media/order, inventory and arrival date.

### Branch B — Hero generation

1. Generate the 2048 × 2048 hero using the approved image pipeline.
2. Preserve fish identity and supported visual characteristics.
3. Retain source/output hashes and image-generation telemetry.
4. Keep the complete original source photograph unchanged for Image 2.

The total number of concurrent external operations must not exceed `4`.

## 7. Resume behaviour

Successful work must not be repeated unnecessarily.

- If Shopify resolution succeeds but Grok/image generation fails, rerun only the missing image branch.
- If image generation succeeds but Shopify resolution fails, rerun only the Shopify branch.
- If both branches are complete, do not repeat either branch.
- Retries resume from the last valid persisted checkpoint.

The workflow may join into the next processing stage only after both preparation branches are valid.

## 8. Inventory CSV

Write:

`/Users/davidlo/Documents/Betta Processing/betta-inventory.csv`

with exactly:

`Tank Number,Proposed Title,Cost,Retail Price`

Rules:

- `Proposed Title` is the deterministic final Shopify title.
- Copy cost and retail from the live pre-write Shopify snapshot.
- Do not use fixed price/cost recommendations.
- Require exact headers and one unique row per accepted tank.

## 9. Image QA

For each fish, compare source, hero and original reference.

Required deterministic checks include:

- dimensions;
- filenames;
- label;
- framing;
- original-reference hash equality.

Required visual checks include:

- same identity;
- body anatomy;
- scale markings;
- regional colour;
- tail/fins/pose;
- complete framing;
- realistic texture;
- hero composition;
- label;
- reference integrity.

Reject changed identity, invented markings, implausible anatomy, wrong tail form, materially recoloured regions, plastic texture, severe halos, unsupported detail, or incomplete evidence.

Every mandatory assertion must PASS before upload.

## 10. Authorised Shopify mutation

Only the following fields may change:

- title → deterministic expected title;
- `custom.arrival_date` → physical photo date;
- inventory → exactly `1`;
- approved media/order.

Feature:

- Image 1 → approved hero;
- Image 2 → complete uncropped original source photograph.

Protected fields must remain identical to the pre-write snapshot:

- description;
- price;
- cost;
- vendor;
- product type;
- handle;
- status.

Any transport error, GraphQL error, or material `userErrors` result stops the item.

## 11. Fresh read-back verification

After mutation, query Shopify again independently and verify:

- Product ID unchanged;
- tank mapping unchanged;
- title exactly matches deterministic title;
- protected fields unchanged;
- arrival date equals physical photo date;
- inventory equals `1`;
- approved hero is Image 1;
- complete original is Image 2;
- no unintended media loss occurred.

Failure produces `FIX_REQUIRED`; prose must not override a failed assertion.

## 12. Telemetry

Before a fish becomes `PASS`, record/update one row in:

`~/Documents/Betta Processing/betta-telemetry.sqlite3`

Required operational fields include:

- tank number;
- date entered;
- arrival date;
- onboarding start;
- Shopify verified timestamp;
- onboarding seconds;
- archive completion timestamp;
- end-to-archive seconds;
- model call count;
- retry count;
- Grok call count;
- input tokens;
- output tokens;
- Grok/xAI cost;
- cost currency/source;
- slowest workflow state;
- slowest-state seconds;
- state-duration data;
- provider/model summary;
- Shopify Product ID;
- final title.

### Grok cost rule

Current NTA fallback cost is **USD 0.07 per Grok image generation/edit call**.

If xAI reports an actual billed cost, use the provider-reported value. Otherwise use the configured/default USD 0.07 fallback and record its cost source. Do not represent an unknown cost as zero.

## 13. Onboarding-time definition

Primary onboarding KPI:

`first ledger entry → successful fresh Shopify read-back`

This is stored as `onboarding_seconds`.

Archive time is measured separately so file housekeeping does not distort onboarding performance.

## 14. Archive and report

Archive only successful fish/batches.

Store source files, outputs, CSV, ledger and telemetry export under the dated archive structure. Verify file hashes after moving.

The final Discord/report result should include:

- PASS/blocked counts;
- tank numbers;
- physical arrival dates;
- final deterministic titles;
- protected-field confirmation;
- inventory result;
- media result;
- Shopify/storefront links where available;
- input/output token totals;
- Grok cost;
- onboarding time;
- retry count;
- genuine exceptions.

## 15. First live-test SOP

Use one Betta only.

The test is PASS only if all of the following are true:

1. Tank ID is correct.
2. Final title follows the exact deterministic format.
3. Unknown/uncertain sex resolves to Male.
4. Shopify maps to the correct existing product.
5. Hero generation and Shopify resolution use the parallel-preparation design.
6. Image 1 is the approved hero.
7. Image 2 is the unchanged original source.
8. Inventory is `1`.
9. Arrival date matches the physical label.
10. Protected Shopify fields remain unchanged.
11. Fresh read-back passes.
12. Telemetry row exists.
13. Input/output tokens are captured when reported.
14. Grok cost is captured using provider cost or the USD 0.07 fallback.
15. `onboarding_seconds` is populated.
16. Retry/checkpoint behaviour does not repeat already-completed work.

If any item fails, do not expand the test to a larger batch until the cause is diagnosed and corrected.

## 2026-10-02 closeout constraints

V2.1 is the only production processing workflow; experimental V3 is deferred. Before mutation, record a fresh exact Product/Variant/Location/tank snapshot with DENY and tracked inventory. Only ACTIVE individual products with stock 0 or 1 are eligible; zero stock requires explicit new-fish authority tied to the source reference and hash. Negative/multiple stock and inactive products hold for operator review. Photo/text conflicts must be resolved explicitly; no adjacent tank inference.

Fresh independent readback must include exact variant/location and protected fields. ARCHIVED requires existing source and hero files with approved hashes and a verification timestamp; update paths when moving files. Shopify status remains protected: evidence archiving is not authority to archive a sold Shopify product. Serialize ledger writes and retain source references for cross-batch duplicate checks. See CLOSEOUT.md for one final live acceptance exercise and recovery.
