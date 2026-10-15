# INDEPENDENT SECURITY & RELEASE REVIEW — P1 identity incident repair (A6)

> *Post-review status (updated 2026-10-15, later than the original capture): four
> findings were fixed by the owners and are re-verified green in §10; the
> original findings and CI quotes below are kept verbatim as the historical
> record. H1 (out-of-repo bridge copy) remains owner-gated.*

**Reviewer:** Agent 6 — independent adversarial security review (read-only over all other files).
**Worktree:** `/Users/davidlo/openclaw-skills-incident-repair` — branch `codex/betta-identity-incident-20261015`.
**Reviewed head SHA:** `4f6462ee92ef47e8fcf6b73b1b2b2b662b49e973` (PR #35 head at review time; this review's own commit is later and was NOT present when the CI/evidence below was captured).
**Deliverables (owned files):** this report and
`nta-betta-picture-processing-v2/tests/test_betta_firewall_adversarial.py` (51 tests, all passing).
**Constraints honoured:** no git commits/pushes; no writes outside the two owned files; **no production Shopify mutation** (two read-only `resolve` calls were made, explicitly allowed); `~/.openclaw` and the live watcher (`com.nanotanksaustralia.betta-watch`) were read-only inspected and untouched; no bridge was executed.

## 0. Verdict board (do not conflate these)

| Status | Value |
|---|---|
| CODE COMPLETE (in-repo repair) | **Yes** — dual label reads + comparator, uploader identity firewall + owner-correction records, bridge-integrity detection, orchestrator quarantine rules, 52-test incident suite, 51-test adversarial suite |
| TESTS PASS | **Yes, locally** — adversarial: `Ran 51 tests … OK`; full suite: `Ran 594 tests … OK` (543 pre-existing + 51 adversarial) |
| CI STATUS | PR **#35** head `4f6462e`: **all 4 checks green** (per-SHA API, see §7). PR **#34** head `2ae58b1`: **Betta workflow CI red** (`ModuleNotFoundError: No module named 'PIL'`); the fix is only on the #35 branch |
| MERGED | **No** — both PRs OPEN, `mergeable: MERGEABLE`, `mergeStateStatus: UNSTABLE` |
| DEPLOYED | **No** — every bridge/`~/.openclaw` hardening item is owner-gated and untouched |
| PRODUCTION VERIFIED | **Read-only verified** — independent fresh resolves at 2026-10-15T02:59–03:00Z match the repair receipt and the audit (§6). No deployment verification is claimed |

**Recommendation:** **GO for merging PR #35 into its base branch** (`codex/betta-autonomy-reconcile-20261014`), subject to a final exact-SHA CI re-run after this review commit lands. **NO-GO for deploying the owner-gated items and NO-GO for merging #34 → `main` until #34's CI is re-run green after the stack update** (§7). No attacker-usable bypass of the uploader identity gate was found; no critical findings.

---

## 1. Method

I did not trust the summaries. I read the final code on the branch (not the reports about it), then attacked it:

- Read: `INCIDENT_BRIEF.md`, `P1_FORENSICS_2026-10-15.md`, `SHOPIFY_AUDIT_2026-10-15.md`, `MUTATION_FIREWALL_DESIGN_2026-10-15.md`, `REGRESSION_EVIDENCE_2026-10-15.md`, `label_recognition_evidence/summary.md`, `incident_eval/summary.md`, and every archived receipt used as evidence.
- Read the diff `git diff 2ae58b1..HEAD -- nta-betta-picture-processing-v2` plus the full current `betta_shopify_batch.py` (`_validate_identity`, `_load_evidence`, `_build_context`, `StateStore`, write path), `betta_corrections.py`, `label_identity.compare_reads`, `betta_bau_adapters.py` dual-read/retry logic, `betta_process.py` quarantine flow, `betta_policy.authorise_manifest`, `betta_bindings` execute runner, `betta_bridge_integrity.py`.
- Wrote `tests/test_betta_firewall_adversarial.py`: 51 hermetic attacks. Genuine incident bytes
  (`incident-photo.png` `6e4a4f…9ca9`, `near-confusion-5bt43-original.png` `6c1d0e92…`) are used as the real source hashes; mocked vision is keyed by input hash so every mock binds the bytes it claims.
- Ran the suite and the full suite exactly as CI does.
- Independently verified the on-disk bridge pin and the live Shopify state (read-only).

Run commands (reproducible):

```sh
V=/Users/davidlo/openclaw-skills-v3/nta-betta-picture-processing-v2/.venv/bin/python
cd /Users/davidlo/openclaw-skills-incident-repair
$V -B -m unittest discover -s nta-betta-picture-processing-v2/tests -p 'test_betta_firewall_adversarial.py'   # Ran 51 tests … OK
$V -B -m unittest discover -s nta-betta-picture-processing-v2/tests -p 'test_*.py'                            # Ran 594 tests … OK
$V -B -m py_compile nta-betta-picture-processing-v2/scripts/*.py                                             # OK
```

## 2. THE CENTRAL ATTACK — cause an update of 5BT43 while the owner requested 2BT23

All variants were implemented as tests; **all attack variants that depend on an honest identity record were refused**. Exact refusal reasons are the code's own messages.

| # | Attack variant | Test | Result |
|---|---|---|---|
| a | Manifest targets 5BT43, `detected_tank=2BT23`, `requested=accepted=5BT43`, no correction (Fred's shape) | `test_central_attack_read_2bt23_target_5bt43_without_correction_refused` | **SURVIVED** — `ManifestError: 5BT43: vision-detected tank (2BT23) differs from the requested tank (5BT43) without a correction record` |
| a2 | `requested_tank=2BT23` while `accepted_tank=5BT43` | `test_central_attack_honest_request_2bt23_cannot_target_5bt43` | **SURVIVED** — `requested_tank must equal the manifest tank when no correction is present` |
| a3 | `accepted_tank` silently differs from the manifest tank | `test_central_attack_accepted_tank_must_equal_item_tank` | **SURVIVED** — `identity accepted_tank must equal the manifest tank` |
| b1 | Correction recorded for a **different source** (near-confusion 5BT43 photo) presented for the incident photo | `test_correction_with_wrong_source_refused` | **SURVIVED** — `source_sha256_mismatch` |
| b2 | Correction recorded for a **different product** | `test_correction_with_wrong_product_refused` | **SURVIVED** — `product_id_mismatch` |
| b3 | Correction scope does not cover the Betta operation set (merch fields / missing `media`) | `test_merch_scope_cannot_authorise_betta_operation`, `test_partial_scope_refused` | **SURVIVED** — `operation_scope_mismatch` |
| b4 | The designed owner override — honest `detected=5BT43`, owner corrected to 2BT23 | `test_central_attack_valid_correction_is_the_designed_override` | **SURVIVED as designed** — refused without a record; loads only with the exact record (source+product+target+scope bound) |
| c1 | Tampered correction bytes (`corrected_tank` flipped, self-hash stale) | `test_correction_tampered_bytes_refused` | **SURVIVED** — `self_hash_mismatch` |
| c2 | Copied valid record bytes into a second batch paired with a different source | `test_correction_copied_into_another_batch_refused` | **SURVIVED** — `source_sha256_mismatch` |
| c3 | Valid record moved away from the bound corrections path | `test_correction_must_reside_at_the_bound_path` | **SURVIVED** — `record_unavailable` |
| c4 | Correction path does not exist | `test_correction_nonexistent_path_refused` | **SURVIVED** — `record_unavailable` |
| c5 | Uppercase correction sha | `test_correction_hash_must_be_lowercase` | **SURVIVED** — `lowercase SHA-256` |
| d1 | Identity block extra key / missing key | `test_identity_block_key_set_is_exact` | **SURVIVED** — `identity block must contain exactly …` |
| d2 | `identity.source_sha256` ≠ hashed original bytes | `test_identity_source_hash_must_bind_the_real_original_bytes` | **SURVIVED** — `identity source hash differs from the camera original` (the uploader re-hashes the file; the claim cannot be forged) |
| d3 | Non-lowercase source sha / non-canonical tank value | `test_identity_source_sha_must_be_lowercase`, `test_identity_tank_values_must_be_canonical` | **SURVIVED** — refused |
| f1 | **Every CLI command** (`preflight`, `dry-run`, `execute`, `resume`, `status`, `verify`) on a broken identity | `test_every_cli_command_refuses_broken_identity_before_any_state` | **SURVIVED** — exit 2 before a state/report directory or a bridge exists |
| f2 | Standing-policy automatic authority (`betta_policy.authorise_manifest`) | `test_policy_authorise_manifest_applies_the_identity_gate` | **SURVIVED** — happy path issues `automatic-standing-bau` receipt; the same call with a broken identity raises `PolicyError: uploader rejected manifest: …` and writes **no** authority receipt. The policy loads the manifest *through* the uploader (`ManifestBundle`), so the gate applies there too |
| f3 | Owner-recorded **legacy digest grant** + `execute --live` | `test_legacy_digest_grant_cannot_bypass_the_identity_gate` | **SURVIVED** — the grant does not matter; the CLI re-loads the manifest and refuses before state |
| f4 | Manifest swapped under an existing state | `test_state_store_refuses_a_manifest_swap` | **SURVIVED** — `state belongs to a different manifest digest` |
| e | **Upstream-producer lie** (`detected=requested=accepted=5BT43`, real incident-photo sha, self-consistent) | `test_boundary_upstream_producer_lie_passes_the_gate` | **LOADS — documented trust boundary, not a bypass.** See §5 |

Structural invariant verified from the code + tests: **`accepted_tank == requested_tank == manifest tank` is unconditional**, and a correction record can never name a corrected target different from the requested/accepted tank (`betta_corrections.validate_correction` enforces `requested == corrected == accepted`). A mutation can therefore only target a tank that the manifest *declares as the requested tank*; the honest-mismatch case fails closed.

## 3. Other adversarial groups

### 3.1 Cross-product contamination (two concurrent sandboxes, one scratch registry)
`test_concurrent_shared_registry_keeps_identities_uncrossed` — incident photo → 2BT23 and the archived 5BT43 photo → 5BT43 run **in two threads against one shared SQLite registry** with hash-keyed mocked vision. **SURVIVED**: both runs `COMPLETE`; every text artifact of each batch is free of the other batch's source sha and tank string; the registry keeps both identities distinct; manifests carry the correct `identity` blocks. `test_registry_cannot_rebind_a_processed_identity` (duplicate `INSERT OR IGNORE` cannot rebind a sha to another batch), `test_cross_linked_manifest_identity_refused` (a manifest item paired with the other photo's sha is refused) also pass.

### 3.2 False confidence / below-gate veto matrix
- Confident **wrong crop** vs confident **correct full** read → **quarantine**, no generation/manifest/authority (`test_confident_crop_contradicting_confident_full_read_quarantines`).
- Confident crop vs **below-gate** full tank, date, or both → **accepted from the crop**; below-gate values never veto (`test_below_gate_full_tank_cannot_veto_confident_crop`, `test_below_gate_date_cannot_veto_confident_crop`, `test_both_below_gate_cannot_veto_confident_crop`). The gated-passing fields still veto: gated tank conflict and gated date conflict both yield `RETRY_CONFLICT` (`test_gated_tank_contradiction_still_refuses`, `test_gated_date_contradiction_still_refuses`).
- No path was found where a below-gate value vetoes a confident crop read; the refinement is complete for the documented rules.

### 3.3 Source binding
- Retry with **drifted source bytes** → `label retry source changed` (`test_retry_refuses_drifted_source_bytes`).
- **Changed crop bytes** under an existing corroboration receipt → `label crop changed since its corroboration receipt` (`test_corroboration_receipt_refuses_changed_crop_bytes`).
- Corroboration receipt self-consistency (source sha, crop sha, both receipt hashes, crop detection points at the live final path, no `.part`) → `test_corroboration_receipt_binds_source_crop_and_full_receipt`.
- Uploader `resume` after **drifted evidence sidecar** → exit 2 `hash mismatch`, state bytes and mock-gateway write count unchanged; drifted hero asset → same class of refusal (`test_uploader_resume_refuses_drifted_evidence_and_makes_no_write`, `test_uploader_refuses_drifted_asset_bytes`).

### 3.4 Stale snapshots / duplicates / protected fields
- Live **price drift** after approval → both items BLOCKED **before any write** (`gateway.writes == []`) (`test_protected_field_drift_blocks_before_any_write`).
- Full mocked execute (2 items): the write stream is exactly the 6 allowed operations per item; a recursive scan of every variable finds **no** `price`/`cost`/`vendor` key; `betta_batch_update_details` sends exactly `{id,title,metafields}`; a second pass via `resume` performs **no** additional write (inventory CAS stays at exactly one per item) (`test_mocked_write_path_never_touches_price_cost_vendor`).

### 3.5 Misreporting cross-check (documents vs receipts)
`test_incident_receipts_match_the_audit_document` — the archived receipts match every audit claim (plan shas `b691ee3b…806ece5` / `5ed84ede…1ed64c`, product/variant ids, before/after vendor·price·cost), and the repair receipt is the exact inverse of the unauthorised change. `test_two_incident_uploads_remain_byte_identical` re-verifies the fixture shas.

### 3.6 Owner-override scoping
Reuse on another source / product / tank refused; Betta scope cannot authorise merch fields and vice versa; a record missing one of the four fields cannot authorise the full uploader operation set; repeat recording is refused and the original record bytes are unchanged (`test_reuse_for_another_*`, `test_betta_scope_cannot_authorise_merch_fields`, `test_partial_scope_refused`, `test_repeat_recording_refused_and_original_bytes_stable`).

## 4. Findings by severity

### CRITICAL
None. No attack that depends on an honest identity record succeeded; no wrong-product mutation path was found in the repaired pipeline.

### HIGH
**H1 — The incident's original vector is still live on disk (out-of-repo, owner-gated).**
Fred's writable bridge copy at
`~/.openclaw/workspace/fred/tmp/betta-merch-20261014/scripts/shopify-session-bridge.mjs`
still exists with the incident sha `2251f709…cae9d6` (mtime 2026-10-15 09:22:52) and still contains the in-file write allowlist (`BETTA_MERCH_TARGETS` ×3 occurrences; the canonical bridge has 0). Repo-side `betta_bridge_integrity.check_bridge` correctly returns `bridge_not_canonical` (exit 2), but nothing wires that check into the Fred write path yet — all wiring/removal is owner-gated (design §4/§5). This is the only finding that could reproduce the incident today, and it is outside this repository's merge scope.

### MEDIUM
**M1 — Evidence/documentation drift: the archived real run is not reproducible on the final code.** The archived `real-run-*` receipts (batch `betta-20261015-105638-vccnto`, 10:56 AEDT) were produced ~2 h **before** commit `cba92e2` (12:58 AEDT) added the gate-aware retry refinement; the receipts lack `catalogue_confidence_gates`/`gate_passed`/`disposition` and still record the stale `.part` crop path. With the **current** code and the **recorded** values (tank 0.98 pass/date 0.88 below gate, crop 2BT23/2026-10-14 0.95), the pipeline returns **`RETRY_ACCEPTED`** — the below-gate date is discarded and the crop's correct date is used — whereas `REGRESSION_EVIDENCE`/`incident_eval/summary.md` describe `RETRY_CONFLICT` + QUARANTINE. Pinned (asserting the observed current behaviour) in
`test_recorded_real_run_shape_now_accepts_via_below_gate_refinement`. Safety impact: none for this photo (the accepted identity is the correct 2BT23/2026-10-14; the misread date is still never accepted); impact is on the evidential claim that the archival run validates the final revision. Also: `REGRESSION_EVIDENCE_2026-10-15.md` lists two "NOT fixed" bugs (vision-route PATH, `.part` crop path) that **are fixed at HEAD** (PATH hardening is in `cba92e2` with a passing test; the crop helper is now invoked with the final path — verified by `test_corroboration_receipt_binds_source_crop_and_full_receipt`).

**M2 — Correction-record authenticity is a deployment prerequisite, not an enforced property.** `betta_corrections.record` authenticates nothing: any actor able to write into the corrections directory (including a manifest-declared `corrections_dir`, which the uploader honours verbatim) can mint a self-hashed record and pair it with an honest `detected_tank` claim. Documented in `test_boundary_self_minted_correction_passes_the_gate`. This is the same trust boundary as manifest authorship (an actor who can write the manifest can already write `detected_tank`), so it is not a new bypass — but the operator field and evidence reference are advisory only, and the default directory `<repo>/references/corrections/` does not exist yet (it will be created inside the working tree on first use). Deployment requirement: corrections directory owner-writable only, outside agent-writable trees; state this in the release notes.

**M3 — Stack CI sequencing (release process).** PR #34's exact-SHA CI is red (missing Pillow) and the fix lives only on PR #35. See §7. Merge-blocking for the final `main` merge, not a code defect.

### LOW
**L1 — Confidence audit fields mislabel the production key names (evidence quality, safety-neutral).**
`catalogue_confidence_raw`/`catalogue_confidence_gates` (added "for audit") read only `<field>_confidence`/`confidence.<field>`. The production contract emits `tank_confidence`/`date_confidence` (the archived real receipts use them), so a below-gate `0.88` is recorded as `"MISSING"`/`None` instead of `"BELOW_GATE"`/`0.88`. The gate *decision* is unaffected. Documented in `test_documentation_confidence_audit_fields_miss_real_key_names` (both key forms asserted). Suggested fix: extend `_raw_confidence` to also read `tank_confidence`/`date_confidence`.

**L2 — `build_manifest` defence-in-depth guard covers `DISAGREE` but not `RETRY_CONFLICT`.** The belt-and-braces check (`betta_bau_adapters.py` ~L1493) refuses `label_reads.status == "DISAGREE"` (identify path) but not the retry-path conflict status. The process quarantines both before a manifest is built, so this is currently unreachable; a future caller bug marking a conflicted entry `VERIFIED` would pass this specific guard (the deterministic-title check still fails such an entry). Documented in `test_documentation_manifest_guard_covers_disagree_but_not_retry_conflict`.

**L3 — Audit-trail consistency gaps in the correction binding.** The record's `variant_id` and `original_model_tank` are not cross-checked by the uploader (it binds source, product, corrected target, scope). Neither can redirect a write (single-variant product is enforced by the protected snapshot; `detected_tank` authorises nothing), but an inconsistent record/manifest pair is not flagged. Documented in `test_documentation_detected_tank_claim_is_not_authenticated`.

**L4 — Cosmetic code smell:** `StrictBAUAdapters._label_crop` tries `helper(source_path=source, output_path=crop)` first, which can never succeed (the helper's parameter is `image_path`); it always falls through to the positional call. Harmless, but the dead branch should be removed or corrected.

## 5. Trust-boundary analysis (what the gate can and cannot do)

The uploader identity gate is a **consistency gate over producer-authored documents**, enforced at manifest load on the single path shared by `preflight`/`dry-run`/`execute`/`resume`/`verify`/`status` and by `betta_policy.authorise_manifest`; it runs before any bridge, state store or write capability is constructed. It proves, deterministically:

1. the accepted target equals the manifest tank, and equals the requested tank unless an exact, self-hashed, non-reusable owner record covers this source + product + field set;
2. `identity.source_sha256` equals the **re-hashed bytes** of the camera original, which are the same bytes the label evidence, new-fish authority and image-QA receipts bind.

It **cannot** know (and does not claim to know): that the manifest's `detected_tank` is the true vision output; that the declared "requested tank" is what the owner actually requested; that the author of the manifest/records is the owner. A fully self-consistent lie loads (`test_boundary_upstream_producer_lie_passes_the_gate`).

What stops the incident-class attack upstream (verified from code + real evidence):

- The pipeline (A4 `build_manifest`) always writes `detected = requested = accepted = tank`, and `tank` comes from the dual-read decision: the **real** reads of this exact photo were `2BT23` in every recorded call (A2: full 0.93 + crop 0.99; A5: full 0.98 + crop 0.99 + preflight 0.99), and any contradiction quarantines without producing a manifest. Producing a 5BT43 manifest for this photo therefore requires fabricating the manifest **and** all hash-bound sidecars — i.e. write access at a layer where any guard of this shape is bypassable.
- The Fred-path failure mode (no vision read at all, hallucinated identity, self-widened write scope) cannot reach this uploader: the uploader never accepted conversational identity claims, and the gate now refuses any internally inconsistent manifest.

Residual trust to manage at deployment: manifest authorship (orchestrator-only), the corrections directory's permissions (M2), the vision model's confident output (unchanged risk, mitigated by dual reads + quarantine, never by majority vote), and the Fred bridge (H1).

## 6. Production state verification (read-only, independent)

Ran on 2026-10-15 (read-only `shopify_live.mjs resolve`, no mutations; shop `Nano Tanks Australia`):

| Fetch | Product | Values seen | Cross-check |
|---|---|---|---|
| 5BT43 `2859f3cb-3f39-48d3-a2cf-a6acbd30a066` @02:59:11.796Z | `gid://shopify/Product/7239072481489`, variant `…41532067512529` | vendor `NTA Imports`, price `25.00`, cost `1.0`, inv 1, arrival `2026-10-09`, policy DENY, 2 READY media | matches SHOPIFY_AUDIT and the unauthorised receipt's `before` |
| 2BT23 `63186b3d-25e6-46f3-8cd0-3a7794bc5ef4` @03:00:44.308Z | `gid://shopify/Product/7255867588817`, variant `…41571765453009` | vendor `Renial`, price `35.00`, cost `15.0`, inv 0, arrival `2026-06-30`, policy DENY, 2 READY media | matches SHOPIFY_AUDIT and the repair receipt's `after` |

The repair stands; the unauthorised change is fully reverted. (Arrival date/inventory posture for 2BT23 remain the owner's open decisions, already flagged by the audit.)

Bridge pin independently re-checked against live files: canonical bridge `d1fb2264…c3a5ba2` → `verified`; Fred copy `2251f709…cae9d6` → `bridge_not_canonical` (H1).

## 7. PR #34 / PR #35 release posture

Exact current results (captured for this report):

**PR #35** (`P1: FredAPP 2BT23→5BT43 identity incident repair…`, base `codex/betta-autonomy-reconcile-20261014`, OPEN, `MERGEABLE`, `UNSTABLE`):
- `gh pr view 35 --json statusCheckRollup` returned four check runs: `test` **FAILURE** (runs `38669052997`, `38668943495`, 02:04–02:05Z) and `fulfilment` **SUCCESS**. Those runs are for the **previous** head `24f23a5`; the aggregate output did not reflect the current head.
- Exact-SHA check-runs for the current head `4f6462ee92ef47e8fcf6b73b1b2b2b662b49e973`: **4/4 SUCCESS** (Betta `test` runs `38672080639` @02:39:54Z and `38672076638` @02:40:03Z; `fulfilment` `38672080626`/`38672076709`). Green log: `Ran 543 tests in 69.671s` / `OK (skipped=1)`.
- The earlier failure was one test, `test_2_fresh_crop_reproduces_the_recorded_crop_bytes`: `AssertionError: 'daaaa69dfadd8cbe5a7e249379642c5dc655352cec36e1e760cdc792d9ee0be7' != 'b6cbc02721b2071d01fe7e16f48cea2b043842bec7478d45ac8b5f80f12107f1'` — PNG byte determinism across environments, fixed by `4f6462e` (pixel-equality comparison).

**PR #34** (`Betta autonomy: reconciliation + local preparation + calibrated QA`, base `main`, OPEN, `MERGEABLE`, `UNSTABLE`):
- Exact-SHA `2ae58b1dfb67e89c5082983f05502b63f1377219`: `test` **FAILURE** ×2 (runs `38641363105`, `38641357796`, 2026-10-14 21:35Z); `fulfilment` SUCCESS ×2.
- Failure cause: `ModuleNotFoundError: No module named 'PIL'` in six test modules; `Ran 283 tests in 8.336s` / `FAILED (errors=6)`. The fix (`python -m pip install pillow`, `.github/workflows/betta-ci.yml` +2 lines) exists **only on the #35 branch** (commit `24f23a5`).

**Owner-gated / deployment items (none deployed; all explicitly flagged by A3/A4):**
1. Wire `betta_bridge_integrity.check_bridge` into every bridge-launching write path and an owner-visible health check; re-pin process for canonical bridge changes.
2. Canonical bridge scope-config redesign (allowlists out of agent-writable `.mjs`; owner-pinned hash; writability refusal).
3. Correction-record enforcement in the Fred conversational path (no record, no write; agent may never select the product; `detected_tank` from a vision read only) — this is a `~/.openclaw`/FredAPP instruction-and-permission change.
4. Quarantine/removal of the `fred/tmp` bridge copy (H1).
5. Permissions/placement of this repo's corrections directory (M2) and removal of the dead `_label_crop` branch (L4) can ride along with any follow-up commit.

**Remaining release blockers:** (a) after the master pushes this review commit, CI must be re-run on the new exact SHA and be green (my quotes are for `4f6462e`, not for the post-review commit); (b) merge #35 into the `#34` branch, then **re-run #34's CI** on its new head — it should go green (it will carry the Pillow install and the fixed crop test); only then may #34 merge to `main`. No code blocker remains in-repo.

## 8. What I did NOT test

- **No live Shopify writes** of any kind; only the two read-only resolves in §6. No `--live` uploader run, no bridge execution.
- **No `~/.openclaw` mutation, no Fred-path invocation**, no live-watcher interaction (watcher inspected read-only in `launchctl list`: `com.nanotanksaustralia.betta-watch`, last exit 0, not running).
- **No new live vision/model calls** — dual-read behaviour is tested hermetically; the real-read evidence was read, not regenerated (so I cannot comment on model variance beyond the documented single-sample caveats).
- The canonical bridge's runtime enforcement (outside this repo) was not executed; I only pinned/hashed files read-only.
- The `betta_finish_heroes`/legacy paths were exercised only by the existing suite, not individually adversarially.
- No cross-platform matrix beyond: macOS/venv locally, and the committed SHA's ubuntu CI result (quoted, not reproduced).
- PR #34's prior commits were assessed only via its exact-head CI result; no deep review of its earlier feature work (out of scope for this incident).
- The owner-gated deployment items were not validated in any environment.

## 9. Final recommendation

- **GO — merge PR #35 into its base branch** once CI on the post-review exact SHA is green. The in-repo repair is code-complete, hermetic tests pass (51 adversarial + 594 full), the central attack and its variants are refused with exact-binding error paths, protected-field/idempotency guarantees hold, and no critical or high *code* vulnerability was found.
- **NO-GO — deployment.** All bridge/`~/.openclaw` hardening remains owner-gated; the incident's original vector (Fred's writable bridge copy) is still on disk (H1), and the corrections directory must be made owner-private before the override path is used in production (M2).
- **NO-GO — merging #34 → `main`** until #34's CI is re-run green after the stack update (M3).
- **Evidence hygiene before the stack closes (recommended, not blocking):** refresh one real dual-read run on the final revision (or clearly mark the existing archival run as pre-refinement), and fix the confidence audit fields (L1).

---

## 10. Post-review fix verification (2026-10-15) — ADDENDUM

The owners applied the review's fixable findings (uncommitted working tree at the
time of this verification; the master commits). I re-read the code changes,
updated my adversarial suite to pin the fixed behaviour, and re-ran everything.
**No new issues were found in the fix delta.**

### 10.1 Findings fixed and verified

| Finding | Change applied | Verified by |
|---|---|---|
| **L1** confidence audit fields mislabelled the production key names | A4 (`betta_bau_adapters.py`): a single `_confidence_value` lookup now feeds both the gates and the audit fields, reading the same `confidence.<field>`/`<field>_confidence`/flat `tank_confidence`·`date_confidence` chain | `test_confidence_audit_fields_use_real_key_names` (green pin): flat production keys record `tank_id 0.98 / PASS` and `photo_date 0.88 / BELOW_GATE`; the alternate mapping form records identical evidence. A5's v2 replay receipt independently records `catalogue_confidence_raw {tank_id: 0.98, photo_date: 0.88}` + `gates {tank_id: PASS, photo_date: BELOW_GATE}` |
| **L2** `build_manifest` guard covered `DISAGREE` but not `RETRY_CONFLICT` | A4: refusal set is now `{"DISAGREE", "RETRY_CONFLICT"}`; message `refused label contradiction (<status>) must never reach a manifest` | `test_manifest_guard_refuses_disagree_and_retry_conflict` (renamed green pin): **both** statuses refused before any manifest is written; a normal agreeing entry still builds |
| **L3** correction `variant_id` not bound | A3 (`betta_corrections.py` + uploader): `validate_correction(..., variant_id=…)` refuses mismatches (`variant_id_mismatch`), and `ManifestBundle._validate_identity` now passes `item.variant_id` | `test_correction_variant_must_match_when_bound`: direct validation refusal **and** uploader-level `ManifestError … variant_id_mismatch` |
| **L3b / A3 hardening** no-op corrections (`original_model_tank == corrected_tank`) accepted | A3: `record()` raises, `_validate_record_shape` returns `no_op_correction` | `test_no_op_correction_refused_at_recording_and_validation`: refused at creation and a hand-built self-hashed no-op is invalid with reason `no_op_correction` |
| **L4** dead `helper(source_path=…)` invocation | A4: removed; the helper is called once with the final path | Covered by the existing `test_corroboration_receipt_binds_source_crop_and_full_receipt` (recorded `output_path` = live final crop, no `.part`) |

Fixture corrections required by the new no-op rule: my `OwnerOverrideScoping`
helpers now record `original_model_tank="1BT99"` for the two 5BT43-targeted
scope tests; all other correction fixtures already used distinct
original/corrected tanks. Assertions are unchanged.

The residual audit-trail note from L3 stays: the manifest's `detected_tank`
claim is still not compared with the record's `original_model_tank` (neither
value authorises anything) — pinned by
`test_documentation_detected_tank_claim_is_not_authenticated`.

### 10.2 M1 resolution (evidence drift)

A5 produced a post-refinement v2 archive at
`docs/incident/incident_eval_v2/` (**v1 untouched**), which resolves the drift
exactly as recommended:

- **Deterministic replay** of the recorded v1 reads through the current code →
  `RETRY_ACCEPTED` → `2BT23 / 2026-10-14` → `PREPARED` →
  `AWAITING_AUTHORISATION` (below-gate catalogue date cannot veto the confident
  focused read; the misread `2026-04-10` is never accepted).
- **Fresh live sample** of the same photo (model variance: date 0.93, both
  gates pass) → confident contradiction → `QUARANTINED` (PARTIAL, no manifest),
  i.e. the confident-confident rule still fails closed.
- **Live below-gate probe** (`0.88 BELOW_GATE`, tank agrees) → `RETRY_ACCEPTED`
  → `2BT23 / 2026-10-14`, receipt `gate_passed {tank_id: true, photo_date: false}`,
  `disposition: ACCEPTED`.

My hermetic pin
`test_recorded_real_run_shape_now_accepts_via_below_gate_refinement` remains
green and now agrees with the archived v2 evidence.

### 10.3 M2 / H1 status

- **M2** (correction authenticity) is now documented as a deployment
  prerequisite in `MUTATION_FIREWALL_DESIGN §4.5`: owner-only corrections
  directory, do not trust a manifest-declared `corrections_dir` in production,
  owner-authenticated record channel — all owner-gated/unimplemented by design.
  No code claim of enforcement was added.
- **H1** (Fred's writable bridge copy `2251f709…`, still on disk) is unchanged
  and still owner-gated; no `~/.openclaw` surface was touched.

### 10.4 Re-run results (post-fix)

```sh
$V -B -m py_compile nta-betta-picture-processing-v2/scripts/*.py                                   # OK
$V -B -m unittest discover -s nta-betta-picture-processing-v2/tests -p 'test_betta_firewall_adversarial.py'
# Ran 53 tests … OK
$V -B -m unittest discover -s nta-betta-picture-processing-v2/tests -p 'test_*.py'
# Ran 608 tests … OK
```

Counts: **53 adversarial tests** (51 original + 2 new hardening pins), **608
full-suite tests, all green** (543 as CI ran at the pre-fix head `4f6462e`, the
owners' hardening additions — net +12 by arithmetic — and the 53 adversarial
tests). Every earlier attack was re-run against the fixed code and still
survives: all central 5BT43/2BT23 gate and correction variants, the full CLI and
policy refusal paths, the below-gate veto matrix (`RETRY_ACCEPTED` for
below-gate fields; `RETRY_CONFLICT` for gated contradictions), source/crop/
evidence drift refusals, cross-product isolation, and the
protected-field/idempotency checks.

**Readiness:** the working tree is green locally and ready for the final commit.
The final **exact-SHA CI confirmation** must be requested after the master
pushes (this addendum and the updated adversarial suite are new commit content),
and the #34-stack CI re-run remains required before #34 → `main` (M3).

---

## 11. Exact-SHA confirmation (2026-10-15)

- **Reviewed & pushed head:** `b42c5915778d7607db36b08f2f1603e97ac0e764` — local `HEAD` == `origin/codex/betta-identity-incident-20261015` == PR #35 `headRefOid`; `git status --short` empty; the committed bytes of both A6 files are byte-identical to the reviewed revision. (The confirmation request's reference `b42c59157b99dcab4d01e25e532000ff6f5b7f35` does not exist on GitHub — `No commit found for SHA … (HTTP 422)`; transcription typo of the same `b42c591` prefix.)
- **CI on this exact SHA** (`gh api …/commits/b42c5915778d76…/check-runs`): `test` (Betta workflow CI) → completed/success ×2 (10:44:38→10:46:28, 10:44:40→10:46:22); `fulfilment` (Shipping fulfilment CI) → completed/success ×2 (10:44:38→10:44:48, 10:44:40→10:44:49). Green-run log: `Ran 608 tests in 98.588s` / `OK (skipped=1)` — **Betta workflow CI is green on this exact SHA.**
- **PR #35:** `headRefOid b42c5915778d7607db36b08f2f1603e97ac0e764`, `mergeStateStatus: CLEAN`, all four checks SUCCESS. PR #34 remains head `2ae58b1…` (`test` FAILURE ×2, `ModuleNotFoundError: No module named 'PIL'`) pending the stack merge.
- **Final:** **GO** merge PR #35 into base `codex/betta-autonomy-reconcile-20261014`; **NO-GO** deploy and **NO-GO** #34 → `main` until #34's head moves with the #35 stack (carrying the Pillow CI fix) and its CI is re-run green (M3).
