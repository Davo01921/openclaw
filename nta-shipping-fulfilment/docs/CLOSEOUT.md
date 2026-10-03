# Shipping Fulfilment V2 closeout — 2026-10-03

Status: CLOSED / BAU. PR #17 and the executable runner are the completed canonical implementation.

## Closure decision
On 3 October 2026 the owner accepted Shipping Fulfilment V2 for closure based on the completed deterministic architecture, regression coverage, read-only production adapter evidence and documented recovery controls. The previously planned genuine-dispatch restart/replay exercise was explicitly waived as a project-closure blocker. It remains a recommended BAU confidence exercise when a suitable real dispatch occurs; it must not be represented as having already happened.

## Purpose and final architecture
Validate authorized dispatch events and fulfil exact Shopify lines without a separate stock adjustment or unsolicited customer notification. Exact Order, FulfillmentOrder and FulfillmentOrderLineItem GIDs are mandatory. No title/SKU guessing.

Python event validation → canonical verifier fulfilment_handoff with fresh exact order/remaining lines → guarded canonical writer → independent fresh-read auditor. Tracking company/number now survive every boundary and reach fulfillmentCreate.trackingInfo. The auditor requires successful fulfilment state and exact tracking/quantities; OPEN is not success.

shipment_boundary.execute_shipment composes those gates with the existing authenticated writer and independent reader callbacks. shipment_ledger uses SQLite atomic primary-key claims, stores intent before the writer, stores its receipt before auditing, and marks VERIFIED only after independent PASS. Concurrent claims and process restart cannot authorize a second attempt. Timeout or failed audit remains INDETERMINATE for reconciliation. The key excludes delivery ID and shipment timestamp, so redelivery/reformatting cannot create a new shipment identity.

## Evidence
17 regression tests cover complete handoff, tracking mismatch, wrong order, exhausted lines, malformed input, duplicate groups, timestamp identity, failed/indeterminate writes, concurrent claims, restart and duplicate receipt. Existing shipping, verifier, writer, API adapter, auditor and effect dry-runs pass. Shared Death Loss regressions remain green. A read-only production adapter capability probe and exact #17111 snapshot (one fulfillment-order connection, two historical fulfillments, complete pagination) are retained in the central evidence folder; neither establishes a successful V2 write.

## Deployment state and BAU confidence exercise
This source is canonical; do not infer that an old Fred checkout or dirty runtime mirror has the new boundary. No real order was fulfilled during the engineering closeout review and no customer notification was sent.

When a suitable genuine dispatch occurs, the established fulfillment operator may run one exact authorized event through scripts/run_shipment.py with the persistent private SQLite ledger as a BAU confidence exercise. The desired sequence is READY preflight → VERIFIED first execute with independent PASS readback → process restart → DUPLICATE_NOOP replay with the same fulfillment ID and no second Shopify fulfillment. This is recommended operational evidence, not unfinished v2 engineering and not a prerequisite to CLOSED / BAU status.

## Operation and recovery
Archive ledger receipts securely; keep the ledger on persistent disk and back it up with SQLite's backup API. Never delete or restore the ledger blindly: a remote fulfillment can outlive a failed local run. Reconcile INDETERMINATE against the exact order, lines and tracking before any explicitly authorized retry. No automatic mutation retry is supplied. Stop write-enable and restore the prior source revision to roll back code while retaining the current ledger. Shopify fulfillments require business-controlled correction, not automatic deletion.

## Limitations/backlog
The included run_shipment.py supplies the existing authenticated adapter and independent before/after normalization; it refuses truncated reads, wrong created fulfillment IDs, extra lines and incorrect remaining-quantity effects. Carrier selection, label buying, notifications and unrelated order orchestration are outside this skill. Optional carrier URLs and richer reporting are deferred.

## Optional BAU operator command

From the canonical repository root, place the genuinely dispatched event in the private event file (exact GIDs and quantities; explicit source carrier/tracking; notify_customer=false). Run read-only first, then the existing write-enabled acceptance and repeat the same execute command after process restart:

```sh
NTA_SHOPIFY_SESSION_BRIDGE_NODE=/Users/davidlo/.nvm/versions/node/v24.20.0/bin/node python3 -B nta-shipping-fulfilment/scripts/run_shipment.py --env-file /Users/davidlo/.openclaw/workspace/nta-betta-picture-processor/.env --event /Users/davidlo/.openclaw/workspace/fred/state/shipping-acceptance.json --ledger /Users/davidlo/.openclaw/workspace/fred/state/shipping-fulfilment.sqlite
NTA_SHOPIFY_SESSION_BRIDGE_NODE=/Users/davidlo/.nvm/versions/node/v24.20.0/bin/node NTA_SHOPIFY_FULFILMENT_WRITE_ENABLED=true python3 -B nta-shipping-fulfilment/scripts/run_shipment.py --env-file /Users/davidlo/.openclaw/workspace/nta-betta-picture-processor/.env --event /Users/davidlo/.openclaw/workspace/fred/state/shipping-acceptance.json --ledger /Users/davidlo/.openclaw/workspace/fred/state/shipping-fulfilment.sqlite --execute
```

Expected: READY preflight, VERIFIED first execute with stored independent readback/PASS receipt, DUPLICATE_NOOP replay. Never execute a fixture or already-dispatched ambiguity without the operator's exact source authority.
