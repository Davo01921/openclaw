# NTA Betta Processing V2.2 — BAU handover

Date: 2026-10-11 (Australia/Sydney)
Canonical runtime: `~/openclaw-skills-v3/nta-betta-picture-processing-v2/`
Repository: https://github.com/Davo01921/openclaw-skills

**BAU is NOT ACTIVATED. Critical gates failed; authority, paid generation and dispatcher remain disabled. The watcher is not installed or loaded.**

David’s standing approval is accepted. Existing successful E2Es are sufficient; no additional paid/live test or routine owner approval is required. Activation work made zero paid calls, zero Shopify mutations and zero Discord sends. Existing Grok generation code/prompts remain unchanged.

## Completed repairs

- Added exact persisted-manifest authorization with immutable receipts, strict inventory scope and mandatory budget caps.
- Added dispatcher-owned source selection, history deduplication, batch limits, durable notification intent, and read-only status/smoke.
- Repaired configured uploader/bridge/archiver wiring, full protected snapshots and SHA-verified generic audit inputs.
- Added strict production adapters, complete QA assertions, catalogue/title preservation, canonical uploader manifests, budget reservations and uncertainty replay refusal.
- Added actual verification timestamps, inert completed-batch restart, per-fish quarantine and terminal archive receipt gate.
- Prepared disabled policy/runtime configuration and launchd candidate using the existing image-capable virtual environment.

## Validation

266 offline tests passed. Independent safety review completed and identified the blockers below. Fresh read-only checks verified Nano Tanks Australia Shopify identity, the authenticated offline-session bridge, #betta-processing, telemetry integrity/writability, Keychain retrieval without exposure, configured vision capabilities, and deterministic 2048×2048 rendering.

Grok SHA-256: `5732aa9803f860eca361c26e34348220ba6fb510969eb81187e2b62550b2878e`

## Blocking gates and exact next actions

### 1. paid-cost-ceiling

grok_hero.normalized_usage({}) supplies USD 0.07 from nta_default_0.07; strict adapter settles fallback as reported actual.

Preserve Grok generation; require provider-reported cost or independently verified fixed-price upper bound for this exact model/quality before dispatch. Treat default/configured costs as estimates, not reported actual. Fail closed when no provable ceiling is available.

### 2. final-telemetry-archive

Telemetry and process snapshot are archived before archive receipt, ARCHIVED/COMPLETE and dispatcher outcome are persisted; archive completion timing remains absent.

Add finalization evidence after verified archive; persist archive timing and terminal process/dispatcher receipts, and SHA-verify final telemetry and outcome in the audit archive. Verify original intake-folder cleanup only against the archived source digest.

### 3. uncertain-reconciliation

PENDING_RECONCILIATION and unsettled generation are turned into terminal quarantined/ABANDONED batches; replay is refused but a reconciliation-only continuation cannot be scheduled.

Keep uncertainty in a distinct recoverable checkpoint. Permit read-only reconciliation without replay, only advance after proven outcome; preserve reservations and mutation idempotency journals.

### 4. vision-route-attestation

Strict evidence checker accepts execution_attested:false override and a naive 1970 timestamp.

Reject overrides and unknown/unattested provider/model in BAU. Require route-bound actual execution and timezone-aware timestamp bounded to the selected source/batch. Retain all call usage/retry evidence.

### 5. archive-readback-binding

Later archive report collection checks tank and PASS status without rebinding manifest/batch/command/timestamp or persisted report SHA.

Persist the verification report digest with the execute receipt. At archive, validate those exact bytes, exact batch/manifest identity, verify command and readback receipt before accepting PASS.

## Activation sequence after repair

Re-run the offline integration and independent review. Only when all critical gates pass: enable the scoped automatic policy and paid generation within USD 0.14/fish, USD 2.80/batch, 2 attempts/fish and 20 fish/batch; install/bootstrap the prepared watcher; verify launchd context, restart persistence and read-only smoke without processing any live batch.

Restart persistence remains unverified because activation stopped before installing launchd. Historical batches and photographs were not changed.

Evidence: `BAU_READINESS_REPAIR_2026-10-11.json`. Candidate watcher: `com.nta.betta-watch.plist` (prepared only).
