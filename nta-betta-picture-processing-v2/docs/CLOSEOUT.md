# Betta Processing closeout — 2026-10-02

Status: ONE CANONICAL VERSION — V2.1, READY FOR FINAL LIVE ACCEPTANCE.

## Purpose and architecture
Onboard a genuine newly received individual Betta from the designated Discord/photos intake to one existing Shopify tank product. The canonical source is nta-betta-picture-processing-v2; installed skill name remains betta-picture-processing. Model-assisted catalogue/image evidence feeds a deterministic ledger and protected-field Shopify mutation contract. The existing auth/session bridge is shared infrastructure, not a competing processing workflow.

PR #3's proposed V3 quota/overnight engine declares its Shopify writes deliberately absent. It is not sufficiently complete or demonstrably safer than V2.1. It is deferred and formally closed; no V3 production path is installed.

## Safety work and evidence
30 fixture tests pass, including exact tank/title mapping, independent Product/Variant/Location identity, source hash and image precedence, duplicate products, file tampering, protected fields, sold/inactive/negative/multiple-stock holds, explicit new-fish authority before reviving zero stock, conflict holds, telemetry, checkpoint recovery and archive file hashes. Saves fsync the checkpoint before atomic replacement.

Offline follow-up (9 October 2026) added `scripts/betta_runtime.py` and a `MUTATION_UNCERTAIN` hold state, and expanded the suite to 81 tests (44 added). The new tests use fake adapters, temporary ledgers and temporary SQLite databases to cover serialized writes, cross-batch intake deduplication, API-error classification, uncertain-write reconciliation (no automatic retry), CSV validation, telemetry-before-PASS and the complete intake-to-archive path. This is offline implementation evidence only: no live Shopify read/write, paid generation, installation, restart, activation or merge occurred, and the deployed runtime is not present in this repository (see docs/RUNTIME_ADAPTER_STATUS_2026-10-09.md). It does not replace the outstanding one-fish live acceptance.

A real 9 September archive has seven ARCHIVED items with retained Shopify readbacks. Independent filesystem checks verified all seven source and hero hashes (14/14). Its older title and ledger conventions differ from the current V2.1 contract, so it is historical evidence only and cannot establish today's changed workflow acceptance. Current Shopify data is checked read-only; a changed stock count after sale must not be called an onboarding regression.

## One final acceptance exercise
Use one genuinely new fish with its existing approved hero/source assets through the established V2.1 live-test path. Confirm staff new-fish authority with the exact source reference/hash if the existing tank product has zero stock. Require one fresh exact product/variant/location mapping, approved hero first and byte-identical source second, correct physical date/title, inventory exactly one, all protected fields unchanged and independent readback PASS. Then verify the archived files' hashes and telemetry row. Resume the same ledger: completed work must not cause a second mutation. Keep that complete receipt to close V2.1.

No paid image/model generation or Shopify mutation was performed during closeout. A previously approved operating path does not authorize inventing a new fish, reviving a sold fish or generating paid test assets.

## Operator responsibilities and limitations
Photos identify the fish/tank and physical date. Explicit staff corrections are recorded as source references; a photo/text conflict holds the item until resolved. Zero stock alone does not authorize onboarding or Shopify archiving. This workflow archives evidence, not sold Shopify products; status is protected. Sold-product archival belongs to separately authorized catalogue operations after order/identity verification. No product creation, price adjustment or inventory batch reset is implied.

The runtime owns live calls and must serialize ledger writes; atomic replacement is not a multi-writer lock. Cross-batch deduplication must use the retained intake/source references and archived ledgers. Current source files are preserved; old historical ledgers are not rewritten into new acceptance evidence.

## Deployment and recovery
The clean canonical main checkout is /Users/davidlo/openclaw-skills-v3. Main workshop and Fred workspace Betta SKILL.md entries now delegate to its nta-betta-picture-processing-v2 source; their obsolete supporting files are retained only for recovery. Both previous entries were backed up before replacement. Back up active ledgers, telemetry SQLite and approved assets before workflow updates. Resume from validated checkpoints; reconcile uncertain Shopify mutation results by independent read before any retry. Roll back code from the saved runtime/source revision while retaining new state. Do not restore inventory blindly from a prior snapshot, since a fish may have sold after onboarding. Archived paths must be updated in the ledger after copying/moving, with the same approved hashes verified before ARCHIVED.
