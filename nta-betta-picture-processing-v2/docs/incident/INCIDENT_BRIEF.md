# P1 INCIDENT BRIEF — FredAPP misidentification 2BT23 → 5BT43 (2026-10-15)

Single source of truth for all incident-repair agents. Read this fully before acting.

## Incident (verified so far by the master orchestrator)

- 15 Oct 08:50:58 AEDT the owner uploaded a Betta photograph to Fred (OpenClaw `fred`
  agent, session `252e7ef3-aba0-47be-b1ca-9b5e6a869bfa`) with the text
  `Cost 15 / Retail 35 / Vendor Renial`.
- The attachment carried an auto-generated description that correctly read the
  card: tank "2BT23", date "4/10/2026" (misread of the handwritten 14/10), price "$35".
- At 08:52:12 Fred wrote — **with no tool call against the image in between** —
  "The attached photo physically reads **5BT43**, dated **9 October 2026** — not
  2BT23/4 October", then resolved Shopify product 5BT43
  (`gid://shopify/Product/7239072481489`), extended its own local write allowlist
  after a `betta_merch_scope_invalid` rejection (see below), and at 08:54:33 AEDT
  applied vendor `NTA Imports → Renial`, price `$25 → $35`, cost `$1 → $15` to 5BT43.
- 09:05:45 the owner challenged ("? this is 2BT23 where did you get 5BT43?").
  Fred doubled down: "the handwritten card in that file reads 5BT43, 9/10/2026"
  (09:07:23).
- 09:20-09:23 (after further owner instruction) Fred reverted 5BT43 to
  `NTA Imports / $25 / $1` and applied `Renial / $35 / $15` to 2BT23
  (`gid://shopify/Product/7255867588817`). Both receipts claim fresh read-back pass.

## Verified evidence

- Incident image (byte-identical copies of the owner's uploads, 2,936,221 bytes,
  1512×2688 PNG):
  `tests/fixtures/incident_2bt23/incident-photo.png` and
  `tests/fixtures/incident_2bt23/incident-photo-second-upload.png`
  SHA-256 `6e4a4f573f8cfc829218f798eeb5b45cd08803689d31d7db6fce4920cdca9ca9` (both).
- The photograph visibly shows `2 BT 23`, date `14/10/2026`, price `$35`.
- Fred later claimed the two uploads were byte-identical — TRUE (same SHA both times)
  — but irrelevant to the misreading.
- Mutation receipts: `tests/fixtures/incident_2bt23/evidence/` (unauthorised 5BT43
  change + repair receipt).
- Fred's write path: ad-hoc scripts in `~/.openclaw/workspace/fred/tmp/`
  (`betta_merch_update_5bt43_20261015.mjs`, `betta_merch_repair_2bt23_20261015.mjs`)
  against a **copied** session bridge
  `~/.openclaw/workspace/fred/tmp/betta-merch-20261014/scripts/shopify-session-bridge.mjs`
  using `NTA_BETTA_MERCH_WRITE_ENABLED=true`. The copy contains a merch scope
  allowlist (~line 774+) that the agent widened itself after the guard rejected the
  write.

## Root-cause hypothesis (to confirm/refute in forensics)

1. Fred never performed a vision read of the uploaded image before asserting a
   reading; the "5BT43 / 9 Oct" assertion appears to be context contamination /
   hallucination possibly reinforced by archive searches (the 2026-10-10 archived
   batch contained a real 5BT43 photo).
2. Confirmation bias: Fred then searched archives/Shopify for 5BT43, found matching
   artifacts, and proceeded.
3. The only mechanical guard (write-bridge scope allowlist) was defeated because the
   allowlist lived in an agent-writable local copy.
4. Fred's conversational flow has no deterministic identity contract binding
   "owner-requested tank" to "vision-detected tank" to "product actually mutated".

## This repository's exposure

The autonomous Betta pipeline (`nta-betta-picture-processing-v2/`) NEVER calls the
Fred conversational path; Fred used its own scripts/bridge. The pipeline already has
label cross-checks (focused label-crop retry; vision-preflight label conflict gate)
but does not yet run dual reads for every fish nor bind requested/detected identity
into the uploader manifest. Those gaps are this workstream's repair.

## Workstream ownership (STRICT — do not edit outside your set)

All work happens in **this worktree**: `/Users/davidlo/openclaw-skills-incident-repair`
(branch `codex/betta-identity-incident-20261015`). Rules for every agent:

- **Do NOT git commit, push, merge, or deploy anything.** Leave changes in the
  working tree. The master orchestrator commits.
- **Never mutate production Shopify.** All Shopify access is read-only
  (resolve/preflight/verify commands only). No `--live` executes.
- **Do not touch the live watcher** (`com.nanotanksaustralia.betta-watch`), the
  live intake `~/Documents/Betta Processing/`, or anything under `~/.openclaw`
  (read-only inspection is allowed).
- Do not modify fixtures under `tests/fixtures/incident_2bt23/` unless you own them.
- Run your scoped test modules only (`python3 -B -m unittest <module>`), with the
  venv at `/Users/davidlo/openclaw-skills-v3/nta-betta-picture-processing-v2/.venv/bin/python`
  (it has Pillow; there is no local pytest).

| Agent | Owns (edit) | Must not edit |
|---|---|---|
| A1 forensics | `docs/incident/P1_FORENSICS_2026-10-15.md` only (everything else read-only) | all code |
| A2 label recognition | `scripts/vision_review.py`, `scripts/label_identity.py`, `scripts/betta_prepare.py`, `tests/test_betta_label_identity.py`, `tests/test_betta_vision_review.py`, `tests/test_betta_prepare.py`, new `tests/test_betta_label_dual_read.py` | everything else |
| A3 firewall | `scripts/betta_shopify_batch.py`, `scripts/betta_corrections.py` (new), `scripts/betta_policy.py`, `tests/test_betta_shopify_batch.py`, new `tests/test_betta_corrections.py` | everything else |
| A4 orchestrator | `scripts/betta_process.py`, `scripts/betta_bau_adapters.py`, `scripts/betta_bau.py`, `tests/test_betta_process.py`, `tests/test_betta_bau_adapters.py`, `tests/test_betta_bau_integration.py` | everything else |
| A5 regression/QA | new `tests/test_betta_incident_2bt23.py`, `tests/fixtures/incident_2bt23/**` | everything else |
| A6 security review | `docs/incident/INDEPENDENT_REVIEW_2026-10-15.md`, new `tests/test_betta_firewall_adversarial.py` | everything else |

## Interface contracts (pinned — implement exactly)

1. `label_identity.compare_reads(full, crop) -> dict` (A2 implements; A4 consumes):
   - `full`/`crop` = `{"tank_id": str|None, "photo_date": str|None, "confident": bool}`
     with already-normalised values (normalisation is the caller's job for `full`,
     the label read already normalises).
   - Returns `{"status": "AGREE"|"DISAGREE"|"INCOMPLETE", "tank": str|None,
     "date": str|None, "reasons": [str, ...]}`.
   - `AGREE` only when both confident reads exist and match on normalized
     tank AND date. `INCOMPLETE` when either side is not confident.
     `DISAGREE` when both are confident and differ. No majority voting inside.
2. Dual label reads (A2 tools + A4 wiring):
   - Full-image read: existing `vision_review.py --mode catalogue`.
   - Label-crop read: `vision_review.py --mode label` (existing) — A2 may improve
     the crop quality/prompt and MUST add optional `visible_price` to the label
     output contract (strictly as an observation; never invented).
   - A4 runs BOTH reads for every publishable candidate fish, compares with
     `compare_reads`, performs at most ONE bounded independent re-evaluation on
     disagreement, and quarantines any still-unresolved tank/date contradiction.
3. Identity block in uploader manifests (A3 defines + validates; A4 fills):
   ```json
   "identity": {
     "source_sha256": "<raw camera original sha>",
     "detected_tank": "2BT23",         // vision-accepted identity
     "requested_tank": "2BT23",        // owner/entered target for this operation
     "accepted_tank": "2BT23",
     "correction_sha256": null | "<sha of immutable correction record>"
   }
   ```
   Uploader rule: `accepted_tank == requested_tank` must hold, OR a correction
   record must bind exactly (source_sha256, requested_tank, accepted_tank,
   product_id) and be hash-verified. Otherwise the uploader MUST refuse the item
   before any write. `detected_tank != requested_tank` without a correction is an
   automatic refusal.
4. Correction records (A3): immutable JSON created by
   `scripts/betta_corrections.py record`, schema
   `nta-betta-owner-correction-v1` binding: source_sha256, original_model_tank,
   corrected_tank, product_id (+variant), reason, evidence reference, operation
   scope (fields), operator, timestamp. Stored under a corrections directory;
   validated by `betta_corrections.validate_correction(...)`. Reuse for a
   different source/product/operation must fail.

## Non-negotiable protections

- Raw camera original preserved; Shopify Image 2 byte-identical to it.
- No autonomous acceptance loosening: dual-read machinery must QUARANTINE more,
  never publish more.
- Price/cost/vendor remain protected fields for autonomous Betta processing;
  owner-directed edits only through the explicit, verified target-product path.
- Existing inventory/duplicate/idempotency/read-back guards unchanged.
- Bounded retries only; no infinite loops; one terminal report per batch.
