# Autonomous Betta completion — preparation, calibration, integration, acceptance (2026-10-15)

Workstream: finish the remaining unattended-processing requirements on
`codex/betta-autonomy-reconcile-20261014`.  No production Shopify write was
performed by this workstream; all Shopify mutations in testing were simulated
and clearly marked.

## 1. Local photo preparation (Phase 1)

New module `scripts/betta_prepare.py` (pure deterministic PIL, no external
calls) ported from the owner-reviewed local flow and the prototype preflight:

* **Bounds**: the vision preflight (`vision_review.py --mode preflight`,
  prototype prompt) supplies tank/fish/debris geometry plus an independent
  tank/date label read.  Bounds are usable only at ≥0.90 confidence with one
  fish and no retake flag.
* **Label cross-check**: a confident preflight label that disagrees with the
  authoritative identification **blocks the fish before any spend** ("tank read
  conflict" / "date read conflict"); unreadable labels do not block.
* **Crop**: vision tank bounds padded; the crop must contain the expanded fish
  safety rectangle (expanded, never clipped); min-area floor; no unverified
  fallback crops.
* **Exposure / white balance**: the owner-reviewed bounded enhancement profile
  (unchanged constants) with a severe-exposure guard that skips enhancement
  instead of inventing content; neutral-pixel white balance clamped to ±6%.
* **Debris**: tiny neutral bright components over dark water only, never
  inside the expanded fish rectangle (plus a one-cell half-scale exclusion
  ring so boundary dots can never be touched), capped at 2.5% of the frame,
  skipped over budget.
* **Prepared-image QA**: `vision_review.py --mode prep` compares the raw
  original with the working image (same_fish, full_fins, faithful_colours,
  tank_only, lighting_usable, no_identity_alteration).
* **Ladder**: full preparation → conservative fallback (no crop, no cleanup)
  → untouched raw copy.  Only provable inconsistencies (conflicts, changed
  sources, gate violations) quarantine; routine vision failures degrade to the
  conservative path with recorded notes.
* **Deterministic gate**: `verify_preparation()` re-checks every invariant
  (crop containment, fish-safety, mask separation, gain/exposure bounds, L1
  semantics) from the operations record; the adapter re-checks the working
  file bytes and dimensions.  Receipts are immutable and reused on resume.
* **Shopify Image 2 is unchanged**: the manifest binds the working image as a
  new `working` asset, while `original` remains the exact camera original
  (uploader updated to validate the new binding, backward compatible).

Pipeline wiring (`betta_process.py`): `IDENTIFIED → [label retry] →
[eligibility] → PREPARED → GENERATED → QA → …`; generation consumes the working
image; QA compares `[working, hero, raw]` with the expected tank/date passed
into the prompt.  All existing safeguards (authority, budgets, retries,
archive, single report, durable state) are unchanged.

## 2. QA calibration (Phase 2)

Evidence retrieval, categorisation of the seven-of-eight exceptions, and the
calibrated contract are documented in
[QA_CALIBRATION_2026-10-15.md](QA_CALIBRATION_2026-10-15.md).  Summary:
studio tone depth, display pose and source-detail insufficiency are now
explicit presentation allowances; hue-direction, pattern-class, visible
marking, fabricated-anatomy, framing and label contradictions remain hard
failures.  Genuine fixtures (accepted and rejected) live in
`tests/fixtures/qa_calibration/` with regression tests; historical exceptions
never auto-pass.  QA transport failures now retry and every failure writes an
immutable receipt with reasons + categories.

## 3. Acceptance (Phase 4)

* **Offline suite: 364 tests pass** (`unittest discover`), including
  crop-safety, fish-protection, debris-boundary, ladder, conflict, transport
  retry, taxonomy, zero-candidate and manifest-binding regressions.
* **Automatic-path dry-run** (real dispatcher, scratch paths, read-only
  Shopify, paid generation disabled): two genuine photographs → intake →
  identify + focused label retry → eligibility quarantine (inventory 1) →
  truthful `PARTIAL`, `NOT_REQUIRED_NO_MUTATIONS`, one report.  No spend, no
  writes.
* **Full-chain dry-run** (3 genuine photographs; real intake, identification,
  preflight, preparation, prepared-image QA, Grok generation, calibrated hero
  QA, read-only product resolution; simulated execute/archive, clearly
  marked):
  - Preparation: 3/3 `PREPARED` (2 × full, 1 × conservative fallback after a
    first-attempt prepared-QA rejection); raw originals untouched.
  - Generation: 3 Grok calls, **USD 0.21**; all generated from working images.
  - Calibrated hero QA: **1 PASS / 2 quarantined** (33% unconditional pass vs
    1/8 = 12.5% in the 14 October run), with failure fingerprints now specific
    and evidence-grounded:
    - `1BT43` PASS — "more fully spread fins, stronger scale definition, deeper
      saturation and higher contrast are consistent with an acceptable studio
      presentation"; label assertion validated the rendered tank/date.
    - `APE16` reject — "adds numerous prominent black oval spots across the
      dorsal fin that are not supported by the source"; audited as a
      defensible true-positive (discrete marking invention).
    - `2BT13` reject — "short-finned plakat form → long-finned form; fin-form
      class contradiction"; audited as a **remaining borderline false-positive
      candidate** (clamped in-tank fins can hide the display form).  The
      fin-class rejection is intentionally kept for now to preserve the
      fabrication protections; a one-line prompt allowance for clamped-fin
      sources is the documented fallback if this recurs.
  - One fish reached the manifest; the manifest was authorised in sandbox,
    "mutated" through the simulated uploader (recorded), and archived through
    the simulated archiver: truthful `PARTIAL` (1 published, 2 quarantined).
* **Real uploader verification on the dry-run manifest** (read-only):
  `preflight` and `dry-run` both reported `1BT43: PREFLIGHTED`,
  `shopify_writes_performed: false`, manifest SHA-256 matched — the real
  uploader validation path (including the new working-asset binding) was
  exercised without writes.
* **Vision/API usage** (full-chain dry-run): 24 recorded calls (intake 3,
  identify 3, label retry 2, preflight 3, prepared-QA 4, generation 3, finish
  3, hero-QA 3), zero call errors; Grok USD 0.21; vision token usage not
  reported by the provider.

## 4. Release state (Phase 5)

* All work is committed on `codex/betta-autonomy-reconcile-20261014` and
  pushed; the pull request is listed on the repository.
* The running local code is the canonical checkout
  `~/openclaw-skills-v3/nta-betta-picture-processing-v2`; the launchd watcher
  executes exactly this checkout.  `git rev-parse HEAD` and the SHA-256 of the
  key scripts are recorded in the workstream report.
* No merge or deploy is performed by this workstream; production writes
  remain gated by the standing policy.

## 5. Watcher service incident and hardening (2026-10-15)

During the release review the original watcher service was found in a wedged
launchd state: its last successful run was 04:08 local time, after which every
spawn failed instantly with `EX_CONFIG (78)` and no output.  Bisection showed
the program, environment and full plist content all work correctly under
launchd; the failing component was launchd opening the **existing** log files
inside `~/Documents/Betta Processing/state/logs/` (a new file in the same
directory worked).  That directory sits inside the Dropbox-managed Documents
tree, where actively appended files can become unopenable by launchd.

Hardening applied:

* service re-registered as **`com.nanotanksaustralia.betta-watch`** (matching
  the NTA launchd naming convention); the previous plist is retired as
  `~/Library/LaunchAgents/com.nta.betta-watch.plist.disabled-20261015`;
* watcher logs moved out of the synced folder to
  `~/Library/Logs/nta-betta/watcher.{stdout,stderr}.log` (historical logs
  preserved as `watcher.*.log.20261015-old` in the old location);
* verified after the change: run-at-load, 60-second interval runs and
  WatchPaths folder-trigger runs all execute with exit code 0.

Emergency stop is now:
`launchctl bootout gui/$(id -u)/com.nanotanksaustralia.betta-watch`.
