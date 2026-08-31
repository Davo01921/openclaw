---
name: "nta-shopify-write-verifier"
version: "1.0"
description: "Canonical NTA Shopify mutation boundary that applies an authorised change set and independently verifies fresh live state."
---

# NTA Shopify Write Verifier

## Purpose

Provide one reusable, auditable Shopify mutation boundary. It coordinates the existing writer and auditor; it does not make product decisions or authorise fields.

## Required input

```yaml
write_request:
  job_id:
  idempotency_key:
  entity: product | variant | inventory | order | fulfilment | media
  resolved_identity: {}
  authorised_changes: []
  protected_fields: []
  retry_authorised: false
```

Every change must contain the current value, proposed value, path, source module, confidence, and reason. Reject a request without exact target identity, explicit authorisation, or an expected value for read-back.

## Procedure

1. Read current state when freshness matters and remove true no-op changes.
2. Invoke `nta-shopify-product-writer` for approved changes only.
3. Stop on material API/user errors; record an indeterminate result rather than guessing whether a retry is safe.
4. Invoke `nta-product-qa-auditor` against the exact approved changes and protected fields.
5. Return one immutable operation record with before/after values, mutation identifiers, verification result, warnings, and retry count.

## Result states

- `VERIFIED` — every intended field passed fresh read-back.
- `VERIFIED_WITH_WARNING` — all intended fields passed and a non-material warning is recorded.
- `PARTIAL` — only independently authorised changes verified; skipped/failed fields are listed.
- `FAILED` — a mutation or verification failed.
- `BLOCKED` — preconditions or authorisation failed.

Never call a successful API response completion. Only `VERIFIED` or an explicitly accepted `VERIFIED_WITH_WARNING` completes a write job.

## Ownership and compatibility

`nta-shopify-product-writer` remains the write-phase implementation and `nta-product-qa-auditor` remains the independent verification phase. New workflows call this module rather than invoking both separately.
