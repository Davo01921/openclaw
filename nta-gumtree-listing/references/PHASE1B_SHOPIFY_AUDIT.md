# Phase 1B - Shopify Gumtree Configuration Audit

Date: 2026-09-10
Branch: gumtree-phase1a
Mode: READ ONLY

## Result

Shopify catalogue size: 2,267 products.

Classification:
- UNCONFIGURED: 2,267
- CONFIGURED: 0
- EXCLUDED: 0
- CONFIG_ERROR: 0

No Shopify or Gumtree listing values were changed during this audit.

## Evidence

A Shopify Admin GraphQL bulk operation queried all products and requested only these child metafields:

- nta.gumtree_enabled
- nta.gumtree_policy
- nta.gumtree_priority
- nta.gumtree_min_stock
- nta.gumtree_stockout_policy
- nta.gumtree_stockout_grace_days
- nta.gumtree_price_override
- nta.gumtree_title_override
- nta.gumtree_description_override

Bulk operation ID:
`gid://shopify/BulkOperation/4063408750801`

Shopify reported:
- status: COMPLETED
- errorCode: null
- rootObjectCount: 2267
- objectCount: 2267

The bulk query contains product root objects and the requested metafield child objects. Because total objectCount equals rootObjectCount exactly, no requested Gumtree metafield child objects were returned for any product.

As a cross-check, 200 products were also read directly in four 50-product pages. All 200 returned an empty metafield node set for the same Gumtree keys.

## Safety conclusion

Under the Phase 1 policy, blank Gumtree configuration means UNCONFIGURED and grants no authority to create or maintain a Gumtree listing automatically.

Therefore, as of this audit, no product in the NTA Shopify catalogue is authorized for automatic Gumtree listing activity.

This includes products that appear commercially suitable, such as Live Blackworms, Red Cherry Shrimp, Endlers and other livestock. Suitability must never override explicit Shopify configuration.

## Data-quality observations

The direct sample also confirmed cases the later eligibility engine must handle conservatively:

- some active products have negative inventory quantities;
- some products do not track inventory;
- at least one active livestock product had a zero price.

These conditions must not be resolved by AI guesswork. They should produce deterministic policy handling or NEEDS_REVIEW.

## Next phase gate

Before any Gumtree draft creation can occur, Phase 1C should establish the metafield definitions and configure a small representative test set explicitly. The remainder of the catalogue should remain UNCONFIGURED by default.
