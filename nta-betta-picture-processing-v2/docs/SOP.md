# NTA Betta Processing V2.2 — Production SOP

Version: 2.2 · Status: production release; unattended activation gated (see §20)
Runtime: macOS · OpenClaw/Fred · Discord · Shopify Admin API · Grok/xAI · macOS Keychain

Normal owner action: **drop the original photographs into the intake folder.**
Normal Fred action: **complete the full workflow automatically.**
Owner intervention: **only genuine unresolved exceptions.**

No routine approvals, Discord start messages or Terminal commands are required
after activation.

## 1. Purpose and scope

Onboard genuinely received individual Bettas from labelled photographs into their
existing Shopify products: identify tank/date, create and verify the hero, apply
only authorised listing changes, independently verify, record telemetry, archive
and report. The Grok/xAI generation engine, model, prompts and enhancement method
are unchanged and out of scope for this SOP.

## 2. BAU operating model

1. Owner drops originals into `~/Documents/Betta Processing/`.
2. Fred detects them, allocates a batch, identifies tanks/dates, generates and
   finishes heroes, runs independent QA, matches existing products, applies only
   authorised changes under the standing policy, verifies Shopify, records
   telemetry, archives, cleans working files and reports in Discord.

## 3. Intake folder and supported formats

- Intake: `~/Documents/Betta Processing/` (top level only, non-recursive).
- Formats: `.png .jpg .jpeg .tif .tiff .heic .webp .bmp`.
- Ignored: dotfiles, `*.tmp/.part/.crdownload/.download/.partial`, generated names
  (`*-clean.png`, `*-labelled.png`, `test-hero.png`), and anything under
  `batches/`, `Archived Bettas/`, `Grok Tests/`, `Audit/`.

## 4. Automatic batch detection

`scripts/betta_watch.py` polls the intake folder, waits for files to settle
(`--settle-seconds`, default 20s), excludes already-processed source hashes via the
persistent `ProcessedRegistry`, and hands stable originals to the orchestrator.
The watcher is DISABLED by default and requires `--enable` plus owner approval.

## 5. Tank-number and date identification

`vision_review.py --mode catalogue` reads the label; `label_identity` normalises
`2 BT 14` → `2BT14` and Australian `D/M/YYYY` (ISO accepted). Year uses explicit
provenance; ambiguous year without a trusted reference is a hold. Unresolved or
duplicate tank IDs quarantine the affected fish — never guessed.

## 6. Existing Grok/xAI image processing

Unchanged: existing provider, model (`grok-imagine-image-2.0`), prompt, black
background, 2048×2048 output, identity-preservation rules and hero finishing
(`render_betta_label.py`). The generator is invoked via `grok_hero.py`.

## 7. Hero image requirements

2048×2048 PNG, one fish, clean near-black background, labelled tank/date block,
faithful to the source fish; the complete uncropped original is Image 2, byte
identical.

## 8. Independent QA and visual fidelity

`vision_review.py --mode qa` compares source, hero and original. Assertions cover
identity, anatomy, markings, colour, fins/tail, framing, texture, composition,
label and reference integrity. A material appearance discrepancy is never
auto-accepted: it quarantines unless the owner records a scoped exception.
Label/date mismatches are metadata issues (year provenance), not fidelity passes.

## 9. Product matching

Exact one-to-one match to an existing Betta product by tank token; the Product ID
is the primary identity. Ambiguous or absent matches quarantine the fish. No
product creation.

## 10. Shopify update permissions (standing policy)

Permitted, only on uniquely matched existing products: approved title, verified
arrival/photo date, approved hero (Image 1) + untouched original (Image 2) in
order, guarded inventory. Protected and never changed: description, retail price,
cost, vendor, product type, handle, status, Product/Variant/InventoryItem IDs,
unrelated metafields, inventory tracking, DENY policy.

## 11. Inventory adjustment rules

Guard: resolve the exact inventory item and location, read current quantity,
require tracking + DENY, allow only the configured transition (default 0→1),
apply with compare-and-set + persisted idempotency key, and verify. Unexpected
values hold. Never adjust stock twice for the same intake.

## 12. Independent Shopify verification

After mutation, fresh read-back must confirm identity, title, arrival date,
inventory exactly 1, hero Image 1, original Image 2, and every protected field.
An API success response alone is never proof. Uncertain writes are reconciled by
read before any retry.

## 13. Telemetry and cost tracking

Recorded as calls occur in `~/Documents/Betta Processing/betta-telemetry.sqlite3`
(`betta_call_telemetry`): batch, tank, stage, provider, model, attempt, timestamp,
duration, outcome, tokens when reported, cost + source, error. No invented usage.
Exports to `<batch>/reports/betta-call-telemetry.csv` and is archived. Grok fallback
USD 0.07/image only when the provider does not report a billed cost.

## 14. Archive structure

`scripts/betta_archive.py` writes `~/Documents/Archived Bettas/YYYY-MM-DD/` with
`Betta Processing/` (`<Tank ID> Original <Date>.<ext>` + inventory CSV),
`Betta Processed/` (`<Tank ID>.png`) and `Audit/` (manifest, receipts, QA,
reports, telemetry, exceptions). Batch-specific names
`<batch-id>-archive-{state,manifest}.json`; collisions isolate under the batch id.

## 15. Automatic cleanup

Working copies are removed only after destination SHA-256 verification. Unrelated
files, credentials, unresolved mutation state and archived evidence are never
deleted. Duplicate/redundant intake copies are moved to a dated quarantine folder
outside the intake directory, never deleted.

## 16. Discord reporting

Reports batch ID, photographs received, published, quarantined, Shopify
verification, generation cost, archive status and genuine errors. The owner is
notified on batch completion/partial, unrecoverable exception, or meaningful
system failure — not for routine work.

## 17. Exception handling

Classification: material appearance discrepancy (quarantine or scoped owner
exception), metadata/date error (deterministic resolution), QA false positive
(correct with evidence), technical error (retry within budget), unresolved
uncertainty (quarantine). A failed assertion is never converted to a plain pass.

## 18. Quarantine and recovery

Quarantined fish keep full evidence and are excluded from publication. Processing
is resumable from `<batch>/state/process.json`; completed stages and successful
per-fish work are never repeated. Uncertain Shopify results are reconciled by read
before retry.

## 19. Staff responsibilities

- Owner: place originals; decide genuine exceptions; approve any change to
  prompts/model/limits via change control.
- Fred: run the workflow automatically; report; never exceed the standing policy.
- Operators: emergency stop, rollback, credential checks (see §20).

## 20. Emergency stop procedure

1. Unload the watcher: `launchctl bootout gui/$(id -u)/com.nanotanksaustralia.betta-watch` (label history: `com.nta.betta-watch` retired 2026-10-15; logs now in `~/Library/Logs/nta-betta/`).
2. Disable standing authority: `python3 scripts/betta_policy.py set-enabled false`.
3. `set-paid-generation false` if generation must halt too.
4. Inspect `<batch>/state/process.json`; reconcile any uncertain Shopify result by
   read before any retry. Do not delete evidence.

## 21. Daily and periodic operational checks

- Daily: watcher health (`launchctl list | grep betta`), Discord report received,
  no blocked batches.
- Weekly: telemetry median/p90 onboarding time, retry rate, Grok spend, slowest
  states (`betta_metrics.py`).
- Monthly: archive hash spot-check, policy/credential validity, Keychain item
  present, rollback drill.
