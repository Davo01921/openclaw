---
name: "nta-product-qa-auditor"
version: "1.1"
description: "Independent verification-phase implementation for nta-shopify-write-verifier."
---

# NTA Product QA Auditor — v1.0

## Purpose

Verify product changes after writing. A successful API response is not proof that Shopify contains the intended state.

New workflows call `nta-shopify-write-verifier`, which invokes this module after the writer. This module retains independent read-back responsibility and must not become a decision or repair engine.

## Required output

```yaml
qa:
  expected: []
  verified: []
  mismatches: []
  warnings: []
  final_status: PASS | PASS_WITH_WARNING | FAIL
```

## Rules

- Re-read the exact product/variant after writes.
- Compare every changed field against the approved expected value.
- Verify exact variant inventory, inventory policy and relevant metafields independently.
- For descriptions, compare saved HTML with generated approved HTML and run the canonical `nta-product-description-standard` QA requirements.
- For pricing, verify exact price/compare-at values actually saved.
- For tags/collections/metafields, verify only authorised changes and confirm unrelated protected fields were not unintentionally altered where practical.
- Treat missing, transformed, truncated, wrong-scope or wrong-variant values as mismatches.
- Do not silently repair a mismatch unless the calling workflow explicitly authorises a retry. Report retry results separately.

## Completion

Only PASS or an explicitly acceptable PASS_WITH_WARNING can satisfy the orchestrator's completion rule.
