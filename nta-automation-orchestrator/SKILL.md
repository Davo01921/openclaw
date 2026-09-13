---
name: "nta-automation-orchestrator"
version: "1.4"
description: "Route non-financial NTA automation jobs through specialist workflows and shared product, Shopify, customer-service, and canonical model-routing modules."
---

# NTA Automation Orchestrator

## Purpose

This is the sole top-level NTA automation entry point. It routes a job; it does not repeat supplier, pricing, content, inventory, image, Shopify, shipping, customer-service, or general model-selection rules.

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
| Standard stock intake (including requested DYMO tank labels) | `nta-inventory-update` | `nta-product-orchestrator`; labels use `nta-dymo-tank-label` after verified Shopify state, or planned Shopify state in dry-run mode |
| Individual or batch Betta media/intake | `nta-betta-picture-processing-v2` | resolver, inventory/availability/metafields, write verifier |
| Shopify dropship trigger / recent-order scan | `nta-dropship-order-trigger` | dispatches candidates to `nta-dropship-order-processing`; no direct Shopify writes |
| Dropship order | `nta-dropship-order-processing` | resolver and write verifier only for authorised product/order updates |
| Shipping/fulfilment | `nta-shipping-fulfilment` | write verifier only for authorised Shopify fulfilment state |
| Death/loss order | `nta-death-loss-order` | exact variant resolution and fresh Shopify verification |
| Customer complaint, refund, replacement, livestock-health concern, service dispute or goodwill request | `nta-customer-service` | live Shopify/order evidence where relevant; write verifier for any authorised Shopify mutation |

## Dropship trigger rule

When the source is a Shopify order event, scheduled recent-order scan, or manual order recheck intended to detect dropship work, route first to `nta-dropship-order-trigger`. The trigger may only detect and dispatch. Supplier hand-off remains exclusively owned by `nta-dropship-order-processing` and its configured supplier adapter.

A webhook payload is a wake-up signal, not authoritative product state. Before a consequential action, downstream processing must re-read the live Shopify order and live dropship product metafields.

## Customer-service routing rule

When the request concerns a complaint, refund, replacement, livestock health/DOA issue, fulfilment dispute, product representation, pickup/shipping misunderstanding, or goodwill request, route to `nta-customer-service` before drafting the customer response or making a remedy decision. The customer-service skill must gather the relevant live evidence, classify responsibility, run the ACL/policy and devil's-advocate checks, and determine the recommended remedy before any consequential Shopify write is authorised.

## Canonical model-routing rule

`adaptive-model-router` is the sole selection authority for interchangeable reasoning, extraction, review and vision-inference models used by this orchestration layer and its child workflows.

- First remove deterministic work. Parsing after extraction, arithmetic, exact comparisons, payload construction, API calls, idempotency, state transitions and read-back verification should not consume a model when deterministic execution is sufficient.
- For every genuinely model-required general inference/reasoning phase, resolve the phase through `adaptive-model-router` before dispatch.
- Child skills may declare capability needs such as vision, structured extraction, ordinary reasoning or deep review, but may not independently choose general-purpose providers, hard-code reasoning/inference model slugs, define competing fallback chains or silently escalate model cost.
- A directly invoked specialist skill inherits the same rule even when this top-level orchestrator was bypassed.
- A fixed, non-substitutable specialist service may remain owned by its specialist workflow for its bounded operation under the router's specialised-service boundary. Example: Betta `grok_hero` may remain a fixed Grok/xAI image-generation step; this does not make Grok an eligible general reasoning/review route.
- Model choice never expands operational authority. Existing writer, verifier, exception-gate and explicit-authorisation requirements still apply.
- Requested route and actual execution are separate facts; use runtime metadata before claiming which provider/model handled general model work.

## Dispatch rules

1. Select the narrowest specialist workflow.
2. Classify deterministic phases as `NONE` through the `adaptive-model-router` contract; route only genuinely model-required general inference/reasoning phases through the router.
3. Preserve the router's configured general-provider/fallback policy. Do not create one-off model overrides that silently bypass it.
4. Keep fixed specialist services bounded to their defined operations; do not repurpose them as alternate general model routes.
5. Require an explicit authorised change set before a Shopify mutation.
6. Require fresh read-back through `nta-shopify-write-verifier` after every Shopify mutation.
7. After an ambiguous provider failure, verify external state before retrying any consequential action.
8. Aggregate warnings and unresolved items. `COMPLETE` requires verification of every intended write; otherwise return `PARTIAL`, `REVIEW_REQUIRED`, or `BLOCKED`.

## Boundary rule

Specialist workflows own their source-specific intake, idempotency, fixed specialist-service dependencies and external partner actions. Shared modules own reusable product decisions and Shopify mutation assurance. `adaptive-model-router` owns interchangeable general inference/reasoning model selection. No workflow may silently widen its authority or create a competing general model-routing policy.
