---
name: "nta-product-exception-gate"
version: "1.0"
description: "Convert NTA product confidence, contradictions, and risk into AUTO_APPROVE, warning, review, or block decisions before Shopify mutation."
---

# NTA Product Exception Gate — v1.0

## Purpose

Decide whether proposed product changes may proceed automatically.

This module does not resolve product facts itself. It consumes outputs from upstream modules and evaluates confidence, contradictions, and write risk.

## Required output

```yaml
exception_gate:
  status: AUTO_APPROVE | AUTO_APPROVE_WITH_WARNING | REVIEW_REQUIRED | BLOCK
  blocked_fields: []
  permitted_fields: []
  reasons: []
```

## AUTO_APPROVE

Use when identity is high confidence, required arithmetic is resolved, classification is clear enough for the affected fields, no material contradictions remain, and each intended write is supported by its canonical module.

## AUTO_APPROVE_WITH_WARNING

Use when the intended write is still safe but a non-critical caveat should be surfaced. Warnings must not conceal uncertainty that could materially change the write.

## REVIEW_REQUIRED

Use when an affected field depends on unresolved ambiguity such as:

- multiple plausible product/variant matches;
- unclear supplier pack-to-Shopify unit conversion;
- unknown GST basis that materially affects cost/pricing;
- conflicting purchase-critical specifications;
- ambiguous replenishment/preorder status;
- unusually large or weakly evidenced price movement;
- uncertain metafield scope/type;
- description facts with LOW confidence.

Independent deterministic fields may proceed only when they do not depend on the unresolved issue and the calling workflow permits partial writes.

## BLOCK

Use when product identity is unsafe, a duplicate application is detected, a write could corrupt inventory or the wrong product, or required evidence directly contradicts the proposed action.

## Principle

Do not downgrade a material problem merely to complete the workflow. Uncertainty belongs in the status, not hidden in prose.
