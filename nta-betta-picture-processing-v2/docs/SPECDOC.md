# NTA Betta Picture Processing — System Specification

**Status:** Current live-test specification  
**Version:** 2.1  
**Date:** 2026-09-13  
**Applies to:** `betta-picture-processing`

## 1. Scope

This specification defines the required behaviour of the NTA individual-Betta onboarding workflow from labelled source image through verified Shopify state, telemetry and archive.

It is normative. If implementation behaviour conflicts with this document, the workflow must be treated as non-compliant until resolved.

## 2. Core invariants

### SPEC-ID-001 — Stable fish identity

Every fish MUST maintain a traceable mapping:

`source attachment → source SHA-256 → tank/date evidence → exact Shopify Product ID`

No adjacent-label inference or filesystem-order inference is permitted.

### SPEC-ID-002 — Existing product only

The workflow MUST resolve exactly one existing Shopify product per accepted fish.

The workflow MUST NOT implicitly create a product.

### SPEC-ID-003 — Unique product mapping

Within a batch, two individual fish MUST NOT resolve to the same Shopify Product ID.

## 3. Title specification

### SPEC-TITLE-001 — Exact format

The Shopify title MUST be exactly:

`<Tank Number> - <Fish Name> <Tail Type> <Male/Female>`

### SPEC-TITLE-002 — Tank number

The tank number MUST equal the accepted item/tank identity and MUST appear first in the final title.

### SPEC-TITLE-003 — Fish name

`Fish Name` MUST represent only supported visible colour/pattern/descriptive traits.

It MUST NOT contain:

- tank number;
- tail type;
- Male/Female;
- unsupported lineage/genetics/grade claims.

### SPEC-TITLE-004 — Tail type

Tail type is mandatory.

It MUST be written in full, for example:

- `Halfmoon`
- `Halfmoon Plakat`

Abbreviations such as `HM` and `HMPK` MUST NOT appear in the final title.

### SPEC-TITLE-005 — Sex default

Canonical sex MUST be `Male` unless Female is positively classified at confidence `>= 0.85`.

Unknown, absent, ambiguous or low-confidence sex MUST resolve to `Male`.

### SPEC-TITLE-006 — Deterministic authority

A model MAY classify `fish_name`, `tail_type` and sex evidence.

A model MUST NOT be authoritative for the final title string.

Deterministic code MUST construct and validate the final title.

### SPEC-TITLE-007 — Mutation/read-back enforcement

The deterministic expected title MUST be checked:

1. before Shopify mutation; and
2. after fresh Shopify read-back.

Any deviation MUST fail closed.

## 4. Date specification

### SPEC-DATE-001 — Date entered

`date_entered` MUST represent the Australia/Sydney timestamp when the fish first enters the processing ledger.

It MUST remain stable for that processing record.

### SPEC-DATE-002 — Arrival date

`arrival_date` MUST be derived from the physical photo/tank label and normalized to `YYYY-MM-DD`.

### SPEC-DATE-003 — Date separation

`date_entered`, `arrival_date` and archive date are separate concepts and MUST NOT be conflated.

## 5. Visual catalogue specification

### SPEC-VIS-001 — Structured output

The catalogue stage MUST produce or derive structured values for:

- tank ID;
- tank confidence;
- physical photo date;
- date confidence;
- one-fish visibility;
- fish name;
- tail type;
- sex evidence;
- sex confidence;
- uncertainty reasons.

### SPEC-VIS-002 — Tank/date threshold

Tank/date confidence handling MUST follow:

- `>= 0.90`: accept;
- `0.70–0.89`: one focused cheap retry;
- `< 0.70`: retry then minimal-evidence escalation;
- unresolved: block before Shopify.

### SPEC-VIS-003 — Unsupported claims

The system MUST NOT claim unsupported lineage, genetics, grade, colour stability or specialist variety.

## 6. Parallel preparation specification

### SPEC-PAR-001 — Fork point

After `VISUAL_ACCEPTED`, Shopify resolution and hero generation MUST be independently schedulable.

### SPEC-PAR-002 — Shopify branch

The Shopify branch MUST produce a valid exact Product ID plus a complete pre-write snapshot.

### SPEC-PAR-003 — Hero branch

The image branch MUST produce a valid hero asset record with file path, SHA-256 and generation evidence.

### SPEC-PAR-004 — Join gate

The workflow MUST NOT progress beyond the parallel preparation checkpoint until both branches are valid.

### SPEC-PAR-005 — Resume semantics

If one branch is valid and the other is missing/failed, rerun MUST schedule only the missing/failed branch.

Valid completed work MUST NOT be repeated solely because the workflow restarts.

### SPEC-PAR-006 — Concurrency ceiling

Total concurrent external operations MUST NOT exceed `4` under the current configuration.

## 7. Image specification

### SPEC-IMG-001 — Hero dimensions

The approved hero MUST be 2048 × 2048 pixels.

### SPEC-IMG-002 — Hero presentation

The hero SHOULD present:

- one fish;
- near-black clean background;
- complete fin framing;
- believable exposure/colour;
- realistic anatomy and texture;
- no text, labels, hands, tank borders, reflections or props.

### SPEC-IMG-003 — Identity preservation

The hero MUST remain recognizably the same fish based on body proportions, scale layout, markings, regional colour distribution, tail type and anatomy.

### SPEC-IMG-004 — Original Image 2

Shopify Image 2 MUST be the complete original source photograph.

Its bytes and SHA-256 MUST match the saved source.

It MUST NOT be cropped, resized, recompressed, relabelled or converted.

## 8. Image QA specification

### SPEC-QA-001 — Mandatory QA

Image QA MUST run before Shopify media mutation.

### SPEC-QA-002 — Deterministic assertions

Required deterministic assertions include:

- dimensions;
- filenames;
- label;
- framing;
- original-reference hash integrity.

### SPEC-QA-003 — Visual assertions

Required visual assertions include:

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

### SPEC-QA-004 — Fail closed

Missing evidence, unapproved candidate version or any mandatory failed assertion MUST prevent upload.

## 9. Shopify mutation specification

### SPEC-SHP-001 — Authorised mutation keys

Only the following product changes are authorised:

- title;
- arrival date;
- inventory;
- approved media/order.

### SPEC-SHP-002 — Inventory

Individual-Betta inventory MUST be set to exactly `1`.

### SPEC-SHP-003 — Media order

Image 1 MUST be the approved hero.

Image 2 MUST be the unchanged original source photograph.

### SPEC-SHP-004 — Protected fields

The following MUST remain equal to the pre-write snapshot:

- description;
- price;
- cost;
- vendor;
- product type;
- handle;
- status.

### SPEC-SHP-005 — Error handling

Transport errors, top-level GraphQL errors and material Shopify `userErrors` MUST fail the item.

## 10. Fresh read-back specification

### SPEC-RB-001 — Independent read-back

The workflow MUST query Shopify again after mutation rather than treating mutation success as proof of final state.

### SPEC-RB-002 — Required assertions

Read-back MUST verify:

- exact Product ID;
- deterministic title;
- protected fields unchanged;
- arrival date;
- inventory `1`;
- hero as Image 1;
- original source as Image 2;
- no unintended media loss.

### SPEC-RB-003 — Verification state

A fish MUST NOT be treated as successfully onboarded until fresh read-back passes.

## 11. Telemetry specification

### SPEC-TEL-001 — Operational database

Per-fish telemetry MUST be stored in:

`~/Documents/Betta Processing/betta-telemetry.sqlite3`

The live SQLite database is the operational source of truth.

### SPEC-TEL-002 — Primary key

The logical record identity MUST be `(batch_id, tank_number)`.

### SPEC-TEL-003 — Required fields

Each successful fish record MUST capture at minimum:

- batch ID;
- tank number;
- date entered;
- arrival date;
- onboarding start;
- Shopify verified time;
- onboarding seconds;
- model-call count;
- retry count;
- Grok-call count;
- input tokens;
- output tokens;
- Grok cost;
- cost currency/source;
- Shopify Product ID;
- final title.

### SPEC-TEL-004 — Efficiency fields

The system SHOULD capture:

- archive-completed time;
- end-to-archive seconds;
- slowest state;
- slowest-state seconds;
- state durations;
- provider/model summary;
- unknown-cost-call count.

### SPEC-TEL-005 — Token accounting

Input/output token totals MUST include attributable retries and failed attempts when provider/runtime usage is reported.

The system MUST NOT fabricate unreported token usage.

### SPEC-TEL-006 — Grok cost

Current fallback Grok cost is:

`USD 0.07 per image generation/edit call`

Cost priority MUST be:

1. provider-reported billed cost;
2. configured/default USD 0.07 per-call rate;
3. unknown/null if neither is available.

Unknown MUST NOT be represented as zero.

### SPEC-TEL-007 — GitHub export

CSV telemetry exports MAY be committed to GitHub or retained with archived batch evidence.

A committed SQLite binary MUST NOT become the live transactional database.

## 12. Timing and efficiency specification

### SPEC-PERF-001 — Onboarding KPI

Primary onboarding time MUST be measured as:

`first ledger entry → successful fresh Shopify read-back`

and stored as `onboarding_seconds`.

### SPEC-PERF-002 — Archive timing

Archive completion MUST be measured separately so archive/file housekeeping does not distort the onboarding KPI.

### SPEC-PERF-003 — Bottleneck measurement

The implementation SHOULD calculate state-level wall-clock durations and identify the slowest state per fish.

### SPEC-PERF-004 — Rolling analysis

The system SHOULD support rolling summaries including:

- median onboarding time;
- average onboarding time;
- p90 onboarding time;
- retry rate;
- average tokens;
- Grok spend;
- slowest workflow states.

## 13. CSV specification

### SPEC-CSV-001 — Inventory CSV path

The workflow MUST create:

`/Users/davidlo/Documents/Betta Processing/betta-inventory.csv`

### SPEC-CSV-002 — Headers

Headers MUST be exactly:

`Tank Number,Proposed Title,Cost,Retail Price`

### SPEC-CSV-003 — Values

The proposed title MUST be the deterministic final title.

Cost and retail MUST be copied from the live Shopify pre-write snapshot.

## 14. Failure specification

### SPEC-FAIL-001 — Visual block

Unresolved tank/date/title components MUST block before Shopify.

### SPEC-FAIL-002 — Product block

Missing/ambiguous Shopify identity MUST block mutation.

### SPEC-FAIL-003 — QA failure

Image-QA failure MUST prevent media/product mutation.

### SPEC-FAIL-004 — Read-back failure

Fresh read-back failure MUST result in `FIX_REQUIRED` or equivalent non-success state.

### SPEC-FAIL-005 — No prose override

Human/model prose MUST NOT convert a failed deterministic assertion into PASS.

## 15. Archive specification

### SPEC-ARC-001 — Archive gate

Only successfully verified fish/batches may be archived as complete.

### SPEC-ARC-002 — Evidence retention

Archive evidence SHOULD include:

- originals;
- heroes;
- inventory CSV;
- batch ledger;
- telemetry CSV export;
- hashes/verification evidence.

## 16. CI specification

### SPEC-CI-001 — Compilation

All Betta Python scripts MUST compile in CI.

### SPEC-CI-002 — Unit tests

Betta unit tests MUST pass before the repository version is considered ready for live testing.

### SPEC-CI-003 — Required coverage areas

Tests SHOULD cover:

- exact title contract;
- default-Male rule;
- confident Female rule;
- missing title components;
- protected mutation boundary;
- hash integrity;
- duplicate Product IDs;
- fork/join readiness;
- missing-branch resume;
- concurrency ceiling;
- telemetry/timing calculations.

## 17. Live-test acceptance criteria

The initial one-Betta live test is accepted only when all criteria below pass:

| ID | Criterion | Expected result |
|---|---|---|
| LT-01 | Tank identification | Correct tank |
| LT-02 | Title | Exact deterministic format |
| LT-03 | Sex fallback | Unknown/uncertain → Male |
| LT-04 | Shopify product | Correct existing Product ID |
| LT-05 | Parallel prep | Shopify/Grok independently schedulable |
| LT-06 | Resume | Completed preparation branch not repeated |
| LT-07 | Hero | Approved 2048×2048 hero as Image 1 |
| LT-08 | Original | Exact unchanged source as Image 2 |
| LT-09 | Arrival date | Matches physical label |
| LT-10 | Inventory | Exactly 1 |
| LT-11 | Protected fields | No unintended changes |
| LT-12 | Read-back | Fresh verification PASS |
| LT-13 | Tokens | Reported input/output captured |
| LT-14 | Grok cost | Provider cost or USD 0.07 fallback captured |
| LT-15 | Timing | `onboarding_seconds` populated |
| LT-16 | Telemetry | One valid row for batch/tank |
| LT-17 | Errors | No hidden/ignored material errors |

A failure in any mandatory criterion stops rollout to a larger production batch until corrected.

## 18. Change-control rule

Any future change that alters title semantics, Shopify mutation authority, identity resolution, image fidelity rules, telemetry accounting, onboarding-time definition, concurrency or retry behaviour MUST update this specification and corresponding tests in the same change set.
