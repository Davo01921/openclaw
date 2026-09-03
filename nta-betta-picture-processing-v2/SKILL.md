---
name: "betta-picture-processing"
description: "Cost-optimised NTA Betta workflow with mandatory image-fidelity QA before Shopify upload."
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

A generated or edited result is only a candidate. It must pass the same identity and presentation QA below before it may be uploaded. If an image-editing result changes pose, anatomy, finnage, markings, colour distribution, or unique visible traits, reject it immediately and fall back to genuine source pixels or mark `FIX_REQUIRED`.

Do not upscale a crop beyond credible source detail. Prefer a smaller authentic fish with clean negative space over a large soft, noisy, or artificially sharpened fish.

## Mandatory pre-upload image QA — NONE + VISION_CHEAP

Run this gate for every hero and reference before any Shopify Files upload.

### Deterministic checks

Verify:
- exact 2048 × 2048 output dimensions where required;
- expected filenames;
- file existence and non-zero size;
- one hero/reference pair per accepted tank;
- expected tank ID and photo date label text;
- a single clean label render with no duplicated, clipped, ghosted, malformed, or overlapping glyphs;
- the complete fish is inside frame with room around every fin;
- no unintended black bars, asymmetric padding, neighbouring tanks, or accidental crop boundaries;
- no obvious overexposure, crushed detail, excessive saturation, excessive sharpening, or enlargement artifacts.

Dimensions, filenames, and file existence alone are never sufficient for PASS.

### Mandatory visual comparison

Use `VISION_CHEAP` to compare source, hero, and reference side by side at useful/full resolution for every fish. Return structured PASS/FAIL fields for:

- same fish identity;
- same pose and orientation;
- same body proportions and anatomy;
- same fin shape, length, edges, and extent;
- same scale pattern and unique markings;
- photo-faithful colour distribution;
- complete subject framing;
- realistic detail without blur, plastic texture, halos, noise amplification, or invented detail;
- clean background and professional composition;
- correct, legible, single-rendered label.

Any material change to fish identity, pose, anatomy, finnage, markings, or colour is an automatic rejection. A changed fish may never be accepted because it looks cleaner or more attractive.

If the cheap comparison is uncertain, run one focused cheap retry. Escalate to Sol only when material identity ambiguity remains. If still unresolved, set `FIX_REQUIRED_IMAGE_QA` or `BLOCKED_IMAGE_IDENTITY`.

### Gate outcome

Persist the QA result and evidence in the batch ledger.

- All deterministic and visual assertions PASS → continue to Shopify upload.
- Presentation defect with intact identity → rebuild deterministically and rerun the full gate.
- Identity change, invented detail, or unresolved comparison → reject the candidate; do not upload.
- Any failed image assertion → item state `FIX_REQUIRED`; the batch may not be archived or marked DONE.

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

## Correcting an already-live bad hero

When David explicitly requests correction of an already-live hero:

1. Rebuild a versioned candidate from the genuine archived source.
2. Run the complete mandatory pre-upload image QA.
3. Query fresh live product/media state and protect Product ID, tank mapping, title, price, cost, description, vendor, product type, handle, status, inventory, arrival date, reference media, and useful extra angles.
4. Upload the corrected candidate as a new READY Shopify File.
5. Add it as product media and wait for READY.
6. Feature and move the corrected hero to Image 1.
7. Keep the genuine natural reference at Image 2.
8. Delete only the specifically superseded bad hero after the replacement is READY and ordered.
9. Perform the complete fresh read-back verification.
10. Preserve the rejected candidate only for diagnosis; never upload it.

A failed correction leaves the existing live media intact whenever possible and records `FIX_REQUIRED`.

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
- the uploaded hero is the exact image-QA-approved file/version;
- the approved hero and reference still satisfy the mandatory visual identity assertions;
- label rendering remains correct in the delivered asset;
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
