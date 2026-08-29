# Batch integrity

## Identity chain

Every Shopify write must be traceable through:

`Discord attachment → local source hash → physical tank/date → exact Shopify Product ID → uploaded/reused file → product media → fresh read-back`

A filename, handle, title, upload order, or visual resemblance alone is not sufficient to replace this chain.

## Handle anomalies

The Product ID is the primary Shopify identity. A handle mismatch is evidence to inspect, not permission to switch products.

If:
- tank ID matches one Product ID but handle looks stale;
- product title and physical label conflict;
- multiple products contain the tank token;

stop and diagnose before mutation.

## Batch set assertions

Before Shopify:
- accepted tank IDs are unique.
- accepted source hashes are unique unless the same attachment was intentionally duplicated and explicitly recorded.
- every accepted tank has exactly one source identity.

Before archive:
- CSV tank set equals PASS tank set.
- hero tank set equals PASS tank set.
- reference tank set equals PASS tank set.
- Shopify verified tank set equals PASS tank set.

Any set mismatch blocks archive.
