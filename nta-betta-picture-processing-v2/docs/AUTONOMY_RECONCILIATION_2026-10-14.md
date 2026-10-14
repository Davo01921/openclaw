# Betta BAU autonomy — reconciliation, APE namespace, and identify hardening (2026-10-14)

Status: implemented on `codex/betta-autonomy-reconcile-20261014`; 329 offline tests
pass; a live self-heal and a read-only sandbox dry-run with real photographs
passed. This change set performed **no Shopify mutations** and no paid generation.

## Problem

The launchd BAU watcher was deadlocked since 2026-10-13 on an owned terminal batch
(`betta-20261013-161838-bduzet`): the batch was fully quarantined (identification
uncertain) and therefore had no archive receipt, while the finalization gate
required one — so every run reported `BLOCKED: owned terminal batch requires
reconciliation` and no new intake could be allocated.

## Fixes

1. **Zero-mutation deadlock.** A terminal batch that provably performed no Shopify
   mutation (every fish quarantined, nothing executed, no archive receipt) can
   never satisfy the archive-based finalization gate. The dispatcher now resolves
   such batches as a truthful terminal `PARTIAL`
   (`finalization: NOT_REQUIRED_NO_MUTATIONS`), closes them, notifies once, and
   continues. Batches that performed any mutation keep the unchanged archive and
   finalization contract.
2. **APE tank namespace.** `label_identity.normalize_tank`, the uploader `TANK_RE`,
   the Shopify bridge resolver, and the deterministic title builder accepted only
   `\d+BT\d+`, so every APE-namespace tank quarantined in BAU. All four validators
   now accept `APE\d+` (the hero label renderer already did).
3. **Identify contract + focused label retry.** The strict identify path rejected
   any catalogue read carrying model uncertainty notes or sub-0.90 date confidence
   — which real photographs routinely produce — and had never processed a real
   photo in production. It now returns truthful `uncertain` decisions (with a
   reason and an immutable receipt) for identity-quality outcomes, while
   call-level and attestation failures still raise. The orchestrator performs one
   focused top-30% label-crop re-read (`vision_review.py --mode label`) that must
   pass the same attestation and confidence gates before replacing an uncertain
   result; call-level failures get bounded retries (2 attempts) and are recorded.
4. **Pre-generation eligibility (automatic runs).** A read-only Shopify resolution
   and standing 0-to-1 baseline check runs before paid generation. Fish whose
   product is not writable under the standing scope (for example inventory already
   1) are quarantined with the exact reason before any generation spend.
5. **Truthful failure summaries.** Dispatch exceptions now enrich counts from the
   durable process state instead of reporting `published 0 / quarantined 0`, and
   are written to the watcher's stderr log.

## Evidence

- Offline suite: 329 tests pass (`python3 -B -m unittest discover -s
  nta-betta-picture-processing-v2/tests -p 'test_*.py'`).
- Self-heal observed live: the watcher reaped `bduzet` (19:37), processed the two
  remaining root photographs as `betta-20261014-193740-bqe1i0` (19:39; 2
  quarantined, no spend), and returned to `IDLE` with exit code 0.
- Read-only sandbox dry-run with both real photographs: identify → label-crop
  retry accepted (`1BT43`) → eligibility quarantine (`inventory baseline is 1`);
  confident read (`2BT13`) → eligibility quarantine. Outcome `PARTIAL`, one
  notification, zero generation calls, zero Shopify writes.

## Remaining functional item vs. the original brief (owner decision required)

The orchestrator brief's mandatory local pre-processing stage (aquarium-boundary
crop, exposure correction, water-debris cleanup, with its own crop-safety quality
gate) is **not** part of the approved V2.2/BAU chain: paid generation currently
consumes the raw camera original, and the Grok prompt plus independent QA handle
presentation quality (QA failures quarantine, never auto-accept). The supervised
flows of 10–14 October used one-off cleaned inputs and owner review; making that
stage autonomous means porting the prototype's `preflight.py` / `preflight_vision`
boundary detection and bounded local edits into the BAU pipeline as a new gated
stage with crop-safety tests. That changes the approved pipeline and spends
additional vision calls, so it is recorded here for an explicit owner decision
rather than added silently.

## Residual risks / notes

- Handwritten labels that differ by a single digit (for example 1BT43/1BT44) can
  be read differently across calls. The confidence gate, the focused label retry,
  exact product resolution, the uploader baseline guards and the QA label
  cross-check all apply; an identity flip on a writable (inventory-0) product
  remains the residual model risk to monitor.
- `betta-20261013-161815-skit0v` (manual APE16 batch) intentionally remains
  ACTIVE/unmanaged and does not affect BAU allocation.
