---
name: "nta-inventory-state"
version: "1.1"
description: "Deterministically interpret NTA physical stock facts and propose safe Shopify inventory SET, ADD, or NONE actions independently from preorder availability."
---

# NTA Inventory State — v1.1

## Purpose

Determine the physical inventory action for an exact Shopify variant from structured stock facts.

This module owns stock quantity interpretation only. It does not resolve identity, decide preorder eligibility, change inventory policy, set retail price, write descriptions/tags, determine supplier ETA, or write Shopify.

## Design principle

Use deterministic rules for all normal inventory-state decisions.

Do not ask a model to decide arithmetic, SET vs ADD, ordered-vs-received stock, usable physical quantity, or whether a known inventory action is safe.

If exact variant identity, stock location, sell-unit conversion, or usable physical quantity is unresolved, return `REVIEW_REQUIRED` rather than guessing.

## Production files

```text
nta-inventory-state/
├── SKILL.md
└── scripts/
    ├── inventory_state.py
    └── dry_run.py
```

`scripts/inventory_state.py` is deterministic Python and performs no Shopify writes, network calls, or model calls.

## Input contract

Provide structured inventory facts:

```yaml
inventory_input:
  variant_resolved: true | false
  job_state: ORDERED | RECEIVED | COUNTED | CORRECTION
  quantity_basis: PHYSICAL_COUNT | RECEIVED_INCREMENT | NONE
  usable_quantity:
  current_available:
  current_on_hand:
  location:
  sell_unit_conversion_status: RESOLVED | NOT_APPLICABLE
  correction_authorised: true | false | null
```

### Field semantics

- `variant_resolved`: exact Shopify variant/inventory item has already been resolved upstream.
- `job_state`: operational state of the stock event.
- `quantity_basis: PHYSICAL_COUNT`: `usable_quantity` is the verified total physical quantity that should exist now; propose `SET`.
- `quantity_basis: RECEIVED_INCREMENT`: `usable_quantity` is the newly received usable quantity to add to a valid current baseline; propose `ADD`.
- `quantity_basis: NONE`: no physical inventory mutation is requested.
- `usable_quantity`: physically usable Shopify selling units after supplier-pack to Shopify-sell-unit conversion. Ordered, damaged, missing, backordered, or unusable units are excluded.
- `current_available`: current Shopify available inventory when needed for the operation.
- `current_on_hand`: current Shopify on-hand value when supplied for context/audit.
- `location`: exact Shopify inventory location for any `SET` or `ADD` action.
- `sell_unit_conversion_status`: must be resolved (or explicitly not applicable) before changing quantities.
- `correction_authorised`: explicit approval required before correcting a negative/corrupt stock baseline via verified physical-count `SET`.

The decision engine accepts structured facts only. Free-form phrases such as "another 30" or "we counted about 20" should be interpreted upstream into this contract before the deterministic engine runs.

## Output contract

```yaml
status: READY | REVIEW_REQUIRED

inventory:
  current_available:
  current_on_hand:
  usable_quantity:
  operation: SET | ADD | NONE
  proposed_available:
  location:
  notes: []

missing_or_conflicting_fields: []
notes: []
```

`inventory` may be null for a review result when no safe partial action exists.

## Core rules

### ORDERED

A purchase order is not received inventory.

`job_state: ORDERED` normally returns:

```yaml
operation: NONE
```

Do not add supplier ordered quantities to Shopify inventory until physical receipt has been confirmed.

### Physical count → SET

A verified total physical count means the operator is stating what stock should exist now.

Example:

```yaml
quantity_basis: PHYSICAL_COUNT
usable_quantity: 30
```

returns:

```yaml
operation: SET
proposed_available: 30
```

An explicitly supplied physical count defaults to `SET`, not `ADD`.

### Received increment → ADD

A confirmed new receipt means the usable quantity is added to a valid current Shopify available baseline.

Example:

```yaml
current_available: 12
quantity_basis: RECEIVED_INCREMENT
usable_quantity: 30
```

returns:

```yaml
operation: ADD
proposed_available: 42
```

`RECEIVED_INCREMENT` requires `job_state: RECEIVED`.

### Usable received quantity

Use physically usable quantity, not supplier ordered quantity.

Short-supplied, damaged, dead, missing, substituted, rejected, or backordered units must not be included unless they are physically present, usable, and represent the same resolved Shopify selling unit.

Example:

```text
Ordered: 30
Received physically: 30
Unusable/damaged: 4
Usable quantity: 26
```

The deterministic input is:

```yaml
usable_quantity: 26
```

The engine does not calculate usable quantity from unstructured supplier narratives.

## Pair/trio/group selling units

Pair, trio, group, pack, or other multi-unit Shopify variants remain their own Shopify selling units.

Supplier-pack-to-Shopify-sell-unit conversion must be resolved upstream before this skill runs.

If the conversion is unresolved:

```text
REVIEW_REQUIRED
```

Do not assume individual physical animals/items equal Shopify retail units.

## Location gate

Any proposed `SET` or `ADD` requires an exact inventory location.

Missing location returns:

```text
REVIEW_REQUIRED
```

This prevents a correct quantity from being applied to the wrong Shopify location.

## Negative/corrupt inventory

Do not perform `ADD` against a negative/corrupt current baseline.

Where a verified physical count is available, a negative/corrupt quantity may be repaired with `SET` only when `correction_authorised: true`.

Without explicit authorisation:

```text
REVIEW_REQUIRED
```

The exception must be reported in the result notes.

## Inventory policy and preorder boundary

Physical inventory and customer availability are separate concerns.

This skill must never:

- change `inventoryPolicy` / continue-selling settings;
- infer preorder eligibility from zero or negative stock;
- decide whether a product should remain purchasable while out of stock.

Those responsibilities belong to `nta-product-availability` and relevant writer modules.

Zero stock means only that physical available inventory is zero.

## Review gates

Return `REVIEW_REQUIRED` when any material input is unresolved or unsafe, including:

- exact variant/inventory item not resolved;
- invalid or unknown job state;
- unclear quantity basis;
- usable physical quantity missing/invalid;
- exact Shopify location missing for `SET`/`ADD`;
- supplier-pack → Shopify-sell-unit conversion unresolved;
- `ADD` requested without a valid current available baseline;
- `ADD` requested against negative/corrupt current stock;
- negative/corrupt stock correction requested without explicit authorisation.

Do not replace these review gates with `HIGH`, `MEDIUM`, or `LOW` confidence labels.

## AI boundary

Target model usage:

```text
Known physical count → SET:             0 model calls
Known received increment → ADD:         0 model calls
ORDERED → NONE:                         0 model calls
Inventory arithmetic:                   0 model calls
Safety/review gates:                    0 model calls
Ambiguous free-form operator wording:   optional upstream interpretation only
```

If AI/human interpretation is needed upstream, convert the result into structured fields and rerun this deterministic module.

## Side-effect boundary

This skill performs:

```text
Shopify writes:       0
Network calls:        0
Inventory mutations:  0
Inventory-policy changes: 0
Model calls required by decision engine: 0
```

A separate Shopify writer may execute an approved `READY` action.

## Regression test

Run:

```bash
python3 scripts/dry_run.py
```

Regression coverage includes:

- physical-count `SET`;
- received-increment `ADD`;
- ordered stock `NONE`;
- short/damaged receipt using usable quantity;
- missing-location review gate;
- unresolved sell-unit conversion review gate;
- negative-stock correction blocked without authorisation;
- authorised negative-stock `SET` repair;
- zero Shopify writes, network calls, and model calls.

A successful run starts with:

```text
DRY_RUN_PASS: deterministic inventory state
```
