# NTA Betta Processing V2.2 — BAU handover

**BAU ACTIVE — activated 2026-10-11, Australia/Sydney.**

Drop photographs into `~/Documents/Betta Processing/`. The watcher allows 60 seconds for transfers to settle and checks every 60 seconds. Eligible batches are processed automatically, verified against Shopify, archived with SHA-256 evidence, and reported to Discord #betta-processing.

## Approved configuration

- Canonical runtime: `~/openclaw-skills-v3/nta-betta-picture-processing-v2/`; repo https://github.com/Davo01921/openclaw-skills.
- Existing Grok generation and prompts preserved; SHA-256 `5732aa9803f860eca361c26e34348220ba6fb510969eb81187e2b62550b2878e`.
- Existing ledger limits remain USD 0.14/fish, USD 2.80/batch, two attempts/fish and 20 fish/batch. David waived the additional price-verification gate; the existing fallback accounting remains.
- Standing Shopify authority enabled only for eligible existing Betta products, bound automatically to each exact persisted production manifest. No product creation, protected-field edits or automatic material QA exceptions.
- Inventory remains tracked/DENY, scoped to the exact variant/location with compare-and-set and persisted idempotency.
- Actual image/source/hero hashes, attested vision route/provider/model, batch identity and timezone-aware timestamps are required. Material discrepancies quarantine.

## Completed repairs

1. Final archive: immutable final process/outcome and batch telemetry CSVs, archive completion timing, SHA-verified local/archive completion receipts; original intake cleanup only after archived-source hash verification.
2. Recovery: uncertain generation holds its reservation and never blindly retries; Shopify uncertainty uses read-only reconciliation. Pending batches remain recoverable and prevent conflicting intake.
3. Vision evidence: reject overrides, unknown or unattested routes, stale/wrong-batch evidence and invalid/future timestamps. Valid persisted receipts resume without another model call.
4. Archive readback binding: verification report bytes, SHA, batch, manifest, command, timestamp and exact tank PASS are revalidated before archiving. Archive inputs are frozen for safe resume.

## Evidence

- 298 offline tests passed; independent review passed with no remaining critical blockers.
- Read-only readiness probe executed through launchd: image runtime, photo-folder access, telemetry integrity, Keychain retrieval without exposure, Fred's image-capable OpenAI → Qwen Token Plan → Qwen API route, Nano Tanks Australia Shopify identity and Discord identity all passed.
- Authenticated Shopify bridge self-test passed; fresh read-only resolver preserved the exact protected snapshot and all inventory quantities.
- LaunchAgent `com.nta.betta-watch` installed and loaded, interval 60 seconds. Bootout/bootstrap verified persistent configuration and successful exit. This verifies service reload/login configuration, not a full Mac reboot.
- Standing authority, automatic per-batch authorization and paid generation enabled; activation hold released. Non-mutating smoke passed, no photos or active owned batches were pending, and dispatcher returned IDLE.
- Activation checks made zero paid generation calls, zero Shopify mutations and zero Discord sends. Existing successful E2Es were accepted; no extra live test batch was run.
- Detailed evidence: `BAU_ACTIVATION_EVIDENCE_2026-10-11.json`.

## Operation and recovery

Routine batches need no owner approval. Oversized scans, material discrepancies and uncertain writes fail closed; unresolved generation stays pending without paid replay. Resolve the recorded evidence before releasing a pending operation.

Configuration: `~/Documents/Betta Processing/bau-config.json`; policy: `automation-policy.json`; logs: `state/logs/watcher.stdout.log` and `watcher.stderr.log`; batch evidence: `batches/<batch-id>/`.

Emergency stop: set dispatcher configuration `enabled` false, disable policy `enabled` and `paid_generation_authorised`, then boot out `com.nta.betta-watch`. Preserve reservations and all batch/mutation journals. Reconcile unknown writes before any retry.
