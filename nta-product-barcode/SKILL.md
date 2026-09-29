---
name: "nta-product-barcode"
version: "1.0"
description: "Deterministically preserve or create an internal NTA Shopify variant barcode for label workflows, collision-check it, and require fresh Shopify verification before printing."
---

# NTA Product Barcode — v1.0

## Purpose

Ensure a resolved Shopify variant has a scan-ready barcode before an NTA DYMO
product label is physically printed.

This skill owns barcode policy only. It does not print labels and it does not
directly mutate Shopify. Shopify writes remain behind
`nta-shopify-write-verifier`.

## Standing NTA policy

For a DYMO label workflow in write mode:

- if the resolved Shopify variant already has a non-empty barcode, preserve it;
- if the barcode is null or blank, automatically create the deterministic
  internal barcode `NTA-V-<legacyResourceId>`;
- collision-check that candidate before writing;
- write only the exact resolved variant's `barcode` field through
  `nta-shopify-write-verifier`;
- fresh-read Shopify after the write and require the live barcode to match;
- only after verification may the physical DYMO print proceed.

Never overwrite a non-empty barcode automatically.

## Identifier boundary

The generated `NTA-V-...` value is an **internal NTA scan identifier** encoded
on the DYMO label as Code 128-B. It is not a GS1-issued GTIN, UPC, EAN, ISBN or
MPN and MUST NOT be represented to Google Merchant Center or any external
channel as one of those identifiers.

The deterministic format is based on Shopify's unique variant numeric resource
ID, so repeated runs for the same variant produce the same proposed barcode.

## Deterministic policy code

Use `scripts/barcode_policy.py`.

Input:

~~~yaml
barcode_request:
  variant_id: gid://shopify/ProductVariant/123456789
  legacy_resource_id: 123456789
  current_shopify_barcode: null
  mode: dry_run | write
  label_requested: true
~~~

Important: `current_shopify_barcode` must come from a fresh Shopify read. Its
presence in the input is required even when its value is null.

Policy result:

~~~yaml
status: READY
action: KEEP_EXISTING | CREATE_INTERNAL
barcode: NTA-V-123456789
barcode_source: existing_shopify | generated_internal
requires_shopify_write: true | false
collision_query: barcode:NTA-V-123456789
~~~

## Concrete Shopify adapter

Use `scripts/shopify_adapter.py` when Fred has an authenticated Shopify Admin
GraphQL transport. `ShopifyBarcodeGateway.ensure_verified_barcode(...)` performs
the live read → deterministic plan → collision check → single authorised write →
fresh read-back → second collision check sequence. The transport is injected;
the code contains no credentials and write execution is disabled unless the
caller explicitly enables write mode.

Only a final `status: VERIFIED` result may be passed to the physical-print step.

## Write-mode procedure

1. Resolve the exact product and variant.
2. Fresh-read the variant's current `barcode` and `legacyResourceId`.
3. Run the deterministic policy.
4. If `KEEP_EXISTING`, preserve the live value and proceed.
5. If `CREATE_INTERNAL`, query Shopify variants using the returned
   `collision_query`.
6. Any match belonging to a different variant is `REVIEW_REQUIRED`; do not
   generate random alternatives and do not print.
7. If collision-free, route the exact variant barcode change through
   `nta-shopify-write-verifier`.
8. Fresh-read `productVariant(id) { id barcode }` independently from the
   mutation response and require exact equality.
9. Fresh-search the barcode again; a different variant using the same value
   blocks printing.
10. Pass the verified live barcode to `nta-dymo-tank-label`.

A mutation response alone is not verification.

## Dry-run procedure

A dry run may deterministically propose the barcode and include it in a preview,
but it MUST NOT mutate Shopify and MUST NOT physically print a label carrying a
newly generated barcode.

## Validated Shopify GraphQL shapes

These operations were validated against the current Shopify Admin GraphQL
schema. The caller still uses the normal Shopify connector/write-verifier
boundary.

Read:

~~~graphql
query ReadVariantBarcode($id: ID!) {
  productVariant(id: $id) {
    id
    legacyResourceId
    barcode
    product { id }
  }
}
~~~

Collision check:

~~~graphql
query FindBarcodeCollision($query: String!) {
  productVariants(first: 5, query: $query) {
    nodes {
      id
      barcode
      product { id }
    }
  }
}
~~~

Write:

~~~graphql
mutation WriteVariantBarcode($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    productVariants {
      id
      barcode
    }
    userErrors {
      field
      message
    }
  }
}
~~~

For the write, the variants payload is exactly:

~~~json
[
  {
    "id": "gid://shopify/ProductVariant/123456789",
    "barcode": "NTA-V-123456789"
  }
]
~~~

## Failure rules

Return `REVIEW_REQUIRED` and do not print when:

- exact variant identity is unresolved;
- fresh current-barcode state is unavailable;
- the existing non-empty barcode is malformed for the DYMO Code 128 path;
- the generated candidate collides with another variant;
- Shopify rejects the barcode write;
- fresh read-back does not exactly match the expected barcode;
- fresh uniqueness verification finds a different variant using the value.

Do not silently replace an existing barcode and do not invent a retail-standard
identifier.
