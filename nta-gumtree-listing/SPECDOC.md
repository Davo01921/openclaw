# NTA Gumtree Listing - SPECDOC

Status: CLOSED / BAU — production manual-post workflow; see [closeout](docs/CLOSEOUT.md).
Version: 1.1

## Objective

Provide a deterministic Gumtree advertising control system for Nano Tanks Australia in which Shopify expresses current business intent, SQLite stores operational memory, Python decides eligibility and prepares complete posting packages, and David performs all Gumtree account interaction manually.

Routine queue preparation requires no LLM. AI may assist with optional wording only after the deterministic facts are established and may never bypass validation or authority gates.

## Production architecture

```text
Current Shopify data
  -> configuration + availability resolution
  -> registry identity/state
  -> deterministic reconciliation
  -> listing-plan validation
  -> live Sydney-date operator queue
  -> David manually posts on Gumtree
  -> operator supplies Gumtree ID/URL
  -> registry POSTED record
  -> explicit verification
  -> VERIFIED
```

There is no production Gumtree browser writer.

## Hard safety invariants

1. Unconfigured products are report-only and cannot enter the operator queue.
2. `nta.gumtree_availability_override` is supplemental and alone never grants listing authority.
3. Uncertain availability never becomes permission to create a listing.
4. Discovery of an existing Gumtree listing does not grant management authority.
5. Only `MAPPED` or `MANAGED` identities may enter the operator queue.
6. Gumtree posting, editing, pausing, removal, relisting and paid promotion are manual unless Gumtree explicitly approves an integration for the account/workflow.
7. `publish_authority` is always `false` in this version.
8. `browser_automation` is always `false` in this version.
9. Live queue generation uses the current `Australia/Sydney` date and exposes no caller-supplied date override.
10. Live queue days are Thursday, Friday and Saturday only; Sunday-Wednesday return zero items.
11. Maximum queue size is three items per live day.
12. Missing price, description, image, identity, mapping, configuration or trustworthy source data fails closed.
13. A Gumtree listing ID already mapped to one NTA ad cannot be silently remapped to another ad.
14. Operator-supplied existing/listed ads record provenance `MANUAL_OPERATOR`.
15. Reconciliation and queue generation are deterministic and idempotent for the same frozen inputs.
16. Runtime SQLite databases, queue artifacts and backups are local state and must not be committed.

## Shopify Gumtree metafields

The supported fields are:

- `nta.gumtree_policy`
- `nta.gumtree_priority`
- `nta.gumtree_min_stock`
- `nta.gumtree_stockout_policy`
- `nta.gumtree_stockout_grace_days`
- `nta.gumtree_price_override`
- `nta.gumtree_title_override`
- `nta.gumtree_description_override`
- `nta.gumtree_desired_listing_count`
- `nta.gumtree_campaign_start`
- `nta.gumtree_campaign_end`
- `nta.gumtree_availability_override`

Policy values: `DO_NOT_LIST`, `ALWAYS_ON`, `WHEN_IN_STOCK`, `UNIQUE`, `CAMPAIGN`.

Priority values: `CORE_TRAFFIC`, `HIGH`, `NORMAL`, `LOW`.

Stockout values: `PAUSE`, `KEEP_ACTIVE`, `GRACE_PERIOD`.

Availability override values: `AVAILABLE`, `UNAVAILABLE`. A populated override does not activate Gumtree management by itself.

## Configuration states

- `UNCONFIGURED`: activation fields are blank. Availability override alone remains UNCONFIGURED.
- `CONFIGURED`: Gumtree configuration is present and validates.
- `EXCLUDED`: explicit `gumtree_policy = DO_NOT_LIST`.
- `CONFIG_ERROR`: populated configuration is invalid or contradictory.

Null means inherit only after the product passes the unconfigured gate. Explicit values such as `0` are not null.

## Availability

Availability statuses are `AVAILABLE`, `UNAVAILABLE`, `UNKNOWN`, `NOT_APPLICABLE`.

Rules are deterministic. For stock-dependent policies, missing/untracked inventory becomes `UNKNOWN` unless an authorised deterministic exception applies. UNIQUE Betta handling requires Shopify product type to identify Betta plus a valid NTA `BT` identifier and positive quantity.

## Registry

SQLite is the operational registry. Core entities are:

- products
- advertisements
- product_ad_links
- gumtree_instances
- snapshots
- actions
- runs

Registry schema v2 adds `gumtree_instances.source` and protects Gumtree listing IDs from cross-ad remapping.

Allowed instance provenance values are `UNKNOWN`, `MANUAL_OPERATOR`, `APPROVED_IMPORT`, and `VERIFIED_OBSERVATION`.

Passwords, API keys, browser cookies and secrets must never be stored in the registry.

## Reconciliation outcomes

The deterministic reconciliation engine emits one primary action:

- `NO_ACTION`
- `CREATE_DRAFT`
- `UPDATE_DRAFT`
- `UPDATE_ACTIVE_REVIEW`
- `RELIST_REVIEW`
- `PAUSE_REVIEW`
- `REMOVE_REVIEW`
- `DUPLICATE_REVIEW`
- `CONFIG_REVIEW`
- `IDENTITY_REVIEW`
- `ERROR`

`PUBLISH` is not a reconciliation action.

For the production manual-post workflow, `CREATE_DRAFT` and `UPDATE_DRAFT` mean "prepare a complete operator posting package"; they do not authorize automated Gumtree interaction.

## Listing plan

A queue candidate must produce a `READY` listing plan containing:

- stable NTA `ad_id`
- Shopify product ID
- title
- description
- valid positive price
- category
- location
- at least one valid image URL
- source fingerprint
- truthful attributes when required

Identity uncertainty, duplicate suspicion, stale/anomalous snapshots or missing required fields block the plan.

## Production queue runner

`gumtree_queue_runner.py` is the production entry point. It:

1. consumes current normalized Shopify product records supplied through an approved/read-only Shopify adapter boundary;
2. classifies configuration;
3. resolves availability;
4. refreshes cached product facts without escalating management authority;
5. resolves registry product/ad identity;
6. derives current recorded Gumtree state without live Gumtree scraping;
7. builds listing input and source fingerprint;
8. calls `build_live_operator_queue(...)`;
9. optionally writes the queue artifact to local disk.

The runner does not contact Gumtree.

Default operational invocation:

```bash
PYTHONPATH=scripts python3 scripts/gumtree_queue_runner.py \
  --input data/current-shopify-products.json \
  --db data/gumtree.db \
  --output data/operator-queue.json
```

## Operator lifecycle

`READY_TO_POST` -> `POSTED` -> `VERIFIED`

- `READY_TO_POST`: validated posting package exists.
- `POSTED`: David has manually posted and supplied a valid Gumtree listing ID or URL; registry source is `MANUAL_OPERATOR`.
- `VERIFIED`: verification explicitly succeeded.

The system must not infer `POSTED` or `VERIFIED` merely from elapsed time or a planned action.

## Existing listing bootstrap

`gumtree_manual_bootstrap.py` accepts an operator-supplied Gumtree listing ID or URL only. It performs no network access or identity guessing. The target NTA advertisement must already exist. Cross-ad listing-ID collisions are rejected.

## Runtime data and backup

`data/.gitignore` excludes SQLite files, queue artifacts and backup directories.

Before registry maintenance, create a consistent SQLite backup with:

```bash
PYTHONPATH=scripts python3 scripts/gumtree_registry_backup.py \
  --db data/gumtree.db \
  --backup-dir data/backups
```

## Definition of complete

The v1.1 skill is complete when all of the following are true:

- Shopify reader exposes all 12 Gumtree metafields;
- configuration and availability safety invariants are tested;
- registry schema v2 is migration-safe and rejects listing-ID remaps;
- manual bootstrap records provenance;
- production runner creates a max-3 Sydney-date Thu/Fri/Sat queue and zero items on blocked days;
- required listing data fails closed;
- manual post and verification lifecycle is tested;
- runtime DB/queue files are ignored and backup utility is tested;
- SKILL.md reflects manual Gumtree interaction only;
- CI passes the full Gumtree test suite.
