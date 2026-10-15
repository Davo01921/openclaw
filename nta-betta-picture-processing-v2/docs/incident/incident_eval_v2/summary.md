# Real pipeline evaluation v2 — incident photo on POST-REFINEMENT code (A5, 2026-10-15)

Re-verification run for independent-review finding **M1** (*evidence drift*): the
v1 archive (`docs/incident/incident_eval/`) was produced before commit
`cba92e2` added the gate-aware retry refinement, so its `RETRY_CONFLICT` +
quarantine outcome is historical and not reproducible at HEAD. This v2 archive
records the current behaviour. **The v1 archive is untouched.**

- Worktree HEAD during these runs: `4f6462ee92ef47e8fcf6b73b1b2b2b662b49e973`
  (dirty worktree: only A5's uncommitted test-file portability change).
- Source: `tests/fixtures/incident_2bt23/incident-photo.png`, SHA-256
  `6e4a4f573f8cfc829218f798eeb5b45cd08803689d31d7db6fce4920cdca9ca9`, raw bytes
  unchanged before/after every run.
- Method identical to v1: real `betta_batches.create_batch` workspace,
  dispatcher-owned `state/sources.json` (mode 444), `GenerationBudget`, strict
  adapters from `make_adapters(..., selected_sources=…)`, `live_shopify=False`,
  `live_generation=False`, default policy (`paid_generation_authorised() ==
  False`) so accepted fish stop at `AWAITING_AUTHORISATION` — no Grok spend, no
  Shopify call, nothing written outside the scratch root and this directory.

## Live-call budget: 4 real vision calls used (≤ 6)

| Driver | Live calls | Result |
|---|---|---|
| `eval_driver_run_v2.py` (full genuine run) | 2 | fresh sample: both catalogue gates PASS → confident contradiction → QUARANTINED (PARTIAL) |
| `eval_driver_probe2_v2.py` (live identification probe; prepared-image stage mocked to stay in budget) | 2 | catalogue date **BELOW GATE** → `RETRY_ACCEPTED` → 2BT23 / 2026-10-14 → PREPARED → `AWAITING_AUTHORISATION` |
| `eval_driver_replay_v2.py` (deterministic replay of the recorded v1 reads) | 0 | `RETRY_ACCEPTED` → 2BT23 / 2026-10-14 → PREPARED → `AWAITING_AUTHORISATION` |

All four live calls attested `openai / gpt-5.6-sol`
(`execution_attested: true`, `fallback_used: false`; call ids below). No other
model call was made anywhere in this evaluation.

## Run 1 — genuine full run (`v2-run-*`)

Batch `betta-20261015-153932-unirxk`, 2 live calls:

| # | Stage | call_id | Verbatim result |
|---|---|---|---|
| 1 | catalogue (full frame) | `fe034231-3c87-4b00-8a83-f5ef528fc5c8` | tank `2BT23` @**0.91** gate PASS; date `2026-04-10` @**0.93** gate PASS; `uncertain: false` |
| 2 | focused label corroboration | `c0f8bfed-1f9d-4ae0-bba7-3918c2f655e7` | tank `2BT23` @0.99 / date `2026-10-14` @0.96 / price `35`; comparator `DISAGREE` (`date mismatch: full=2026-04-10 label-crop=2026-10-14`) |

Outcome (verbatim): entry status `QUARANTINED`, `label_reads.status: DISAGREE`,
quarantine note `label read disagreement: full=2BT23, crop=2BT23; date
full=2026-04-10, crop=2026-10-14`; batch `{status: PARTIAL, published: 0,
quarantined: 1, manifest_sha256: null}`; no manifest, no authority, no
generation, no Shopify call.

**Why this differs from the expectation:** this fresh sample's confidence
numbers differ from the v1 reading (model variance): v1 recorded
tank 0.98 / date **0.88 (below gate)**; this sample returned tank 0.91 / date
**0.93 (above gate)**. With a confident catalogue date the pinned
confident-vs-confident rule applies (no retry exists for confident
contradictions) and the fish is quarantined — safe, but it does not exercise the
gate-aware retry path. The misread date `2026-04-10` is still never accepted.

## Probe 2 — live identification on the below-gate shape (`v2-probe2-*`)

Batch `betta-20261015-155106-t135kd`, 2 live calls. Only the prepared-image
stage is mocked (`probe2-preflight` / `probe2-prepqa`, provider `mock-router`);
identification is **live**:

| # | Stage | call_id | Verbatim result |
|---|---|---|---|
| 1 | catalogue (full frame) | `7fb0c7d9-b8d3-4eec-910d-c3f587f5b263` | tank `2BT23` @0.94 gate PASS; date `2026-04-10` @**0.88 BELOW_GATE**; `uncertain_reason: "catalogue confidence below 0.90"` |
| 2 | focused label retry | `d6b950b7-4b31-4247-a39d-1221ef395dce` | tank `2BT23` @0.99 / date `2026-10-14` @0.96 / price `35`; receipt `gate_passed {tank_id: true, photo_date: false}`, `disposition: "ACCEPTED"`, reason *“focused label read accepted; catalogue tank agrees, date below gate”* |

Outcome (verbatim): entry `tank_id 2BT23`, `photo_date 2026-10-14`,
`status PENDING`, `notes ["focused label retry accepted"]`,
`label_reads.status RETRY_ACCEPTED`; batch `{status: AWAITING_AUTHORISATION,
stage: PREPARED, published: 0, quarantined: 0, manifest_sha256: null}`. This is
the expected post-refinement outcome, observed **live**: the below-gate
catalogue date cannot veto the confident focused read, and the correct identity
proceeds to the paid-generation gate.

## Replay — recorded v1 reads through current code (`v2-replay-*`)

**No model call**: mocked runners return the exact envelopes recorded by the v1
real calls (`real-run-catalogue-receipt.json` SHA
`0965651c9543e492efd6fdf358de4cf84f709800392a452981296ec957dfd1ca`;
`real-run-label-retry-receipt.json` SHA
`e9825988256242f9b88298c68fc8f7a8f6a283cee153b92b5ee3dcb49f4865a8`), rebinding
only the input hashes to the files this batch used. The batch selection context
is set to the recorded call window (`2026-10-14T23:56:00+00:00`) so the recorded
timestamps remain valid. Prepared-image stage mocked; no invented values.

Verbatim outcome with the recorded reads (tank 0.98 pass / date 0.88 below gate;
crop 2BT23 @0.99 / 14/10/2026 @0.96):

- identify receipt: `uncertain: true`,
  `uncertain_reason: "catalogue confidence below 0.90"`,
  `catalogue_confidence_raw {tank_id: 0.98, photo_date: 0.88}`,
  `catalogue_confidence_gates {tank_id: PASS, photo_date: BELOW_GATE}`.
- retry receipt: `gate_passed {tank_id: true, photo_date: false}`,
  `disposition: ACCEPTED`, `contradiction: null`,
  `label_reads.status: RETRY_ACCEPTED`.
- entry: `tank_id 2BT23`, `photo_date 2026-10-14`, `status PENDING`,
  `prep_status PREPARED`, working image SHA
  `69a1dcc99fd664d6c63fb85afaeffa725c4288a2a94b68e0f996eee4ebf2b269` (distinct
  derivative; raw unchanged).
- batch: `{status: AWAITING_AUTHORISATION, stage: PREPARED, published: 0,
  quarantined: 0, manifest_sha256: null}`.

This is the exact M1 expectation: **the recorded genuine reads now yield
`RETRY_ACCEPTED` (2BT23 / 2026-10-14); the below-gate catalogue date cannot
veto; the misread `2026-04-10` is never accepted.**

## Fixes verified at HEAD during these runs

- **Vision-route `PATH` hardening (bug 1):** `betta_vision_route.inspect_live`
  now builds a hardened child environment (`env=child_env`) before invoking the
  node-based `openclaw` CLI; covered by the committed
  `tests/test_betta_vision_route_bau.py`. (The drivers still set a defensive
  `PATH`, so this run does not itself prove the minimal-`PATH` case.)
- **Label-crop `.part` hygiene (bug 2):** `_label_crop` now passes the FINAL
  crop path to the helper; the live probe2 retry receipt records
  `crop_identity.detection.output_path` = `…/<sha>-label.png` (the final file,
  no `.part`), SHA `b6cbc027…`.

## Notes / caveats

- One archiving fix was applied to the probe2 evidence **without any new model
  call**: after a gate-aware retry the process entry's
  `catalogue_evidence_path` points at the retry receipt, so the driver's first
  copy labelled the retry receipt as “catalogue”. The archived
  `v2-probe2-catalogue-receipt.json` was re-copied from
  `label_reads.full.receipt_path` (the original identify receipt, call
  `7fb0c7d9…`) and `v2-probe2-label-retry-receipt.json` from
  `label_reads.crop.receipt_path`; the summary records this as `archive_fix`.
  The same fix was applied to the replay driver before it ran.
- Fresh-sample variance is now evidenced with two live samples of the same
  photo: below-gate (probe2 → accepted) and above-gate (run 1 → confident
  contradiction → quarantined). Both outcomes are safe; neither accepts the
  misread date.
- Real evaluation remains single-photo; the prepared-image stage in probe2 and
  the replay is mocked (documented above). The automated suite covers the same
  semantics hermetically for every stage.
