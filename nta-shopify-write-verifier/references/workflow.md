# NTA Shopify Write Verifier workflow

## Canonical route

1. Receive an already-authorised write request with stable `job_id` and `idempotency_key`.
2. Select the entity-specific canonical pair.
3. Invoke the selected writer only.
4. Fail fast on writer failure/block/review state.
5. After successful or duplicate-noop write handling, obtain a fresh independent Shopify snapshot.
6. Invoke the selected auditor against expected state + fresh snapshot.
7. Map PASS to VERIFIED; PASS_WITH_WARNING to VERIFIED_WITH_WARNING.
8. Retry a failed audit at most once, only when retry safety is positively established and retry is explicitly authorised.
9. Otherwise stop FAILED/REVIEW_REQUIRED/BLOCKED.

## Routes

```text
product / variant / inventory
  -> nta-shopify-product-writer
  -> fresh read
  -> nta-product-qa-auditor

order
  -> nta-shopify-order-writer
  -> fresh order read
  -> nta-shopify-order-auditor

fulfilment
  -> BLOCKED until canonical fulfilment writer + auditor exist

media
  -> BLOCKED until canonical media writer + auditor exist
```

## Non-negotiable boundaries

- Writer API responses are not verification evidence.
- Order writes never route through the product writer.
- Order audits never route through the product QA auditor.
- Fulfilment is not implied by order support.
- Never retry an indeterminate consequential write by assumption.
- Never substitute browser automation or an unrelated writer for a missing canonical adapter.
- This verifier coordinates; it does not invent business decisions or broaden an authorised change set.
