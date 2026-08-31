---
name: "betta-picture-processing"
description: "Cost-optimised NTA Betta workflow: deterministic processing first, cheap vision for catalogue work, Sol only for genuine exceptions."
version: "2.0.0"
user-invocable: true
---

# NTA Betta Picture Processing v2

Run one end-to-end workflow for labelled individual-Betta photographs while minimising AI cost without weakening identity, Shopify, or archival integrity.

## Core operating rule

Use the cheapest reliable mechanism for each step:

1. **Code / deterministic tools first.**
2. **Cheap vision model for genuine visual interpretation.**
3. **Retry cheap vision once when uncertainty may be recoverable.**
4. **GPT-5.6 Sol only for material ambiguity, conflict, or high-consequence diagnosis.**
5. **Ask David only when model escalation still cannot establish a safe answer.**

Do not use GPT-5.6 Sol for routine file handling, CSV construction, Shopify API calls, formatting, resizing, renaming, archiving, ordinary status messages, or successful verification.

Do not spawn one subagent per fish. Treat one Discord thread as one batch and process fish in a single cheap-model batch pass where practical.

## Shared-module integration

This workflow remains the canonical owner of Betta image integrity, batch ledger, media ordering, archive behaviour and Discord reporting. For Shopify product state it must use the shared contracts:

- resolve the exact individual product/variant through `nta-product-resolver` before mutation;
- use `nta-inventory-state`, `nta-product-availability` and `nta-product-metafields` for the individual-fish inventory, availability and arrival-date decision;
- submit the authorised media/inventory/metafield change set through `nta-shopify-write-verifier`.

The specialised identity assertions below are additional protected-field checks; they do not replace the shared write/read-back operation record.

Read [references/delegation-policy.md](references/delegation-policy.md) before processing.
Read [references/state-machine.md](references/state-machine.md) before any Shopify write.
For batches or handle anomalies, also read [references/batch-integrity.md](references/batch-integrity.md).

---

# 0. Model roles

The implementation must expose these logical roles. Provider/model IDs are configuration, not hard-coded workflow logic.

- `VISION_CHEAP`: default visual worker. Prefer the configured Qwen vision-capable model.
- `VISION_CHEAP_RETRY`: same model or another cheap vision-capable model.
- `REASONING_ESCALATION`: GPT-5.6 Sol.
- `UTILITY_CHEAP`: low-cost text model for concise Discord/status wording where code templates are insufficient.
- `NONE`: deterministic code/tool execution; no model call.

If the configured Qwen model cannot accept images, route visual work to the cheapest configured image-capable model rather than silently sending every image to Sol.

The main OpenClaw agent may remain GPT-5.6 Sol, but this skill must not treat the main model as permission to use Sol for every stage.

---

# 1. Intake — NONE

## Discord source

- Discord intake uses only the private channel ID David designates for `#betta-processing`; never trust a channel name alone.
- One Discord thread = one batch.
- Collect all thread attachments until David posts exactly or semantically equivalently: `@FRED process this Betta batch`.
- Process only genuine source photographs attached in that thread.
- Never mix attachments from other threads, channels, messages, filesystem order, or prior batches.
- Preserve Discord attachment/message IDs in the batch ledger so every local file remains traceable to its source.

## Local paths

- Local fallback source: `/Users/davidlo/Documents/Betta Processing`
- Enhanced output: `/Users/davidlo/Documents/Betta Processed`
- Inventory CSV: `/Users/davidlo/Documents/Betta Processing/betta-inventory.csv`
- Archive root: `/Users/davidlo/Documents/Archived Bettas`
- Shopify credentials: `/Users/davidlo/.openclaw/workspace/nta-betta-picture-processor/.env`

## Intake actions

Use deterministic filesystem/Discord tooling only.

1. Create a unique `batch_id`.
2. Save Discord originals into the source folder without overwriting collisions.
3. Hash every source file with SHA-256.
4. Record:
   - batch ID
   - Discord thread ID
   - Discord message ID
   - attachment ID/name
   - local source path
   - SHA-256
   - file size
   - MIME/type
5. Reject non-image attachments from fish identification while retaining them in the batch ledger.
6. Never use upload sequence to infer tank identity.

No AI call is permitted in this stage.

---

# 2. Visual catalogue — VISION_CHEAP

Open every genuine source photograph and return structured data only.

For each source image determine:

- normalized physical tank ID, e.g. `2 BT 14` → `2BT14`;
- physical photo date;
- whether one identifiable Betta is visible;
- concise customer-friendly proposed title based only on visible colour, pattern, and apparent tail form;
- probable sex: `Male`, `Female`, or `Uncertain`;
- confidence for:
  - tank ID
  - photo date
  - fish identity
  - title
  - sex
- short reason for any uncertainty.

Do not make unsupported strain, genetic, grade, lineage, or colour-stability claims.

## Visual confidence gates

### Tank ID
- `>= 0.90`: accept.
- `0.70–0.89`: run one cheap second pass focused only on the physical label.
- `< 0.70`: cheap retry, then escalate to Sol if still unresolved.
- Never infer an adjacent tank number.

### Photo date
- `>= 0.90`: accept.
- `0.70–0.89`: cheap focused retry.
- `< 0.70`: cheap retry, then Sol.
- If still unclear: `BLOCKED`.

### Fish identity
If the image may contain multiple fish, reflection duplicates, a fish inconsistent with another photo mapped to the same tank, or insufficient visual evidence:
- cheap focused retry;
- then Sol;
- then `BLOCKED` if unresolved.

### Sex
Sex is a catalogue recommendation, not a fact to invent.

- `>= 0.85`: accept `Male` or `Female`.
- `0.60–0.84`: one cheap second visual pass.
- `< 0.60`: use `Uncertain`; escalate to Sol only if the title genuinely requires sex.
- If Sol remains uncertain, do not guess. Set `Sex = Uncertain` and mark `NEEDS_HUMAN_TITLE_CONFIRMATION` if David requires sex in every title.

Long fins or vivid colour alone are not sufficient evidence. Plakats, juveniles, stress, finnage condition, and female morphology can make sex inference unreliable.

## Batch efficiency

Where supported, analyse multiple images in one cheap-model request while keeping a stable `source_file_id` for every result.

Do not resend:
- the whole conversation;
- Shopify product descriptions;
- unrelated historical batch data;
- already accepted images

unless required to resolve a specific conflict.

---

# 3. Human mapping preview — UTILITY_CHEAP or template

Before any Shopify write, tell David the interpreted mapping for the batch:

`source → tank → photo date → proposed title → sex → confidence`

Use a deterministic message template when possible. A cheap text model may be used only to make the message readable.

Do not use Sol merely to compose the preview.

This preview is informational unless an item is `BLOCKED`. Routine PASS items do not require manual approval unless David has separately requested an approval gate.

---

# 4. Shopify discovery — NONE

For each accepted tank ID, call `nta-product-resolver` using the normalized tank ID and live Shopify evidence. Then:

1. Query Shopify by exact normalized tank ID.
2. Confirm exactly one existing individual-Betta product.
3. Never create a product unless David explicitly requests creation.
4. Store in the batch ledger:
   - Shopify Product ID
   - original title
   - tank/title association
   - handle
   - status
   - price
   - cost
   - description
   - vendor
   - product type
   - media IDs/order
   - featured media
   - inventory item/location state
   - arrival date

## Discovery decision

- Exactly one unambiguous product → continue.
- Zero products → `BLOCKED_PRODUCT_NOT_FOUND`.
- More than one plausible product → `BLOCKED_PRODUCT_AMBIGUOUS` and escalate to Sol for diagnosis.
- Tank/product identity conflict → Sol.
- Handle anomaly with stable Product ID → diagnose using [references/batch-integrity.md](references/batch-integrity.md); never repair merely because the handle "looks wrong".

Sol may diagnose a conflict, but it must not override a missing identity chain with a guess.

---

# 5. CSV — NONE

Create or update:

`/Users/davidlo/Documents/Betta Processing/betta-inventory.csv`

with exactly:

`Tank Number,Proposed Title,Cost,Retail Price`

For every clearly identified fish:

- normalized physical tank ID;
- concise photo-faithful proposed title;
- append `Male` or `Female` only when accepted by the sex gate;
- if sex remains uncertain and David has not approved a title, keep the ledger blocked rather than silently inventing sex;
- cost `15.00`;
- retail price `35.00`;
- one row per tank;
- preserve valid rows while the thread batch is still being assembled;
- quote CSV fields correctly.

Programmatically verify:
- exact headers;
- exactly four fields per row;
- one row per accepted source fish;
- no duplicate tank rows;
- no invented tanks;
- fixed cost/retail values;
- no blank accepted tank IDs;
- CSV tank set equals the accepted batch tank set.

The CSV values are recommendations. Do not change live Shopify title, cost, or price unless David explicitly requests it.

No LLM may write or validate CSV syntax when code can do it.

---

# 6. Image preparation

## 6A. Natural reference — NONE by default

Output:

`<Tank ID> Reference.png`

Derive only from the genuine source photo.

Use deterministic image tooling for:
- orientation;
- crop/straighten;
- canvas sizing;
- light exposure;
- white balance;
- modest contrast;
- modest sharpness;
- export.

Rules:
- retain useful aquarium context;
- retain the physical tank/date card when reasonably legible;
- never AI-recreate the fish;
- do not replace the background;
- do not materially intensify colour;
- do not alter anatomy/finnage;
- do not remove the physical card;
- do not add a redundant digital label;
- output 2048 × 2048 where practical without destroying useful natural context.

## 6B. Hero — deterministic first, image tool only if needed

Output:

`<Tank ID>.png`

Target:
- 2048 × 2048 PNG;
- real fish only;
- clean black background;
- room for fins;
- legible bottom-left tank ID and physical photo-date label;
- realistic exposure/colour/contrast/sharpness.

First attempt deterministic segmentation/background cleanup where reliable.

If deterministic segmentation cannot safely distinguish:
- fish from reflection;
- fins from background;
- debris from anatomy;
- duplicate/reflected fish from the real subject;

use the configured image-editing capability for that fish only.

Never instruct a generative image model to redesign, recolour, extend, replace, beautify, or recreate the Betta.

## Image identity checks — NONE + cheap vision only when needed

Programmatically verify:
- dimensions;
- filenames;
- expected tank label text;
- file existence;
- non-zero size;
- one hero/reference pair per accepted tank.

Use `VISION_CHEAP` to compare hero/reference/source only where identity fidelity cannot be established deterministically.

Escalate to Sol only when a material identity conflict remains after cheap comparison.

Do not overwrite existing output unless:
- it belongs to the same current source hash and is a resumable partial batch; or
- David approved replacement.

---

# 7. Shopify Files and mutation — NONE

For each confirmed Product ID, build an explicit authorised change set. Submit it through `nta-shopify-write-verifier`; its writer phase may use the stable typed media and inventory functions below.

1. Query Shopify Files first.
2. Reuse an exact READY asset when identity is established by stable file metadata/hash/name association.
3. Upload only missing assets.
4. Wait for all expected assets to become READY.
5. Replace the superseded hero.
6. Feature the new hero.
7. Put the genuine natural reference at Image 2.
8. Preserve useful genuine extra angles.
9. Remove only obsolete duplicates or clearly superseded photographs of that individual fish.
10. Set `custom.arrival_date` from the physical photo date using `YYYY-MM-DD`.
11. Set individual-fish inventory exactly `1`.
12. Preserve:
    - title
    - price
    - cost
    - description
    - vendor
    - product type
    - handle
    - status
    unless David explicitly requests a change or approves a verified repair.
13. Inspect every mutation response.
14. Inspect every `userErrors` array.
15. A non-empty material `userErrors` array is a hard failure. Do not continue as PASS.

No AI should generate routine GraphQL/REST payloads dynamically once the implementation has stable typed functions for these mutations.

---

# 8. Read-back verification — NONE

Freshly query Shopify after each product mutation through the verifier's independent auditor phase, then perform these Betta-specific assertions.

Verify with exact assertions:

- Product ID unchanged;
- tank/product mapping unchanged;
- title preserved;
- price preserved;
- cost preserved where exposed;
- handle preserved unless approved repair;
- status preserved;
- inventory = `1`;
- arrival date = physical photo date;
- expected hero exists;
- expected reference exists;
- hero is featured;
- reference is Image 2;
- media belong to the intended fish;
- no unexpected media loss.

Classify each ledger item:

- `PASS`
- `FIX_REQUIRED`
- `BLOCKED`

A failed assertion is never converted to PASS by prose reasoning.

## When Sol is allowed here

Use Sol only to diagnose:
- contradictory API state;
- uncertain product/media identity;
- a handle/product mismatch;
- destructive-update risk;
- a state impossible to reconcile from deterministic API responses.

After diagnosis, execute the correction deterministically and read it back again.

---

# 9. Retry and resumability — NONE

The workflow must be idempotent.

Persist a batch ledger after every material transition.

On rerun:
- match source files by SHA-256 and Discord attachment ID;
- reuse accepted catalogue data unless the source changed;
- do not duplicate CSV rows;
- do not duplicate Shopify Files;
- do not duplicate product media;
- do not repeat a successful mutation merely because a later fish failed;
- continue from the first non-PASS state.

A partially completed batch remains resumable and must not be archived.

See [references/state-machine.md](references/state-machine.md).

---

# 10. Rename and archive — NONE

Rename each original to:

`<Tank ID> Original <ARCHIVE-DATE>.<actual extension>`

where `<ARCHIVE-DATE>` is the current `Australia/Sydney` calendar date at the time of archive.

This archive filename date is intentionally distinct from the physical photo date used for `custom.arrival_date`.

Never overwrite a collision. Add a deterministic suffix if needed and record it in the ledger.

Archive only when every ledger item is PASS and all batch-level assertions pass.

Move source contents, including CSV and hidden metadata, to:

`Archived Bettas/YYYY-MM-DD/Betta Processing`

Move hero/reference outputs to:

`Archived Bettas/YYYY-MM-DD/Betta Processed`

After move, verify:

- active source folder contains no files belonging to the completed batch;
- active processed folder contains no files belonging to the completed batch;
- archived original tank set = archived hero tank set = archived reference tank set = CSV tank set;
- every archived file hash can be read;
- ledger is saved in the archive.

Do not archive a batch containing `BLOCKED` or `FIX_REQUIRED`.

---

# 11. Discord result — template / UTILITY_CHEAP

Reply in the originating Discord thread.

Include:

- complete or incomplete batch status;
- processed count;
- catalogued count;
- skipped count;
- uploaded count;
- reused count;
- updated count;
- archived count;
- Sol escalation count;
- cheap vision call count;
- estimated AI cost for the batch;
- estimated AI cost per PASS Betta;
- CSV attachment;
- every PASS tank/date;
- inventory = 1;
- hero/reference live;
- title/price preserved;
- live storefront link using only the handle returned by the final Shopify read-back;
- only genuine `BLOCKED` or `FIX_REQUIRED` exceptions.

Use a deterministic template unless wording genuinely requires a model.

A batch is DONE only when every fish is PASS.

Never expose Shopify credentials, tokens, `.env` contents, hidden authorization headers, or model-provider secrets.

---

# 12. Cost telemetry

The implementation must record actual usage whenever the provider/runtime exposes it.

Per model call capture when available:

- provider;
- model;
- purpose;
- source/tank IDs;
- input tokens;
- output tokens;
- image/input units if exposed;
- provider-reported cost;
- retry flag;
- escalation flag.

Batch summary:

- `cheap_vision_calls`
- `cheap_vision_retries`
- `sol_calls`
- `utility_calls`
- `total_ai_cost_usd`
- `pass_betta_count`
- `ai_cost_per_pass_betta_usd`

If exact provider cost is unavailable, calculate an estimate from a configurable price table. Mark estimates as estimates.

Never hard-code model prices into the workflow logic. Store them in configuration so pricing can be updated without rewriting this skill.

## Cost guard

Default policy:

- routine Sol calls permitted: `0`;
- Sol calls only from an explicit escalation branch;
- if Sol escalation exceeds `max(2, ceil(batch_fish_count * 0.15))`, stop further Sol escalation and report `COST_GUARD_TRIGGERED` unless continued escalation is necessary to prevent a destructive Shopify action;
- a destructive-risk ambiguity always stops rather than guessing.

---

# 13. Final safety invariants

Never:

- guess tank IDs;
- shift photos to adjacent tanks;
- infer identity from upload order;
- create Shopify products unless explicitly requested;
- change live title/price/cost merely because the CSV proposes them;
- overwrite images casually;
- recreate a "natural reference" with AI;
- let a generative edit materially change the fish;
- treat a Shopify mutation request as successful without read-back;
- ignore `userErrors`;
- archive partial batches;
- let cheap-model confidence override deterministic contradictory evidence;
- let Sol override missing evidence with a guess;
- expose credentials.

The goal is not the fewest possible model calls at any cost. The goal is the **lowest-cost workflow that preserves fish identity, Shopify integrity, and auditability**.
