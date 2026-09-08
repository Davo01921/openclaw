---
name: "nta-product-metafields"
version: "1.1"
description: "Deterministically map approved NTA product state into canonical Shopify metafield change proposals without deciding business rules or writing Shopify."
---

# NTA Product Metafields — v1.1

## Purpose

Translate already-decided NTA product state into canonical Shopify metafield change proposals.

This module does not decide availability, pricing, physical inventory, product identity, product facts, supplier ETA, or whether Shopify should be written. It only maps approved structured state into allowed metafield proposals.

## Architecture

`Skills decide. Writers write. Auditors verify.`

Upstream canonical modules decide business state. `nta-product-metafields` maps that state. `nta-shopify-product-writer` performs authorised writes. `nta-shopify-write-verifier` verifies live state.

Normal execution of this mapper requires:

- 0 model calls
- 0 network calls
- 0 Shopify writes

## Files

```text
nta-product-metafields/
├── SKILL.md
├── schema/
│   └── metafields.json
└── scripts/
    ├── metafield_mapper.py
    └── dry_run.py
```

## Canonical registry

Only fields present in `schema/metafields.json` may be mapped automatically.

Current canonical mappings are:

- `preorder_eligible` → `custom.preorder_eligible`
- `preorder_status_override` → `custom.preorder_status_override`
- `arrival_date` → `custom.arrival_date`
- `in_store_location_tank_number` → `custom.in_store_location_tank_number`

The registry defines the canonical namespace/key, authoritative source path, and value validation rule. It intentionally does not invent live Shopify definition metadata.

## Verified definition metadata

For every proposed metafield, the caller must provide previously verified Shopify definition metadata:

```yaml
verified_definitions:
  custom.preorder_eligible:
    owner_scope: PRODUCT | VARIANT
    type: <verified Shopify metafield type>
```

The mapper does not fetch definitions from Shopify during normal execution.

If namespace/key is unknown, or definition scope/type has not been verified, return `REVIEW_REQUIRED`. A separate schema-maintenance workflow may inspect Shopify definitions and update the canonical registry or verified metadata when authorised.

## Input contract

```yaml
requested_fields:
  - preorder_eligible
  - preorder_status_override

availability:
  preorder_eligible: true
  status_override: automatic

product_state:
  arrival_date: 2026-09-08
  in_store_location_tank_number: 63.10.1

verified_definitions:
  custom.preorder_eligible:
    owner_scope: PRODUCT
    type: <verified type>
  custom.preorder_status_override:
    owner_scope: PRODUCT
    type: <verified type>
```

Only requested fields are considered. Unrelated metafields must be preserved.

## Output contract

```yaml
status: READY | REVIEW_REQUIRED

metafields:
  proposed:
    - canonical_name:
      namespace:
      key:
      owner_scope: PRODUCT | VARIANT
      type:
      value:
      source_path:
  preserve_unrelated: true
  notes: []

missing_or_conflicting_fields: []
notes: []
```

`metafields` may be null when review is required.

## Deterministic validation

### Availability

Availability mappings must consume approved `nta-product-availability` output rather than independently deciding preorder logic.

- `preorder_eligible` must be a boolean.
- `preorder_status_override` must be exactly one of `automatic`, `eta_tbc`, or `disabled`.

### Arrival date

`custom.arrival_date` must come from a confirmed/supplied canonical arrival date. The mapper accepts an ISO `YYYY-MM-DD` date only.

Do not substitute:

- today's date;
- supplier PO date;
- supplier ETA;
- photo date;
- historic delivery timing;
- guessed or conversational dates.

### Tank/location

`custom.in_store_location_tank_number` must receive a non-empty authorised upstream tank/location string. This mapper does not invent, normalise, or infer tank numbers from prose.

## Review triggers

Return `REVIEW_REQUIRED` when any requested field has:

- an unknown canonical field name;
- a missing authoritative source value;
- an invalid value;
- a missing verified Shopify metafield definition;
- an invalid or unresolved PRODUCT/VARIANT owner scope;
- a missing/invalid verified metafield type;
- conflicting structured inputs.

Do not use fuzzy `HIGH | MEDIUM | LOW` confidence.

## Safeguards

- Never invent a metafield namespace, key, type, or scope.
- Never query Shopify merely to make a normal mapping decision.
- Never write Shopify from this module.
- Preserve unrelated metafields.
- Do not encode availability, pricing, inventory, or classification business rules here.
- Do not duplicate a canonical business rule in metafield mapping code.
- Do not silently map an unknown field.
- Do not convert ambiguous free-form language into commercial state.

## Writer handoff

A `READY` proposal may be passed downstream to `nta-shopify-product-writer` only after the calling workflow has supplied exact product/variant ownership identifiers, current values, authorisation, and any other writer-required audit fields.

The writer performs the mutation. `nta-shopify-write-verifier` independently verifies the final live state.

## Verification

Run:

```bash
python3 scripts/dry_run.py
```

The regression suite checks canonical availability mapping, arrival date mapping, tank location mapping, unknown-field rejection, verified-definition gating, enum validation, and ISO-date validation without Shopify writes, network calls, or model calls.
