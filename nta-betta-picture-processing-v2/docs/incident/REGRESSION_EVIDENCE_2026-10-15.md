# REGRESSION EVIDENCE — P1 2BT23 identity incident (A5, 2026-10-15)

**Agent:** A5 (independent adversarial QA / regression engineering).
**Worktree:** `/Users/davidlo/openclaw-skills-incident-repair` (branch
`codex/betta-identity-incident-20261015`). No commit/push; no production
Shopify mutation; no live-watcher or `~/.openclaw` writes.
**Runner:** `/Users/davidlo/openclaw-skills-v3/nta-betta-picture-processing-v2/.venv/bin/python`
(Python 3.14.7, Pillow 12.3.0).

## Deliverables

| Artifact | Purpose |
|---|---|
| `tests/test_betta_incident_2bt23.py` | The 52-test incident regression suite (categories 1–20). |
| `tests/fixtures/incident_2bt23/README.md` | Fixture provenance, shas, byte-immutability rules. |
| `tests/fixtures/incident_2bt23/near-confusion-5bt43-original.png` | Verbatim archival copy of the archived 5BT43 photo (`6c1d0e92…`). |
| `docs/incident/incident_eval/` | Verbatim real-evaluation evidence (receipts, state, crop) + `summary.md` + the two archived drivers. |
| `docs/incident/REGRESSION_EVIDENCE_2026-10-15.md` | This report. |

## Commands and results

```sh
cd /Users/davidlo/openclaw-skills-incident-repair
V=/Users/davidlo/openclaw-skills-v3/nta-betta-picture-processing-v2/.venv/bin/python

# module (52 tests, including the two skipped-when-absent real-evidence guards)
$V -B -m unittest nta-betta-picture-processing-v2.tests.test_betta_incident_2bt23
# -> Ran 52 tests ... OK

# full suite
cd nta-betta-picture-processing-v2
$V -B -m unittest discover -s tests -t tests
# -> Ran 527 tests ... OK   (was 475 before this suite; +52)

# syntax gate on every file added/edited
$V -B -m py_compile nta-betta-picture-processing-v2/tests/test_betta_incident_2bt23.py
$V -B -m py_compile nta-betta-picture-processing-v2/docs/incident/incident_eval/eval_driver_identification.py
$V -B -m py_compile nta-betta-picture-processing-v2/docs/incident/incident_eval/eval_driver_preparation_probe.py
```

Both the category-1/2/12/16 evidence tests and the full suite pass with the
real-eval evidence present in this worktree. The A2-evidence guards skip only
if `docs/incident/label_recognition_evidence/` is absent.

## Category → test mapping (all 20 required categories)

| # | Requirement | Tests |
|---|---|---|
| 1 | Correct original-image identification | `Category01OriginalImageIdentification.test_1_fixture_is_byte_immutable_and_bound_to_recorded_shas`, `test_1_recorded_real_full_read_identified_tank_2bt23`, `test_1_recorded_real_run_quarantined_instead_of_accepting_the_misread` |
| 2 | Correct cropped-label identification | `Category02CroppedLabelIdentification.test_2_fresh_crop_reproduces_the_recorded_crop_bytes`, `test_2_recorded_real_crop_read_is_confident_and_correct`, `test_2_crop_is_a_deterministic_region_of_the_source` |
| 3 | Wrong high-confidence identification | `Category03WrongHighConfidenceIdentification.test_3_adapter_quarantines_the_wrong_high_confidence_full_read`, `test_3_process_blocks_generation_manifest_and_any_5bt43_mutation` |
| 4 | Wrong photograph date | `Category04WrongPhotographDate.test_4_date_only_disagreement_quarantines_at_the_adapter`, `test_4_process_never_publishes_a_wrong_date`, `test_4_nearby_dates_and_tanks_are_never_equated` |
| 5 | Disagreement / INCOMPLETE handling | `Category05DisagreementAndIncomplete.test_5_not_confident_crop_leaves_the_confident_full_read_in_force`, `test_5_uncertain_full_read_recovers_via_agreeing_crop_read`, `test_5_uncertain_full_read_with_contradicting_crop_stays_quarantined`, `test_5_comparator_matrix_is_pinned` |
| 6 | Requested ≠ detected tank at load | `Category06RequestedDetectedMismatch.test_6_detected_5bt43_requested_2bt23_refused_at_manifest_load`, `test_6_execute_and_resume_both_refuse_before_any_state_exists` |
| 7 | Prevention of wrong-product writes | `Category07WrongProductWritePrevention.test_7_blocked_manifest_never_constructs_a_mutation_path`, `test_7_process_level_wrong_read_cannot_intend_or_perform_a_5bt43_write` |
| 8 | Owner correction with exact source binding | `Category08OwnerCorrection.test_8_valid_correction_allows_the_manifest`, `test_8_correction_record_is_immutable_with_full_audit_fields`, `test_8_mocked_execute_succeeds_for_the_corrected_item` |
| 9 | Correction reuse elsewhere refused | `Category09CorrectionReuseRefusal.test_9_reuse_for_another_image_product_or_tank_is_invalid`, `test_9_manifest_binding_the_record_to_another_item_is_refused` |
| 10 | Duplicate image hashes | `Category10DuplicateHashes.test_10_the_two_uploads_are_byte_identical`, `test_10_processed_registry_dedupes_the_repeat_upload`, `test_10_stable_intake_scan_excludes_the_already_processed_hash`, `test_10_strict_intake_refuses_duplicate_selected_content`, `test_10_identity_block_binds_this_source_sha_exactly_once` |
| 11 | Source-hash attribution refused | `Category11SourceHashAttribution.test_11_identity_source_sha_must_match_the_camera_original`, `test_11_catalogue_receipt_with_wrong_source_lineage_is_refused`, `test_11_label_receipt_with_wrong_source_lineage_is_refused` |
| 12 | Recorded model assertions vs evidence | `Category12RecordedModelEvidence.test_12_recorded_wrong_date_cannot_pass_the_confidence_gate`, `test_12_comparator_never_emits_agree_for_the_recorded_pair`, `test_12_real_run_reached_the_same_class_of_result` |
| 13 | Resume after interrupted mutation | `Category13InterruptedMutationResume.test_13_resume_completes_exactly_once_after_mid_sequence_death`, `test_13_identity_gate_remains_active_during_resume` |
| 14 | Independent Shopify read-back | `Category14ShopifyReadBack.test_14_verify_reports_a_fresh_readback_with_full_evidence` |
| 15 | Autonomous quarantine | `Category15AutonomousQuarantine.test_15_disagreement_is_partial_with_one_terminal_summary`, `test_15_incomplete_identity_is_quarantined_not_published` |
| 16 | Original camera file preservation | `Category16OriginalPreservation.test_16_real_eval_preserved_the_raw_and_used_a_distinct_working_file`, `test_16_hermetic_manifest_binds_the_raw_original_and_a_derived_working_file` |
| 17 | No unauthorised price/cost/vendor changes | `Category17ProtectedFields.test_17_protected_mechanics_cover_price_cost_vendor`, `test_17_merch_scope_only_correction_cannot_authorise_betta_operations`, `test_17_external_price_change_blocks_even_a_corrected_item` |
| 18 | No duplicate Shopify mutations | `Category18Idempotency.test_18_process_restart_never_repeats_a_mutation`, `test_18_exactly_one_mutation_per_identity_source` |
| 19 | Repeat correction immutability | `Category19RepeatCorrections.test_19_identical_repeat_write_is_refused_and_file_is_unchanged`, `test_19_repeated_validation_is_stable_and_equal`, `test_19_tampered_repeat_is_refused` |
| 20 | Concurrent similar-number batches | `Category20ConcurrentBatches.test_20_shared_registry_keeps_both_identities_distinct_and_bound`, `test_20_nearby_numbers_are_distinct_under_normalisation_and_comparison` |

Nearby-confusion unit cases are folded into categories 4, 5 and 20 as required:
`2BT23`/`5BT43` and `2026-10-14`/`2026-10-09` are never equated by
normalisation or by the comparator, and never yield `AGREE`.

## Real-evaluation evidence summary

Full write-up: `docs/incident/incident_eval/summary.md`. The centrepiece used
**5 real vision calls** (budget ≤ 6), all attested `openai / gpt-5.6-sol`:

1. Real full-frame catalogue read of the incident photo → tank `2BT23` (0.98),
   date `2026-04-10` (0.88, **below** the 0.90 gate), model flagged the
   ambiguity itself.
2. Real focused label-crop read → tank `2BT23` (0.99), date `2026-10-14` (0.95),
   price `$35`.
   → The recorded contradiction `catalogue date 2026-04-10 vs label date
   2026-10-14` produced `RETRY_CONFLICT` and a **QUARANTINE**; the run ended
   `PARTIAL`, `published: 0`, no manifest, no authority, no generation, no
   Shopify call.
3. Real preflight (preparation probe) → tank `2BT23` (0.99), date `2026-10-14`
   (0.93), cross-check `AGREES`.
4-5. Real prep-QA `FULL` and `L1` → both `FAIL` (exposure/clipping/cast), so the
   pipeline fell back to the untouched raw (`FALLBACK_RAW`) instead of passing a
   degraded working image to generation; the run stopped at
   `AWAITING_AUTHORISATION` (no Grok spend).

Recorded key values live verbatim in
`docs/incident/incident_eval/real-run-*.json` / `probe-prep-*.json`; the tests
assert only values/structure that were genuinely recorded, plus raw-sha
immutability. A mocked successful read is never presented as OCR evidence
(mocked receipts are labelled `probe-prep-*` and `provider: mock-router`).

## Coverage report

- 20/20 required categories implemented, each with at least one test; 52 tests
  total across 20 classes.
- Real bytes: every hermetic scenario runs on the genuine incident PNG
  (`6e4a4f…`) and the verbatim archived 5BT43 PNG (`6c1d0e92…`); fixture shas
  are re-verified inside the suite.
- Layers covered: pinned comparator (`label_identity.compare_reads`), strict BAU
  adapters (`identify`/`retry_identify`/`prepare`), process orchestrator
  (`betta_process`), uploader manifests (`betta_shopify_batch.ManifestBundle`),
  uploader execution/resume/verify with a mocked bridge, correction records
  (`betta_corrections`), watcher registry/scan (`betta_watch`), batch lifecycle
  (`betta_batches`), budget ledger.
- No network, no Shopify, no Grok in the automated suite (vision is mocked and
  keyed by input hash so every mocked reading binds the file it claims to).

## Bugs / defects found (NOT fixed — reported for the orchestrator)

1. **`betta_vision_route.inspect_live` does not harden `PATH` for route
   resolution** (`scripts/betta_vision_route.py`, line ~22). `openclaw` is a
   node script; `vision_review.run_review` hardens the child `PATH` for the
   actual inference call but calls `resolve_route()` *before* setting it. In a
   minimal-`PATH` execution context the inspect subprocess fails
   (`env: node: No such file or directory`), prod-module identification fails
   closed with `"vision model catalogue unavailable"`, and a legitimate batch is
   quarantined (reproduced once during the real evaluation; the same run
   succeeded once `PATH` included `/opt/homebrew/bin`). Suggested fix: set the
   same preferred `PATH` before `inspect_live` (and honour
   `BETTA_OPENCLAW`/`BETTA_NODE` overrides). Severity: operationally medium,
   safety-neutral (fail-closed), but it wastes the identification stage.
2. **Label-crop detection receipt records a stale `.part` path**
   (`scripts/betta_bau_adapters.py::_label_crop`). The helper is invoked with
   `output_path=<final>.part`; its returned detection record stores that `.part`
   path, then the adapter `os.replace`s the file to the final name. The stored
   `crop_detection.output_path` therefore points at a path that no longer
   exists, while the authoritative `crop_identity.sha256` /
   `output_sha256` are correct and bound. Purely an evidence-hygiene wart
   (forensic readers may chase a dead path). Suggested fix: pass the final path
   to the helper, or rewrite `detection["output_path"]` before persisting.
   Severity: low.
3. **Prep image-tone calibration vs prep-QA strictness (observation).** On the
   incident photo the real prep-QA rejected both deterministic levels (`FULL`
   and `L1`) for exposure/contrast increase with clipped highlights and a pink
   cast; the pipeline correctly fell back to the raw. This is safe but means the
   prepared-image value is lost for this photo class; the tone curve in
   `betta_prepare` and/or the prep-QA threshold may deserve owner review.
   Severity: informational (no acceptance loosening detected — the opposite).

## Residual gaps / risks

- The real evaluation is single-sample (n=1 photo, 5 calls) by design; model
  variance (e.g. the date confidence moving above 0.90 on some run) would change
  the read's confident flag. The suite therefore asserts the *gate/comparator*
  outcome and the recorded values, not future model behaviour.
- The strict pipeline's manifest identity block sets
  `detected_tank == requested_tank == accepted_tank`; there is no pipeline-level
  field for a separately owner-requested tank (the uploader manifest contract
  covers that case). If a future dispatcher is expected to carry an owner
  request, that wiring does not exist yet — flagged, not tested as a feature
  (no invented semantics).
- Real-eval receipts embed scratch paths
  (`/private/var/folders/.../incident-eval/...`); tests treat them as recorded
  strings and only re-hash when the file is still present.
- The archived drivers in `docs/incident/incident_eval/` are exact copies of
  what ran; re-running them makes new live calls and overwrites the scratch
  evidence (not the archived copies).
