---
name: "nta-automation-orchestrator"
version: "1.0"
description: "Route non-financial NTA automation jobs through specialist workflows and shared product, Shopify, and model-delegation modules."
---

# NTA Automation Orchestrator

## Purpose

This is the sole top-level NTA automation entry point. It routes a job; it does not repeat supplier, pricing, content, inventory, image, Shopify, shipping, or model rules.

Financial, debt, repayment, banking, accounting, and reconciliation jobs are out of scope. Return `OUT_OF_SCOPE_FINANCIAL` without invoking any NTA workflow.

## Job envelope

Create one durable job record before dispatch:

```yaml
job:
  id:
  source: discord | shopify | scheduled | manual | api
  mode: dry_run | write
  workflow:
  correlation_id:
  idempotency_key:
  requested_changes: []
  protected_fields: []
  status: PLANNED | RUNNING | REVIEW_REQUIRED | BLOCKED | COMPLETE | PARTIAL
```

Use the supplier document fingerprint, Shopify order ID, Discord thread ID, or equivalent stable source identifier as the idempotency key. Do not repeat consequential operations after an ambiguous provider failure.

## Route table

| Job | Specialist owner | Shared modules required where a Shopify product changes |
|---|---|---|
| Catalogue, pricing, description, inventory or availability | `nta-product-orchestrator` | `nta-product-resolver`, `nta-shopify-write-verifier` |
| Supplier purchase order/invoice | `nta-supplier-order-processing` | `nta-product-orchestrator` |
| Standard stock intake | `nta-inventory-update` | `nta-product-orchestrator` |
| Individual or batch Betta media/intake | `nta-betta-picture-processing-v2` | resolver, inventory/availability/metafields, write verifier |
| Dropship order | `nta-dropship-order-processing` | resolver and write verifier only for authorised product/order updates |
| Shipping/fulfilment | `nta-shipping-fulfilment` | write verifier only for authorised Shopify fulfilment state |
| Death/loss order | `nta-death-loss-order` | exact variant resolution and fresh Shopify verification |

## Dispatch rules

1. Select the narrowest specialist workflow.
2. Use `adaptive-model-router` only for tasks that need a model. Deterministic parsing, arithmetic, API calls, change-set comparison, and verification must not consume model capacity.
3. Require an explicit authorised change set before a Shopify mutation.
4. Require fresh read-back through `nta-shopify-write-verifier` after every Shopify mutation.
5. Aggregate warnings and unresolved items. `COMPLETE` requires verification of every intended write; otherwise return `PARTIAL`, `REVIEW_REQUIRED`, or `BLOCKED`.

## Boundary rule

Specialist workflows own their source-specific intake, idempotency and external partner actions. Shared modules own reusable product decisions and Shopify mutation assurance. No workflow may silently widen its authority.
