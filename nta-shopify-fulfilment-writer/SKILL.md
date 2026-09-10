---
name: "nta-shopify-fulfilment-writer"
version: "1.2"
description: "Canonical deterministic and guarded live write-phase contract for authorised Shopify fulfilment actions."
---

# NTA Shopify Fulfilment Writer — v1.2

## Purpose

Apply an already-authorised Shopify fulfilment action. This module does not decide order identity, fulfilment policy, tracking, notification policy, or inventory policy.

Core principle: **Skills decide. Writers write. Auditors verify.**

## Deterministic contract

The planner accepts:

```yaml
job_id: <stable id>
idempotency_key: <stable id>
authorised: true
order_id: <exact Shopify order ID>
notify_customer: false
fulfilment_orders:
  - fulfilment_order_id: <exact Shopify FulfillmentOrder ID>
    line_items:
      - fulfilment_order_line_item_id: <exact ID>
        quantity: <positive integer>
duplicate_completed: false
prior_result_indeterminate: false
retry_authorised: false
adapter_capability_verified: false
```

For NTA death-loss orders, tracking is omitted and customer notification is false. The writer must never invent tracking information.

## Guarded live adapter

`scripts/shopify_fulfilment_api.py` implements the concrete Admin GraphQL transport for Shopify API `2026-07`. It prefers the local allowlisted persisted-session bridge at the standard NTA auth-project path (override with `NTA_SHOPIFY_SESSION_BRIDGE_PATH`) and keeps the explicit Admin-token configuration only as a legacy fallback.

It provides:

- `probe_capabilities(live=True)` — read-only scope probe;
- `build_create_payload(...)` — deterministic `fulfillmentCreate` mapping;
- `create_fulfilment(...)` — guarded live mutation;
- `read_fulfilment_order(...)` — fresh `FulfillmentOrder` read including `remainingQuantity` and `inventoryItemId`;
- `read_inventory_level(...)` — fresh inventory-level read when an exact level ID is already known.

The live mutation remains blocked unless all of these are true:

1. `execute=True` is supplied by the authorised caller;
2. environment variable `NTA_SHOPIFY_FULFILMENT_WRITE_ENABLED=true` is set;
3. the persisted offline-session bridge (preferred) or legacy Shopify configuration is present;
4. a qualifying fulfilment write scope is positively observed;
5. offline authentication is positively attested by the bridge, or the legacy token is explicitly marked `SHOPIFY_TOKEN_MODE=offline`.

The bridge accepts the auth app's native `SHOPIFY_API_KEY`, `SHOPIFY_API_SECRET`, and `SHOPIFY_STORE_DOMAIN` names, plus the existing NTA aliases `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET`, and `SHOPIFY_STORE`. Credentials are needed only when Shopify requires offline-session rotation; they are never returned by the bridge or printed by the probe.

The adapter does not infer tracking information and does not perform any separate inventory mutation.

## Required Shopify capabilities

Shopify `fulfillmentCreate` requires one qualifying fulfilment write scope and the underlying user/app permission to fulfil and ship orders. Fresh `FulfillmentOrder` reads require a qualifying fulfilment-order read scope. Inventory verification requires `read_inventory` (or a token that exposes equivalent inventory read capability).

Use:

```bash
python3 scripts/capability_probe.py
```

for a read-only live capability check. The probe prints no token or credential value and performs no Shopify mutation.

## Safety gates

- exact order and fulfilment-order IDs required;
- exact fulfilment-order line-item IDs and positive quantities required;
- duplicate completed action returns `DUPLICATE_NOOP`;
- indeterminate retry requires explicit retry authorisation with the same idempotency key;
- live execution remains blocked until the concrete Shopify fulfilment adapter capability is verified;
- no inventory adjustment is performed here;
- successful mutation response is not completion; fresh independent fulfilment and inventory verification are still mandatory.

Run:

```bash
python3 scripts/dry_run.py
python3 scripts/adapter_dry_run.py
```

for deterministic regression coverage. These tests perform no Shopify writes, network calls, inventory changes, or model calls.
