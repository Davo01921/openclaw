---
name: "nta-shopify-fulfilment-auditor"
version: "1.0"
description: "Canonical deterministic auditor for fresh Shopify fulfilment read-back."
---

# NTA Shopify Fulfilment Auditor — v1.0

## Purpose

Compare caller-supplied expected fulfilment state with a fresh independently-read Shopify fulfilment snapshot. Never use the writer response as audit evidence.

## Required evidence

```yaml
expected:
  order_id:
  notify_customer: false
  fulfilled_lines:
    - fulfilment_order_line_item_id:
      quantity:
actual:
  source: FRESH_SHOPIFY_READ
  order_id:
  status:
  fulfilled_lines: []
```

## Rules

- exact order identity must match;
- exact fulfilled line IDs and quantities must match;
- actual source must be `FRESH_SHOPIFY_READ`;
- missing, duplicated, or extra material lines fail;
- normal comparison uses zero model calls, zero network calls and zero writes.

Run `python3 scripts/dry_run.py`.
