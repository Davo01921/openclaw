---
name: "nta-shopify-write-verifier"
version: "1.1"
description: "Canonical deterministic Shopify mutation boundary that routes authorised writes to entity-specific writers and independent auditors."
---

# NTA Shopify Write Verifier — v1.1

## Purpose

Provide one reusable, auditable Shopify mutation boundary. It coordinates canonical entity-specific writers and independent auditors. It does not make product, order, pricing, inventory, customer, discount, fulfilment, or loss-policy decisions.

Core principle: **Skills decide. Writers write. Auditors verify.**

## Supported entity routes

| Entity | Writer | Auditor | Status |
|---|---|---|---|
| `product` | `nta-shopify-product-writer` | `nta-product-qa-auditor` | supported |
| `variant` | `nta-shopify-product-writer` | `nta-product-qa-auditor` | supported |
| `inventory` | `nta-shopify-product-writer` | `nta-product-qa-auditor` | supported |
| `order` | `nta-shopify-order-writer` | `nta-shopify-order-auditor` | supported |
| `fulfilment` | none | none | **blocked until canonical pair exists** |
| `media` | none | none | **blocked until canonical pair exists** |

Do not route orders through the product writer or product QA auditor. Do not claim fulfilment/media support from the entity name alone.

## Required input

```yaml
write_request:
  job_id: <stable job identifier>
  idempotency_key: <stable unique key>
  entity: product | variant | inventory | order | fulfilment | media
  authorised: true
  resolved_identity: {}
  authorised_changes: []
  protected_fields: []
  expected_result: {}
  retry_authorised: false
```

Entity-specific child skills may require additional structured fields. This verifier must pass the exact authorised child request rather than reinterpret or broaden it.

## Deterministic routing

Use `scripts/verification_route.py` to select the canonical writer/auditor pair and enforce child-result gates. Normal routing performs zero model calls, zero network calls and zero Shopify writes.

A request without a stable job ID, stable idempotency key, explicit authorisation or supported entity is not executable.

## Procedure

1. Validate the verifier request and select the canonical entity route.
2. Read current live state before consequential mutation when the selected writer requires it.
3. Invoke only the selected canonical writer with the exact authorised change/request.
4. Fail fast if the writer returns failure, block or review-required state. Do not invoke downstream verification merely to repeat the failure.
5. If the writer returns `SUCCESS` or `DUPLICATE_NOOP`, perform a **fresh independent live read** from Shopify. Never use the writer response as verification evidence.
6. Invoke the selected canonical auditor against caller-supplied expected state and the fresh live snapshot.
7. Map auditor `PASS` → `VERIFIED`; `PASS_WITH_WARNING` → `VERIFIED_WITH_WARNING`.
8. On auditor `FAIL`, retry at most once and only when retry safety is positively established and retry is explicitly authorised. Reuse the original idempotency key. Never guess that an indeterminate write is safe to repeat.
9. A second mismatch, unsafe retry, write failure or material audit failure returns `FAILED` or `REVIEW_REQUIRED` as appropriate.
10. Return one immutable operation record containing route, before/after evidence, mutation identifiers, audit result, warnings and retry count.

## Order-specific boundary

For `entity: order`:

- writer: `nta-shopify-order-writer`;
- auditor: `nta-shopify-order-auditor`;
- exact order/customer/variant/quantity/discount/financial expectations remain owned by the upstream authorised request;
- the auditor must use a fresh Shopify order snapshot, never the writer payload;
- fulfilment and separate inventory adjustment are outside the order route.

The presence of these canonical child contracts does not by itself prove that a concrete live Shopify order adapter/read adapter is available. The child skills must still refuse live execution when their adapter capability is not verified.

## Result states

- `VERIFIED` — every intended field passed fresh independent read-back.
- `VERIFIED_WITH_WARNING` — all intended fields passed and only non-material warnings remain.
- `PARTIAL` — reserved for independently authorised partial product-domain outcomes; never use it to disguise an order mismatch.
- `FAILED` — mutation or verification failed.
- `REVIEW_REQUIRED` — execution or retry safety cannot be established deterministically.
- `BLOCKED` — preconditions, authorisation or canonical entity implementation is absent.

A successful API response is never completion. Only fresh independent verification can complete a write job.

## Refusal conditions

Refuse or stop when:

- target identity or explicit authorisation is missing;
- the entity route is unsupported or not implemented;
- a child writer/auditor capability is only declared but no concrete callable adapter exists;
- a writer returns `FAILED`, `BLOCKED` or `REVIEW_REQUIRED`;
- fresh live read-back cannot be obtained;
- audit evidence is derived from the writer response rather than an independent read;
- retry safety is indeterminate;
- a second verification mismatch occurs.

Never fall back to browser automation or an unrelated writer/auditor merely to make the operation succeed.

Run `python3 scripts/dry_run.py` for deterministic routing regression coverage.
