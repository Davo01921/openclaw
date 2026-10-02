# Shopify mutation contract

## Authorised fields

For one resolved individual-Betta Product ID, authorize only:

1. title = accepted photo-based proposed title;
2. `custom.arrival_date` = accepted physical photo date;
3. inventory = `1` at the resolved individual-fish location;
4. media = the exact image-QA-approved hero followed by the byte-identical complete original source.

## Protected fields

Require byte/value equality before and after for:

- complete product description;
- retail price;
- cost;
- vendor;
- product type;
- handle;
- status.

Do not treat a title change as authority to rewrite the description or merchandising fields. Do not treat CSV values as authority to change price or cost.

## Mutation gate

Before writing, require:

- exact Product ID resolution;
- complete pre-write snapshot;
- accepted proposed title and physical photo date;
- schema-valid image QA evidence tied to uploaded hashes;
- explicit field-level change set;
- no keys outside the authorised set;
- dry-run disabled only for a user-approved live test or batch.

After writing, query fresh live state and compare every authorised and protected field. Any transport error, top-level API error, material `userErrors`, missing read-back value, or mismatch results in `FIX_REQUIRED`.

## Closeout safety gates

Require a fresh exact variant and location, tracked DENY inventory and ACTIVE product. Stock may be 0 or 1; zero requires `intake.new_fish_authorised=true`, a genuine `source_reference` and the exact `source_sha256`. Negative/multiple stock is a review hold, never an automatic reset. Independent readback includes source=FRESH_SHOPIFY_READ, variant_id and location_id. Record and resolve conflicting staff/photo identity before writing. Product status stays protected; never auto-archive or revive a sold fish from an old photograph.
