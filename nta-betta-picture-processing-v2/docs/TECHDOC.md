# NTA Betta Processing V2.2 — Technical Architecture

Version: 2.2 · Repository: `Davo01921/openclaw-skills` · Skill: `nta-betta-picture-processing-v2`
Canonical local skill: `~/openclaw-skills-v3/nta-betta-picture-processing-v2/`

## 1. Repository and module structure

```
nta-betta-picture-processing-v2/
  SKILL.md                      runtime contract
  docs/                         SOP, TECHDOC, SPECDOC, integration/audit records
  references/                   state machine, shopify contract, image standard
  scripts/
    betta_process.py            unified orchestrator (process_batch)
    betta_adapters.py           real batch-scoped adapters (injectable runners)
    betta_bindings.py           Shopify bridge/uploader/archive runner bindings
    betta_watch.py              automatic intake watcher (disabled by default)
    betta_batches.py            generic batch lifecycle + registry
    betta_policy.py             standing Shopify authorisation (disabled by default)
    betta_shopify_batch.py      manifest-bound Shopify writer (dry-run default)
    betta_archive.py            batch-scoped verified archiver
    betta_telemetry.py          telemetry SQLite + call recording/export
    betta_metrics.py            rolling efficiency metrics
    grok_hero.py                existing Grok/xAI generator (unchanged)
    betta_finish_heroes.py      batch-independent hero pipeline
    render_betta_label.py       deterministic label rendering
    label_identity.py           deterministic tank/date/price normalisation
    vision_review.py            catalogue/QA inference
    vision_batch.py             bounded parallel vision
    shopify_live.mjs            read-only resolve + preflight bridge client
  tests/                        offline unit/integration/regression tests
```

## 2. System architecture

```
intake folder --(watcher)--> batch workspace --(orchestrator)--> existing components
   betta_watch.py            betta_batches.py    betta_process.py
                                                  |-- betta_adapters.py (runners)
                                                  |     |-- vision_review (identify/qa)
                                                  |     |-- grok_hero + render_betta_label
                                                  |     |-- shopify_live / betta_shopify_batch
                                                  |     |-- betta_archive
                                                  |     '-- betta_telemetry
                                                  '-- betta_policy.py (authorisation)
```

Deterministic code owns state, identity, hashes, titles, transitions, inventory
guards and verification; models only observe/classify.

## 3. Unified orchestrator

`betta_process.BatchProcessor.process_batch(batch_dir, batch_id, adapters, policy)`.
Crash-safe state at `<batch>/state/process.json` (fcntl-locked, atomic writes).
Idempotent: completed stages and per-fish successes are skipped, so a restart never
repeats a paid generation or a Shopify mutation. Per-fish quarantine. The standing
policy authorisation is bound to the manifest SHA-256. Performs no external calls
itself.

## 4. Automatic intake watcher

`betta_watch.scan` lists top-level files, excludes transient/generated/archive
paths, requires the file mtime to be older than `settle_seconds`, and skips hashes
in the persistent `ProcessedRegistry`. Never moves/renames/deletes. CLI refuses to
run without `--enable`.

## 5. Batch state machine

Item/process stages: DETECTED → ALLOCATED → INTAKE_VERIFIED → IDENTIFIED →
GENERATED → QA_VERIFIED → SHOPIFY_RESOLVED → MANIFEST_READY → AUTHORISED →
SHOPIFY_EXECUTING → SHOPIFY_VERIFIED → TELEMETRY_EXPORTED → ARCHIVING → ARCHIVED →
COMPLETE, with terminal AWAITING_AUTHORISATION / AWAITING_LIVE / PARTIAL / BLOCKED.
Per-fish: PENDING, VERIFIED, PASS_WITH_ACCEPTED_EXCEPTION, QUARANTINED, FAILED.

## 6. Data structures and manifests

Batch: `batches/<batch_id>/{batch.json,intake,evidence,manifest,state,reports,receipts,archive}`.
Registry: `batches/registry.json` (append-only). Uploader manifest schema
`nta-betta-shopify-batch-v1`. Archive manifest
`nta-betta-archive-manifest-v1` (source/destination paths, hashes, timestamps).
Policy `nta-betta-automation-policy-v1`. Telemetry `betta_processing_telemetry` +
`betta_call_telemetry`.

## 7. Identity and label processing

`label_identity.normalize_tank/normalize_date/normalize_price`, and
`resolve_photo_date` with explicit year provenance (clear/ambiguous/missing), never
filename or filesystem-date inference.

## 8. Existing Grok/xAI integration

`grok_hero.py` (provider xAI, model `grok-imagine-image-2.0`, approved prompt,
black background, 2048×2048). Credential from `XAI_API_KEY` env or macOS Keychain
item `nta-betta-xai`. **Unchanged in V2.2** except the Keychain credential fallback.

## 9. Image finishing and QA

`render_betta_label.render` draws the deterministic label. `vision_review.py
--mode qa` returns assertions; failures quarantine unless a bound owner exception.

## 10. Shopify Admin API integration

Read-only resolve via `shopify_live.mjs resolve <tank>` (client-credentials OAuth
from the bridge env file). Mutations only via `betta_shopify_batch.py` against the
authenticated session bridge. API version default `2026-07`.

## 11. Authorisation and policy enforcement

`betta_policy.StandingPolicy`: `enabled`, `paid_generation_authorised`, protected
fields, inventory rule, and `authorisations` each bound to a manifest SHA-256.
`authorise(hash)` returns a receipt only for the exact approved bytes. Absent or
disabled fails closed.

## 12. Inventory compare-and-set and idempotency

Uploader uses `changeFromQuantity` compare-and-set plus a persisted UUID
idempotency key; resolve/read the exact inventory item and location; verify final
quantity. Unexpected values hold. No duplicate adjustment for the same intake.

## 13. Telemetry database and exports

`~/Documents/Betta Processing/betta-telemetry.sqlite3`. `record_call` appends per
call (fail-closed). `export_calls` → `<batch>/reports/betta-call-telemetry.csv`.
`batch_call_summary` reports calls/failures/known cost/unknown-cost calls. The
archive gathers the CSV.

## 14. Batch-scoped archival

`betta_archive.py` layout `Archived Bettas/YYYY-MM-DD/{Betta Processing,Betta
Processed,Audit}` with batch-specific `archive-state/manifest` names; a collision
isolates the batch under its id instead of overwriting.

## 15. Archive SHA-256 verification

Every destination is copied, hashed and compared to the source before the specific
source is removed; the immutable manifest records both. `status` lists per-batch
records; resume is idempotent.

## 16. OpenClaw and Discord integration

Fred agent loads skill `betta-picture-processing` (delegator to the canonical dir).
Discord reports batch outcomes; the obsolete V3 canary channel prompt is closed.

## 17. Credential management

Shopify: bridge env file (client id/secret/store). xAI: env or Keychain
`nta-betta-xai`. No credential value is read, printed, logged or committed by the
Betta tooling.

## 18. Paid generation budgets

Fallback USD 0.07/image when provider cost is unreported. Per-fish and per-batch
ceilings and retry policy must be set in the standing policy before paid
unattended execution; unknown cost is never treated as zero.

## 19. Logging and observability

Structured telemetry per call/stage; process state and immutable event records;
archive manifests; `betta_metrics.py` rolling summaries.

## 20. Restart persistence

State under the batch workspace; the processed-source registry prevents duplicate
intake after restart; completed work is not repeated.

## 21. Failure recovery

Resume from the last validated checkpoint; reconcile uncertain Shopify results by
read before retry; quarantine individual failures without blocking safe fish.

## 22. Quarantine handling

Uncertain identity or material QA discrepancy quarantines the fish with retained
evidence; excluded from publication.

## 23. Production configuration

- Intake `~/Documents/Betta Processing/`; archive `~/Documents/Archived Bettas/`.
- Policy `~/Documents/Betta Processing/automation-policy.json`.
- Watcher via launchd (`com.nta.betta-watch`), enabled only after approval.

## 24. Deployment and rollback

Release merges to `main`; canonical checkout fast-forwards. Rollback: `git revert`
the release commit; disable the watcher (`launchctl unload`), disable the policy
(`set-enabled false`); archive files are additive and never modified.

## 25. Automated tests and CI

`.github/workflows/betta-ci.yml` compiles scripts and runs
`unittest discover -s nta-betta-picture-processing-v2/tests`. Offline unit,
integration and regression tests cover orchestrator, adapters, bindings, policy,
watcher, archive, telemetry, lifecycle and the historical QA analysis.

## 26. Known limitations

- Live orchestrator adapter runners for the Shopify bridge resolve/uploader are
  bound but a supervised live orchestrator run has not yet been performed.
- Production paid-generation budget/retry ceilings are not yet set (see §18).
- Vision identification of previously unseen label formats depends on the live
  model; ambiguous cases quarantine.
- The watcher and standing authority remain disabled until activation gates pass.
