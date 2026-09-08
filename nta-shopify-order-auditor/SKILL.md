---
name: "nta-shopify-order-auditor"
version: "1.0"
description: "Canonical deterministic verification-phase auditor for Shopify order state; independently compares fresh live order data with authorised expected state."
---

# NTA Shopify Order Auditor — v1.0

## Purpose

Independently verify an exact Shopify **order** after an authorised write.

This module is verification-only. It does not make business decisions, perform writes, repair mismatches, fulfil orders, or adjust inventory.

Core principle: **Skills decide. Writers write. Auditors verify.**

## Required input

```yaml
order_audit_request:
  job_id: <stable job identifier>
  order_id: <exact Shopify order ID>
  expected:
    customer_id: null | <exact Shopify customer ID>
    line_items: null | []
    discount_code: null | <expected code>
    total_aud: null | <expected decimal string>
    financial_status: null | <expected status>
    zero_balance: null | true | false
    tags: null | []
    tags_mode: SUBSET | EXACT
    note: null | <expected note>
  protected_fields: []
  read_adapter_capability_verified: true | false
```

Only fields present in `expected` are audited. Do not infer extra expectations from the writer response or surrounding workflow.

## Fresh-state requirement

The live audit implementation must read the exact order from Shopify **after** the write. A mutation response, cached payload, local object, or writer return value is not acceptable verification evidence.

If a concrete order read adapter is unavailable or unverified, return `REVIEW_REQUIRED` and do not claim verification.

## Deterministic comparison

Use `scripts/order_audit.py` to compare a fresh order snapshot with caller-supplied expected state.

The comparator verifies, when requested:

- exact order identity;
- exact customer ID;
- exact variant IDs and quantities;
- discount code;
- total amount;
- financial status;
- zero-balance condition;
- tags using explicit `SUBSET` or `EXACT` semantics;
- note text.

Line-item comparison is exact by variant ID and quantity. Missing, duplicated, unexpected, or quantity-mismatched expected variants fail the audit.

The deterministic comparator performs zero model calls, zero network calls, and zero Shopify writes.

## Rules

1. Require an exact Shopify order ID.
2. Require a concrete, verified order read capability before live-read readiness.
3. Read the order fresh from Shopify independently of the writer response.
4. Compare only explicitly expected fields.
5. Never use the writer response as proof that a field was saved.
6. Never silently normalise a material mismatch into a pass.
7. Never repair a mismatch.
8. Never fulfil an order.
9. Never adjust inventory.
10. Report every mismatch with expected and observed values where possible.
11. Use `PASS_WITH_WARNING` only for non-material warnings that do not weaken verification of expected fields.

## Required output

```yaml
order_audit_result:
  final_status: PASS | PASS_WITH_WARNING | FAIL | REVIEW_REQUIRED
  job_id:
  order_id:
  expected: []
  verified: []
  mismatches: []
  warnings: []
```

`PASS` means every explicitly expected field matched the fresh independent order read-back.

## Out of scope

This version does not audit fulfilment state and does not prove inventory movement. Those require separate canonical auditors.

Run `python3 scripts/dry_run.py` for deterministic regression coverage.
