---
name: "nta-dropship-order-processing"
version: "1.1"
description: "Detect NTA Shopify dropship lines, route them through supplier adapters, and safely write supplier state back to Shopify without duplicate orders."
---

# NTA Dropship Order Processing

## Scope

Own the order-level dropship workflow from Shopify detection through supplier hand-off and acknowledgement. This module does not own product pricing, inventory policy, fulfilment completion, or supplier-specific transport details.

## Authoritative Shopify fields

### Product metafields
- `custom.dropship` — boolean. Only `true` qualifies a product for dropship processing.
- `custom.dropship_supplier` — single-line text. Supplier routing key. Current Aqua Premium-routed products use `Aqua Premium`.

### Order metafields
- `custom.dropship_status` — workflow state.
- `custom.supplier_order_number` — supplier acknowledgement/order number.

### Order tag
- `NTA-DROPSHIP-AQUA-PREMIUM` for any order containing at least one line routed to Aqua Premium.

## Trigger contract

Preferred trigger: Shopify order-created/order-paid event through the NTA orchestrator. Reprocessing is allowed only when the existing dropship status and idempotency record show that no successful supplier hand-off has occurred.

## Procedure

1. Read the live Shopify order and all line items.
2. For each line item, resolve the exact Shopify product/variant and read `custom.dropship` and `custom.dropship_supplier` from the live product state. Do not infer dropship status from vendor alone.
3. Keep only lines where `custom.dropship == true`.
4. Group qualifying lines by `custom.dropship_supplier`.
5. Resolve the exact sellable variant with `nta-product-resolver`. Prefer supplier SKU when available. If supplier SKU is absent, preserve Shopify product title, variant title, quantity, Shopify variant ID and Shopify order ID in the hand-off payload and flag `SUPPLIER_SKU_MISSING`.
6. Build the idempotency key from Shopify order ID + supplier + sorted qualifying Shopify line item IDs. Never resend when a successful hand-off exists for that key.
7. Before external submission, write through `nta-shopify-write-verifier`:
   - `custom.dropship_status = READY_FOR_HANDOFF`
   - supplier-specific order tag.
8. Dispatch the grouped payload to the supplier adapter named by `custom.dropship_supplier`. For `Aqua Premium`, use `nta-dropship-supplier-aqua-premium`.
9. If the supplier request is successfully sent, write `custom.dropship_status = SENT_TO_SUPPLIER`.
10. When a supplier order number/acknowledgement is received, validate that it maps to the same Shopify order and supplier, then write through `nta-shopify-write-verifier`:
   - `custom.supplier_order_number = <supplier reference>`
   - `custom.dropship_status = SUPPLIER_ACKNOWLEDGED`
   - add a human-readable Shopify order note/comment equivalent: `Dropship ordered from <supplier> — supplier order <reference>` when the configured Shopify writer supports it without overwriting unrelated notes.
11. Supplier acknowledgement is not customer fulfilment. Do not mark the Shopify order fulfilled here.

## Aqua Premium payload contract

```yaml
supplier_request:
  supplier: Aqua Premium
  shopify_order_id:
  shopify_order_name:
  idempotency_key:
  ship_to:
    name:
    company:
    address1:
    address2:
    city:
    province:
    postcode:
    country:
    phone:
  lines:
    - shopify_line_item_id:
      shopify_product_id:
      shopify_variant_id:
      supplier_sku:
      title:
      variant_title:
      quantity:
  notes: "NTA dropship for Shopify order <order name>"
```

Only send customer delivery details required to fulfil the order. Do not send unrelated customer data.

## Statuses

`NO_ELIGIBLE_LINES`, `READY_FOR_HANDOFF`, `SENT_TO_SUPPLIER`, `SUPPLIER_ACKNOWLEDGED`, `REVIEW_REQUIRED`, or `BLOCKED`.

Use `REVIEW_REQUIRED` for ambiguous product/variant mapping, conflicting supplier routing, or a supplier acknowledgement that cannot be matched confidently. Use `BLOCKED` when a required adapter or write-verification step is unavailable.

## Failure and retry rules

- Never interpret an HTTP timeout, email transport ambiguity, or portal error as permission to resend.
- After an ambiguous external result, check supplier-side evidence before retrying.
- A successful supplier request must be recorded before any retry path is eligible.
- Never overwrite an existing different `custom.supplier_order_number`; conflicting references require review.

## Output

Return the Shopify order, qualifying lines, supplier groups, idempotency key, supplier payload, external hand-off evidence, Shopify write-verification result, warnings, and final workflow status.