---
name: "nta-shopify-product-writer"
version: "1.0"
description: "Apply only authorised NTA Shopify product changes from approved module outputs, preserving unrelated fields and recording before/after state."
---

# NTA Shopify Product Writer — v1.0

## Purpose

Perform authorised Shopify product/variant writes. This module does not make business decisions; it applies decisions made by upstream canonical modules.

## Required input

A change set containing, for every field:

- exact product/variant identifier;
- field/path;
- current value;
- proposed value;
- source module;
- confidence;
- authorisation status;
- reason.

## Required output

```yaml
writes:
  applied_changes: []
  skipped_changes: []
  failed_changes: []
  write_status: SUCCESS | PARTIAL | FAILED | NONE
```

## Rules

- Read current live state immediately before consequential writes when stale data could matter.
- Write only fields explicitly authorised by the calling workflow.
- Preserve descriptions, images, handles, collections, tags, price, inventory, vendor, status and metafields unless each affected field is explicitly included in the change set.
- Treat inventory quantity as a separate operation from product/variant metadata.
- Never infer additional changes from context.
- Use exact product and variant IDs established by `nta-product-identity-resolver`.
- Refuse LOW-confidence identity writes.
- If one uncertain field can be safely skipped without blocking independent deterministic fields, apply only the independent approved fields and report the partial result.
- Record old → new values for auditability.
- Do not report the job complete; downstream `nta-product-qa-auditor` must independently verify live state.

## Idempotency

Avoid reapplying identical changes. Supplier-order workflows must preserve their own document/order fingerprint protections so inventory cannot be applied twice.
