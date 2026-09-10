# NTA Gumtree Automation - SPECDOC

Status: Phase 0 specification locked for initial implementation
Version: 1.0-draft

## Objective

Build a deterministic Gumtree advertising control system for Nano Tanks Australia. Shopify expresses business intent, SQLite stores operational memory, Gumtree is observed real-world state, and Python reconciles desired state with actual state.

Normal routine operation should not require an LLM. AI may assist only with unresolved identity or optional language work, and may never bypass validation or authority gates.

## Hard safety invariants

1. If ALL NTA Gumtree Shopify metafields are blank/null, the product is UNCONFIGURED.
2. UNCONFIGURED products are REPORT_ONLY and MUST NOT be automatically listed, edited, adopted, paused, removed, relisted, or published.
3. Suggested policies for UNCONFIGURED products are informational only and grant no authority.
4. Discovery of an existing Gumtree listing does not grant management authority.
5. Publish and paid promotion are David-only actions in v1.
6. Active-listing modification, pause, removal, and relisting require review in v1.
7. Draft creation and draft correction may become automatic only after deterministic validation.
8. If identity, price, configuration, Gumtree state, or snapshot integrity is uncertain, preserve existing state and report the problem.
9. Browser automation executes a validated plan; it does not make business decisions.
10. Reconciliation must be idempotent.

## Shopify configuration state

- UNCONFIGURED: every Gumtree-specific Shopify field is blank/null.
- CONFIGURED: at least one Gumtree-specific field is populated and the effective configuration validates.
- EXCLUDED: explicit gumtree_policy = DO_NOT_LIST.
- CONFIG_ERROR: populated configuration is invalid or contradictory.

Preferred activation field: nta.gumtree_policy. Blank fields inherit only AFTER a product has passed the UNCONFIGURED gate.

## Shopify Gumtree fields

- nta.gumtree_policy
- nta.gumtree_priority
- nta.gumtree_min_stock
- nta.gumtree_stockout_policy
- nta.gumtree_stockout_grace_days
- nta.gumtree_price_override
- nta.gumtree_title_override
- nta.gumtree_description_override
- nta.gumtree_desired_listing_count
- nta.gumtree_campaign_start
- nta.gumtree_campaign_end

Policy values:
- DO_NOT_LIST
- ALWAYS_ON
- WHEN_IN_STOCK
- UNIQUE
- CAMPAIGN

Priority values:
- CORE_TRAFFIC
- HIGH
- NORMAL
- LOW

Stockout policy values:
- PAUSE
- KEEP_ACTIVE
- GRACE_PERIOD

## Configuration precedence

1. Advertisement-specific override
2. Shopify product override
3. Product-type configuration
4. System default

Null means inherit. Explicit values such as 0 are not equivalent to null.

System defaults must be conservative. A completely unconfigured product never reaches inheritance.

## Desired-state rules

ALWAYS_ON:
Maintain one valid advertising presence by default, subject to explicit stockout policy. Missing or expired presence requires restoration workflow, not blind duplicate posting.

WHEN_IN_STOCK:
Desired ACTIVE when inventory >= gumtree_min_stock; otherwise desired ABSENT.

UNIQUE:
Desired ACTIVE only while the exact item remains available. Once sold, its advertisement lineage must never be recreated merely because the old Gumtree listing is missing.

CAMPAIGN:
Desired ACTIVE only during configured campaign dates and while other eligibility conditions pass. Campaigns do not auto-extend.

DO_NOT_LIST:
Desired ABSENT. Unexpected existing listings are reported for review rather than automatically deleted.

## Gumtree actual states

- UNKNOWN
- MISSING
- DRAFT
- ACTIVE
- PAUSED
- EXPIRED
- SOLD
- REMOVED
- ERROR
- NEEDS_REVIEW

## Reconciliation outcomes

Every ad reconciliation returns exactly one primary action:

- NO_ACTION
- CREATE_DRAFT
- UPDATE_DRAFT
- UPDATE_ACTIVE_REVIEW
- RELIST_REVIEW
- PAUSE_REVIEW
- REMOVE_REVIEW
- DUPLICATE_REVIEW
- CONFIG_REVIEW
- IDENTITY_REVIEW
- ERROR

PUBLISH is deliberately not a reconciliation action in v1.

## Authority matrix v1

Automatic/read-only:
- read Shopify
- read Gumtree
- update registry from validated observations
- calculate desired/actual state
- generate reconciliation result
- generate listing plan
- validate listing plan
- identify/report duplicates and configuration issues

Potential automatic write after validation:
- create Gumtree draft
- update Gumtree draft
- save draft

Review required initially:
- update active listing
- pause active listing
- remove active listing
- relist expired listing

David only:
- publish new ad
- purchase paid Gumtree promotion/add-on

## Registry model

SQLite is the initial registry.

Core entities:
- products: cached Shopify identity/config state
- advertisements: stable NTA advertising concepts such as GT-NTA-000001
- product_ad_links: supports product, component, and future bundle relationships
- gumtree_instances: each real Gumtree listing instance and its historical status
- snapshots: time-series Gumtree observations/metrics
- actions: proposed/approved/executed action audit trail
- runs: reconciliation/census run health and provenance

One Shopify product may map to zero, one, or multiple NTA advertisements. One NTA advertisement may have multiple historical Gumtree instances across expiry/relisting.

Never store passwords, API keys, browser cookies, or secrets in the registry.

## Census/import

Before any Gumtree write automation, run a read-only census of existing NTA Gumtree ads.

Capture only fields actually exposed by Gumtree. Candidate fields include listing ID, title, price, status, URL, description, website URL, location, category, attributes, images, dates, views, favourites, and enquiries.

Matching evidence priority:
1. known Gumtree listing ID
2. stored relationship
3. exact Shopify product URL/handle
4. exact stable identifier/SKU when available
5. exact normalized title
6. deterministic similarity supported by other evidence
7. optional AI-assisted match
8. human review

Matching buckets:
- MATCHED
- LIKELY_MATCH
- UNMATCHED
- ORPHAN
- DUPLICATE_CANDIDATE

Price may support identity but must not establish identity by itself.

Existing Gumtree listing + all Shopify Gumtree fields blank remains UNCONFIGURED / REPORT_ONLY. Do not modify Shopify or Gumtree automatically.

Discovery lifecycle:
DISCOVERED -> IDENTIFIED -> MAPPED -> POLICY_CONFIGURED -> MANAGED

Only MANAGED advertisements may eventually receive automatic management actions.

## Reconciliation contract

Input is a frozen snapshot containing:
- run_id
- product facts
- resolved policy
- advertisement identity/history
- observed Gumtree state

The reconciliation engine itself performs no browsing and no Shopify/Gumtree writes.

Processing order:
1. configuration gate
2. data-integrity/identity gate
3. determine desired state
4. compare desired vs actual
5. calculate dirty fields
6. calculate authority/review requirements
7. emit deterministic decision record

Dirty dimensions:
- PRICE_DIRTY
- CONTENT_DIRTY
- IMAGE_DIRTY
- INVENTORY_DIRTY
- STATUS_DIRTY

A reconciliation result answers WHAT needs to happen. A listing plan separately specifies exactly WHAT DATA the browser would enter.

## Listing-plan execution gate

Every executable plan is either READY or BLOCKED.

Browser execution is forbidden unless plan_status == READY.

Blocking examples:
- missing/uncertain identity
- invalid price
- missing required image
- invalid Gumtree attributes
- unconfigured product
- suspected duplicate
- stale or anomalous source snapshot

Maximum v1 automated execution is SAVE_DRAFT. There should be no generic post/publish capability available to routine execution.

## Run-level safety

Before any write-capable run, validate:
- Shopify snapshot health
- Gumtree snapshot health
- configuration validity
- registry/database health

An anomalous Gumtree census must block writes. Example: a normal estate of ~40 listings suddenly returning zero must be treated as collector failure, not 40 missing advertisements.

Severity levels:
- INFO
- LOW
- MEDIUM
- HIGH
- CRITICAL

CORE_TRAFFIC missing presence is HIGH. An untrustworthy Gumtree account snapshot is CRITICAL and blocks writes.

## Unconfigured-product report

All products whose Gumtree Shopify fields are entirely blank must appear in a review report rather than being listed.

Useful report fields:
- Shopify product ID
- title
- product type/classification
- inventory
- current price
- configuration state = UNCONFIGURED
- deterministic suggested policy where available
- reason = all Gumtree metafields blank
- whether an existing Gumtree listing was discovered

Suggestion does not equal permission.

## First implementation milestone

Build a read-only Shopify configuration reader that:
1. reads product identity and Gumtree metafields
2. detects whether all Gumtree fields are blank
3. classifies each product as UNCONFIGURED, CONFIGURED, EXCLUDED, or CONFIG_ERROR
4. validates populated fields
5. produces the unconfigured/configuration review report

No Gumtree writes, no publication, and no LLM should be required for this milestone.
