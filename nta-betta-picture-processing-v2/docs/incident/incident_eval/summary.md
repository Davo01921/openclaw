# Real pipeline evaluation — incident photo (A5, 2026-10-15)

Centre-piece evaluation for the 2BT23 incident regression suite. Everything
below was executed from the worktree
`/Users/davidlo/openclaw-skills-incident-repair` (branch
`codex/betta-identity-incident-20261015`) against the byte-immutable fixture
`tests/fixtures/incident_2bt23/incident-photo.png`
(`sha256 6e4a4f573f8cfc829218f798eeb5b45cd08803689d31d7db6fce4920cdca9ca9`).
No Shopify call was made; no Grok/generation call was made; nothing outside the
scratch root (`/private/var/folders/f0/ncwpvltd3_sfbjtbnct70dnm0000gn/T/opencode/incident-eval`)
and this directory was written.

## Exact commands

```sh
# sandbox driver for the genuine identification run (driver lives outside the
# scratch root it wipes)
/Users/davidlo/openclaw-skills-v3/nta-betta-picture-processing-v2/.venv/bin/python -B \
  /private/var/folders/f0/ncwpvltd3_sfbjtbnct70dnm0000gn/T/opencode/incident-eval-worker/run_eval.py

# preparation-stage probe (real preflight + prep-QA; identification plumbed)
/Users/davidlo/openclaw-skills-v3/nta-betta-picture-processing-v2/.venv/bin/python -B \
  /private/var/folders/f0/ncwpvltd3_sfbjtbnct70dnm0000gn/T/opencode/incident-eval-worker/run_probe.py

# archival copy (verbatim)
cp <scratch>/evidence/*.json docs/incident/incident_eval/real-run-*
cp <scratch>/probe/evidence/*.json docs/incident/incident_eval/probe-prep-*
```

Both drivers are archived verbatim alongside this file
(`eval_driver_identification.py`, `eval_driver_preparation_probe.py`). They
build a real `scripts/betta_batches.create_batch` workspace, a dispatcher-owned
`state/sources.json` (mode 444), a `GenerationBudget`, and strict adapters from
`scripts/betta_adapters.make_adapters(..., selected_sources=…)` with
`live_shopify=False`, `live_generation=False` and the default (disabled) policy
whose `paid_generation_authorised()` is `False`.

## Live call inventory (5 real vision calls used; budget ≤ 6)

| # | Stage | Mode | Provider / model | call_id | Result |
|---|---|---|---|---|---|
| 1 | run 1 identification | catalogue (full frame, real) | `openai / gpt-5.6-sol` | `7bd0c9e7-e995-4969-a132-06454958d278` | tank `2BT23` (0.98), date `2026-04-10` (0.88) |
| 2 | run 1 bounded re-evaluation | label crop (`betta_prepare.label_crop`, real) | `openai / gpt-5.6-sol` | `f2290da7-df4f-4825-a7e1-da446e5146df` | tank `2BT23` (0.99), date `2026-10-14` (0.95), price `35` |
| 3 | probe preparation | preflight (raw frame, real) | `openai / gpt-5.6-sol` | `32d8e749-5534-48b4-929a-4a70d39ac65b` | tank `2BT23` (0.99), date `2026-10-14` (0.93) |
| 4 | probe preparation | prep-QA `FULL` (raw + prepared, real) | `openai / gpt-5.6-sol` | `90f5a370-0c60-41ee-ac38-6e9c3d5318c3` | `overall FAIL` (faithful_colours false, lighting_usable false) |
| 5 | probe preparation | prep-QA `L1` (raw + prepared, real) | `openai / gpt-5.6-sol` | `1fac205a-ced5-48ab-a88b-3ff58114e4ad` | `overall FAIL` (same two criteria) |

Two earlier catalogue attempts from the first sandbox invocation exited before
reaching any provider (the `openclaw` CLI could not find `node` on the harness
`PATH` during route resolution); they are **not** model calls and consumed no
budget. All five calls above attested `openai / gpt-5.6-sol`
(`execution_attested: true`, `fallback_used: false`).

## Run 1 — genuine identification run (REAL dual reads)

Artifacts (verbatim): `real-run-summary.json`, `real-run-process-state.json`,
`real-run-catalogue-receipt.json`, `real-run-label-retry-receipt.json`,
`real-run-label-crop.png`.

- Batch `betta-20261015-105638-vccnto`; source sha bound in intake, catalogue
  receipt and retry receipt: `6e4a4f…9ca9ca9`.
- Catalogue read (call 1, verbatim): tank `2BT23` (tank_confidence **0.98**);
  date `2026-04-10` (date_confidence **0.88** — below the pipeline's 0.90
  gate); `one_fish_visible: true`; fish_name `Pastel Pink`; tail
  `Halfmoon Plakat`; sex `Male`; the model itself flagged
  *"Handwritten date could be interpreted as 4/10/2026 or 14/10/2026."*
- Because the date confidence is below 0.90 the read is treated as **not
  confident** (`uncertain_reason: "catalogue confidence below 0.90"`), so the
  pipeline did not accept an identity and ran its one bounded re-evaluation.
- Focused label-crop read (call 2, verbatim): crop created by
  `betta_prepare.label_crop` (`rect_px [0,0,1512,477]`, sha
  `b6cbc02721b2071d01fe7e16f48cea2b043842bec7478d45ac8b5f80f12107f1`); tank
  `2BT23` (0.99), date `2026-10-14` (0.95), price `35`, reasons reading the
  card exactly.
- The retry read **contradicted the catalogue's readable date**
  (`catalogue date 2026-04-10 vs label date 2026-10-14`): the pipeline marked
  `RETRY_CONFLICT` and **quarantined** the fish. No majority vote, no silent
  swap to the crop value.
- Terminal summary: `{status: PARTIAL, published: 0, quarantined: 1,
  manifest_sha256: null}`; no manifest, no authority, no generation, no
  Shopify call, `executed: []`. (These are the same semantics A4's integration
  suite pins: a confident contradiction quarantines; a re-evaluation may never
  redirect identity.)

## Probe — prepared-image stage (REAL preflight + prep-QA)

Artifacts (verbatim): `probe-prep-summary.json`,
`probe-prep-process-state.json`, `probe-prep-catalogue-receipt.json`,
`probe-prep-label-receipt.json`, `probe-prep-preparation-receipt.json`.

**What is mocked and what is real:** to let the pipeline reach the
prepared-image stage on the genuine photo (run 1 honestly quarantined at
identification), the probe's catalogue + corroboration reads were mocked to
exactly **A2's recorded focused-label values** (tank `2BT23`, date
`14/10/2026`, confidences 0.99 / 0.96, price `35`; provider `mock-router`). The
mocked receipts are labelled `probe-prep-*` and are **not** OCR evidence. The
preflight and prep-QA calls ran **live on the raw incident bytes** and are real
evidence.

- Dual-read result: `AGREE` (tank `2BT23`, date `2026-10-14`).
- Batch `betta-20261015-110404-16gddf`; the run stopped at
  `{status: AWAITING_AUTHORISATION, stage: PREPARED}` — paid generation was not
  authorised, so no Grok spend.
- Real preflight (call 3): tank `2BT23` (0.99), date `2026-10-14` (0.93) →
  `identity_cross_check: AGREES` with the identified identity.
- Real prep-QA (calls 4–5): both deterministic preparation levels (`FULL`,
  `L1`) were **rejected** by the model (`faithful_colours: false`,
  `lighting_usable: false`: exposure/contrast increase with clipped highlights
  and a pink cast beyond a mild bounded correction). The pipeline correctly
  fell back to the untouched camera original (`FALLBACK_RAW`), recording both
  attempts verbatim — it did not fabricate a pass.
- Working image: `2BT23-working-raw.png`, a distinct file from the source,
  byte-identical to the raw in fallback (sha `6e4a4f…9ca9ca9`); the raw source
  sha was unchanged before/after.

## Assessment vs acceptance requirement A (2BT23 / 2026-10-14)

- The pipeline's vision reads **identified the correct tank `2BT23` in every
  single call** (catalogue 2BT23, crop 2BT23, preflight 2BT23).
- The correct photograph date `2026-10-14` was read by the focused crop read
  (0.95) and by the preflight (0.93). The full-frame catalogue read misread it
  as `2026-04-10` at low confidence (0.88) — exactly the class of error the
  0.90 gate exists for, and the pipeline **did not accept it**: it quarantined
  the contradiction instead of proceeding.
- The incident outcome (a wrong tank `5BT43` accepted and mutated) is
  impossible on this path for this photo: the only confident tank readings were
  `2BT23`, and the pipeline never emits an accepted identity from a
  contradiction.
- The prepared-image stage additionally refused to pass a visually degraded
  derivative, falling back to the raw original rather than feeding a rejected
  working image to generation.

## Caveats

- The evaluation is single-sample (n=1 photo) by design, inside a 6-call cap.
- The probe's identification is plumbed (mocked) solely to reach the prep
  stage; only run 1's identification is a genuine end-to-end read.
- Timestamps above are UTC; the incident predates this repair and no Shopify
  state was touched.
