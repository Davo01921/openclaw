---
name: "nta-supplier-order-processing"
description: "Process NTA supplier orders and invoices as a specialist intake workflow that delegates product decisions to the canonical modular product system."
---

# NTA supplier order processing

Use when a supplier purchase order, invoice, screenshot, PDF, CSV, or Discord message needs to be reconciled against Shopify.

This is a specialist entry-point workflow. It does not own product-domain rules that now live in the modular product system.

## Canonical dependencies

Read and use `nta-product-orchestrator` first. Delegate each line to the applicable modules:

- `nta-product-resolver`
- `nta-product-classifier`
- `nta-supplier-unit-cost-normalizer`
- `nta-retail-pricing-standard` when a retail-price decision is needed
- `nta-inventory-state` when stock is physically received
- `nta-product-availability` when supplier availability/orderability changes
- `nta-product-metafields`
- `nta-product-exception-gate`
- `nta-shopify-write-verifier`

Do not copy or reinterpret those modules' rules here.

## Purpose

Turn supplier documents into structured supplier-line input and a verified product change set. This workflow owns supplier-document interpretation, order state, supplier-line semantics, idempotency and reconciliation reporting.

## Supplier intake responsibilities

For every supplier line extract where available:

```yaml
supplier_line:
  supplier:
  order_or_invoice_number:
  document_date:
  source_state: ORDERED | RECEIVED | RECEIVED_PARTIAL
  supplier_sku:
  supplier_description:
  order_qty:
  pack_or_combo_wording:
  line_cost:
  gst_evidence:
  supplier_availability:
  eta_evidence:
  received_qty_evidence:
  notes: []
```

Do not decide downstream product fields while parsing.

## Pack and combo intelligence

Preserve exact supplier wording for packs, cartons, trays, pairs, trios, assorted bundles, bonus quantities and free goods.

Examples that require explicit unit interpretation include `10 PACK`, `6PK`, `PAIR`, `TRIO`, `DOZEN`, `BOX`, `TRAY`, `CARTON`, `CASE`, `ASSORTED`, `BONUS`, and `12 + 2 FREE`.

Pass these facts to `nta-supplier-unit-cost-normalizer` and, for received stock, `nta-inventory-state`. Do not duplicate their unit-cost or inventory arithmetic here.

If an assorted line maps to multiple Shopify products without a verified split, require review rather than inventing allocation.

## ORDERED vs RECEIVED

A purchase order is not proof of physical stock.

- `ORDERED`: do not increase available Shopify inventory merely because goods were ordered.
- `RECEIVED`: inventory may be updated after exact identity and sell-unit conversion are resolved.
- `RECEIVED_PARTIAL`: use only physically confirmed usable quantities.

## Product matching

Use `nta-product-resolver`. SKU/barcode/supplier SKU evidence outranks title similarity. An unmatched supplier line is not automatic authority to create a new Shopify product.

## Cost and retail

Use `nta-supplier-unit-cost-normalizer` for GST and pack-to-unit cost conversion.

If supplier cost changed or a retail review is requested, pass normalized cost to `nta-retail-pricing-standard`. Do not change retail solely because cost changed.

## Supplier availability

Pass supplier availability evidence to `nta-product-availability` after `nta-product-classifier` resolves replenishable/one-off state.

Do not infer preorder status from inventory alone and do not invent an ETA from order date, invoice date, historical lead time, or guesswork.

## Idempotency

The same supplier order must not apply inventory twice.

Build a fingerprint from supplier + order/invoice number where available. If no stable document identifier exists, use supplier + document date + normalized line items + total.

A detected duplicate must route to `nta-product-exception-gate` as BLOCK for duplicate inventory application unless an explicit override is authorised.

## Discord intake

Treat one Discord thread/message group as one supplier-order job.

Recommended trigger:

`@FRED process supplier order`

Useful operator phrases:

- `ordered`
- `received`
- `received partial`
- `eta tbc`
- `normal preorder`
- `stop preorder`
- `dry run`

If physical state is unclear, default to `ORDERED` rather than falsely increasing inventory.

## Write and verification

All approved Shopify mutations must go through `nta-shopify-write-verifier`. The verifier invokes the writer and independent read-back auditor.

Do not report completion until live Shopify has been re-read and all intended changes pass QA.

## Output

Return a concise reconciliation report containing:

- supplier and order/invoice identifier;
- state: ORDERED / RECEIVED / RECEIVED_PARTIAL;
- detected GST evidence;
- lines parsed;
- exact/ambiguous/unmatched identity results;
- pack conversions delegated and resolved;
- cost changes;
- pricing decisions or review flags;
- inventory actions or inventory withheld because stock is not received;
- supplier availability interpretation;
- preorder/customer availability result;
- duplicate-order status;
- exception-gate result;
- Shopify write result;
- final QA result.

Never guess to make the report look complete.
