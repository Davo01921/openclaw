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

## Offline audit hardening — 2026-10-09

Catalogue call input hashes must equal the current source-photo hash. Mutation and readback inventory must be an integer 1 (booleans and floating values are rejected). Every protected readback field must be present, including nullable fields. State advancement validates the complete batch before saving; duplicate product/source/call evidence cannot bypass batch checks. The mutation envelope carries exact product_id, variant_id and location_id alongside the allowed changes.

These are local evidence gates. Runtime adapters remain responsible for actual fresh-read provenance, API errors, serialized writes, cross-batch duplicate detection, CSV evidence and persisted telemetry before PASS. Fixture success does not establish live acceptance or authorize deployment.

## Offline runtime hardening — 2026-10-09

`scripts/betta_runtime.py` implements the adapter duties above as deterministic code
over injected adapters:

- Writer responses are classified `APPLIED` / `REJECTED` / `UNCERTAIN`. Only an
  explicit success with no top-level or user errors is `APPLIED`; transport and
  server failures are `UNCERTAIN`; validation/authorisation failures are `REJECTED`.
- An `UNCERTAIN` result moves the item to `MUTATION_UNCERTAIN`, not to a retry. An
  independent read then either reconciles to `MUTATED` (confirmed applied), returns
  to `MUTATION_PENDING` only with explicit retry authority (confirmed not applied),
  or holds for review.
- A read-back must carry its own `fetch_id` and `fetched_at`, must not be derived
  from the writer response (`writer_response_used` must not be true), must use an
  identity distinct from the writer, and must be timestamped at or after the write
  completed.
- The inventory CSV must equal the live pre-write snapshot title/cost/price exactly,
  so CSV values can never authorise a price or cost change.
- `PASS` is blocked until the per-tank telemetry row is persisted.

The repository still contains no concrete Shopify/Discord adapter or single
end-to-end driver. See docs/RUNTIME_ADAPTER_STATUS_2026-10-09.md. Offline completion
is not production acceptance.
