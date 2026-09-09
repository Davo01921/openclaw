---
name: "nta-inventory-effect-auditor"
version: "1.0"
description: "Deterministically verify that a Shopify order changed exact inventory quantities by the expected amount exactly once."
---

# NTA Inventory Effect Auditor — v1.0

## Purpose

Prove the post-write inventory effect for exact Shopify inventory levels using fresh before/after snapshots. This module audits only; it never adjusts inventory.

## Contract

```yaml
expected_net_loss_by_inventory_level:
  <inventory_level_id>: <positive integer>
before:
  <inventory_level_id>:
    source: FRESH_SHOPIFY_READ
    available: <integer>
    on_hand: <integer|null>
after:
  <inventory_level_id>:
    source: FRESH_SHOPIFY_READ
    available: <integer>
    on_hand: <integer|null>
```

For death-loss, the required available-stock delta is exactly `before.available - expected_loss`. No separate manual inventory mutation is permitted for the same event.

## Rules

- every expected inventory level must have fresh before and fresh after evidence;
- exact available delta must match once;
- unexpected inventory levels in the expected set are not ignored;
- on-hand is recorded for audit context when available, but the canonical loss assertion is the exact available delta unless Shopify semantics are explicitly changed upstream;
- comparator uses zero model calls, zero network calls and zero writes.

Run `python3 scripts/dry_run.py`.
