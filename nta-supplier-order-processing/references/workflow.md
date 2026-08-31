# Supplier order workflow

## 1. Intake and fingerprint

Capture the Discord attachment(s), supplier name, order/invoice number, document date, totals, GST line, freight, and each product line.

Normalize the document and create a duplicate-detection fingerprint. A previously applied fingerprint must not apply inventory again without explicit override.

## 2. Determine document state

Classify the job as:

- `ORDERED`
- `RECEIVED`
- `PARTIAL_RECEIPT`
- `DRY_RUN`

A supplier purchase order or invoice on its own defaults to `ORDERED` unless the operator clearly says the goods have arrived/been received.

## 3. Parse every supplier line

Extract:

- raw supplier title
- supplier SKU/barcode when available
- supplier order quantity
- pack/unit wording
- detected pack size
- line subtotal
- unit price if printed
- discount/markdown if printed
- GST basis
- free/bonus units

Preserve the raw line beside the normalized interpretation so the decision can be audited.

## 4. Resolve pack semantics

Recognize patterns including:

- `N PACK`, `N-PACK`, `NPK`, `PACK OF N`
- `PAIR`, `2PK`
- `TRIO`, `3PK`
- `HALF DOZEN`, `DOZEN`
- `BOX`, `CASE`, `CARTON`, `TRAY`
- `ASSORTED`, `MIXED`
- `N + M FREE`, `BONUS`, `FOC`

Never use the pack number by itself to decide Shopify inventory. Compare the supplier pack to the matched Shopify variant's selling unit.

## 5. Match Shopify

Use `nta-product-resolver` as the canonical identity interface. The confidence labels below are supplier-intake evidence; Shopify write authority still requires the resolver's `RESOLVED` outcome.

For each line search Shopify using, in order:

1. supplier SKU / barcode mapped to Shopify SKU
2. exact normalized title + size + variant
3. exact scientific/common-name synonym where maintained
4. high-confidence fuzzy title candidate

Record confidence:

- `EXACT`
- `HIGH`
- `REVIEW`
- `UNMATCHED`

Only `EXACT` and sufficiently unambiguous `HIGH` matches may proceed to safe writes.

## 6. Convert quantity and cost

Calculate:

`base_units = supplier_order_qty × supplier_pack_size + free_units`

Then map to the Shopify selling unit.

Examples:

- supplier 10-pack × 2, Shopify sells each → 20 Shopify units
- supplier 10-pack × 2, Shopify sells 10-pack → 2 Shopify units
- supplier pair × 6, Shopify sells pair → 6 Shopify units
- supplier pair × 6, Shopify sells each → 12 Shopify units

For an assorted pack that maps to multiple Shopify products, stop the line at `REVIEW` unless an exact breakdown exists.

Cost must be converted to the same Shopify selling unit before comparison. Retain both supplier-pack cost and Shopify-unit cost in the audit report.

## 7. GST handling

Detect whether supplier line amounts are ex-GST or inc-GST using explicit document wording first, then reconcile subtotal + GST = total when available.

Do not infer GST from a single line if the document totals contradict it.

Store/compare Shopify cost on the NTA-standard cost basis. If conversion is required, show the calculation in the audit output.

## 8. Proposed Shopify changes

For each matched item build a proposed change set containing:

- product and variant IDs
- vendor: current → proposed
- cost: current → proposed
- retail: current → recommendation/proposed
- inventory: current → proposed or withheld
- quantity conversion explanation
- confidence level

Vendor and cost may be updated when the supplier identity and unit conversion are reliable.

Retail remains unchanged unless an explicit NTA pricing rule authorizes a change after margin/market review.

## 9. Inventory behavior

### ORDERED

Do not add available inventory. Record/report incoming quantity where supported by the implementation, and include it in the Discord report.

### RECEIVED

Use physically received quantities after pack conversion. Follow the NTA inventory skill's set-vs-add rules and location rules. Do not count unreceived/backordered units.

### PARTIAL_RECEIPT

Only process lines/quantities explicitly confirmed received. Keep the remainder outstanding.

## 10. Verification

Submit the approved change set through `nta-shopify-write-verifier`, which invokes the writer and independent fresh read-back auditor. Do not call supplier intake complete from a successful mutation response.

After writes, re-read every changed Shopify product/variant and verify:

- exact matched variant
- vendor
- cost
- retail if changed
- inventory if changed
- active/product integrity

A failed verification is not completion.

## 11. Discord report template

Use a compact format such as:

`Supplier order processed: Pisces`

`Lines: 8 | Exact: 7 | Review: 1 | Unmatched: 0`

`Pack conversions: 10-pack Crypt ×2 → 20 each`

`Cost changes: 3 | Vendor changes: 0 | Retail changes: 0 (2 recommendations)`

`Inventory: ORDERED — no available stock added`

`Duplicate check: passed`

`Shopify verification: passed`

Then list only exceptions/review items with enough detail for the operator to decide.
