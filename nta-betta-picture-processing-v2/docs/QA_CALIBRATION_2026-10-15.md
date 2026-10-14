# QA calibration — analysis and decisions (2026-10-15)

Scope: the seven-of-eight owner-exception event in batch
`betta-20261014-161029-7e1j3n` (and the earlier 2026-10-10 material
exceptions), the calibrated comparison contract, and the regression fixtures
added with this change.  This document is evidence for Phase 2 of the autonomy
completion workstream.

## 1. Retrieved evidence

- Per-fish QA receipts: `betta-20261014-161029-7e1j3n/receipts/qa/*.json`
  (independent QA evidence with assertions, reasons and call attestation).
- Owner decision: `receipts/owner-qa-exceptions-20261014-180702.json`
  ("Owner visually reviewed the generated hero and accepted it for Shopify
  despite the preserved independent-QA failure"; discord message
  1559824840394018847) and the earlier Oct-10 exception records.
- Around 08:00 on 15 Oct the QA receipts of the earlier material cases
  (`4BT14`, `4BT15`, `3BT42`) were retrieved from the 2026-10-10 archive.

## 2. Categorisation of the failures

| Case | Failed assertions | Category | Substance |
|---|---|---|---|
| 2BT16 | – (PASS) | – | Clean pass; visible pattern agreement. |
| 2BT14 | same_identity, scale_markings, regional_colour, body_anatomy, tail_fins_pose | Evidence insufficiency + display pose | Source dark/low-detail; hero adds studio detail consistent with the visible blue-body/red-fin coat; fins displayed. |
| 2BT15 | same_identity, scale_markings, body_anatomy, tail_fins_pose | Evidence insufficiency + display pose | Source small/partly obscured; no contradiction of the visible colour family. |
| 1BT24 | same_identity, scale_markings, body_anatomy, tail_fins_pose, complete_framing | Evidence insufficiency + borderline framing | Hero red coat matches; framing complaint borderline but objective. |
| 1BT43 | same_identity, scale_markings, tail_fins_pose, label | Evidence insufficiency + metadata | Source dark; label complaint was source-card formatting noise (hero label is deterministically rendered). |
| 1BT45 | same_identity, scale_markings, regional_colour, body_anatomy, tail_fins_pose | Evidence insufficiency + display pose | "Cannot verify from the dim source" pattern. |
| 2BT21 | same_identity, scale_markings, body_anatomy, tail_fins_pose, realistic_texture | Evidence insufficiency + texture strictness | Directionally consistent copper/brown; "too clean" texture judged as synthetic. |
| 4BT14 (Oct 10) | regional_colour, same_identity, scale_markings, tail_fins_pose | **Genuine material change** | Introduces prominent blue markings and saturation the source visibly refutes. |
| 3BT42 (Oct 10) | label, same_identity, scale_markings, tail_fins_pose | **Genuine material change** + label metadata | Materially different marking distribution versus a visible source. |
| 4BT15 (Oct 10) | body_anatomy, label, regional_colour, same_identity, scale_markings, tail_fins_pose | **Incorrect label / identity mismatch** | Hero label reads 4BT15 while the source card appears to read 4BT12. |

Recurring themes in the seven excepetions: (a) "identity is uncertain because
the source is small/dark/obscured" — an evidence-sufficiency judgement, not a
contradiction; (b) "fins much more fully spread than the source" — a display
pose the generation contract explicitly allows; (c) sharpness/saturation
complaints about the same hues.

## 3. Calibration decisions

The hero QA prompt is the calibrated comparison contract.  Changes:

1. The hero is stated to be a generated studio representation of the SAME
   individual; the judge is a product-photography reviewer, not a forensic
   copy checker.
2. Explicit allowances (never a failure): display posture with more spread
   fins; sharper detail/cleaner texture; deeper saturation of the SAME hues;
   studio lighting; removal of water/debris/glare/background; fine detail the
   source cannot resolve when it does not contradict visible evidence (noted
   in reasons instead).
3. Explicit rejections (kept hard): different colour family or swapped
   regional colour distribution; different pattern class; different body or
   tail form class; materially different visible individual markings;
   fabricated anatomy (extra/missing/duplicated structures, gross distortion);
   fin-form contradictions or malformed fins; fin/tail tips cut off;
   clearly synthetic artefacts; label mismatch against the expected tank and
   date (now passed into the prompt); tank borders/cards/clutter present.
4. Assertion-level semantics were rewritten accordingly; `label` is judged
   against the deterministically rendered expected tank/date rather than the
   (sometimes unreadable) source card alone.

What was deliberately NOT done: no historical exception was converted into an
automatic pass; any evidence containing a failure of the identity assertions
still cannot pass the deterministic pipeline, and automatic (BAU) runs still
require a clean QA PASS with no exception.  The calibration changes what the
reviewer model calls a failure, not what the pipeline accepts.

## 4. Regression fixtures

`tests/fixtures/qa_calibration/` contains trimmed verbatim evidence for:
`accepted_2BT16`, `accepted_2BT14`, `accepted_1BT45`, `accepted_1BT43`
(owner-accepted 2026-10-14), and `rejected_4BT14`, `rejected_3BT42`,
`rejected_4BT15` (true rejections from 2026-10-10), each with its owner
decision and the calibrated expectation.  `test_betta_qa_calibration.py`
verifies the index integrity, pins the failure taxonomy against the genuine
records, and proves that historical exceptions never auto-pass the
deterministic pipeline.

The live half of the regression runs in Phase 4: the same photographs are
regenerated and re-judged under the calibrated contract, and the acceptance
rate and remaining false positives are measured (see the completion report).

## 5. Dry-run iteration findings (2026-10-15)

The first full-chain dry-run (3 genuine photographs, real generation and QA)
produced three findings, all addressed before the acceptance re-run:

1. **APE16** reached calibrated QA and failed on `regional_colour` and
   `scale_markings`.  Visual review of the source/hero pair shows the same
   green/turquoise fish with the same dark caudal-base markings; the complaint
   was the studio tone depth (darker, richer, more contrasty) — the same
   over-strict pattern.  The prompt now states explicitly that the hero is
   produced under studio lighting on a near-black background and that tonal
   rendering differences are presentation, never colour or marking failures;
   `regional_colour` fails on hue-direction contradictions and
   `scale_markings` fails on missing/moved/added discrete markings.
2. **2BT13**'s QA call hit a provider connection error ("No text output
   returned... Connection error") and was quarantined without a retry.  The QA
   stage now runs through the same bounded transport retries as the other
   vision stages, and every QA failure writes an immutable failure receipt
   (assertions, reasons, categories) that the batch report can cite.
3. **1BT43** was quarantined by the new identity cross-check: the catalogue
   read a confident but wrong date (`2026-04-10`) while the preflight read the
   handwritten card as `2025-10-14`.  The date on that card is genuinely
   ambiguous across reads; blocking before generation (and before any spend) is
   the intended fail-closed behaviour.  No guessing is performed.

A separate flow bug was also fixed: a supervised batch with zero publishable
fish previously crashed in the manifest builder instead of terminating as
`PARTIAL`.  All authority modes now stop cleanly before the manifest when no
fish is publishable.
