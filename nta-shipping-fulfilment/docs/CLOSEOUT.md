# Shipping Fulfilment V2 closeout — 2026-10-02

Status: READY FOR FINAL LIVE ACCEPTANCE. PR #17 is completed engineering work; production shipment acceptance remains explicit.

## Purpose and final architecture
Validate authorized dispatch events and fulfil exact Shopify lines without a separate stock adjustment or unsolicited customer notification. Exact Order, FulfillmentOrder and FulfillmentOrderLineItem GIDs are mandatory. No title/SKU guessing.

Python event validation → canonical verifier fulfilment_handoff with fresh exact order/remaining lines → guarded canonical writer → independent fresh-read auditor. Tracking company/number now survive every boundary and reach fulfillmentCreate.trackingInfo. The auditor requires successful fulfilment state and exact tracking/quantities; OPEN is not success.

shipment_boundary.execute_shipment composes those gates with the existing authenticated writer and independent reader callbacks. shipment_ledger uses SQLite atomic primary-key claims, stores intent before the writer, stores its receipt before auditing, and marks VERIFIED only after independent PASS. Concurrent claims and process restart cannot authorize a second attempt. Timeout or failed audit remains INDETERMINATE for reconciliation. The key excludes delivery ID and shipment timestamp, so redelivery/reformatting cannot create a new shipment identity.

## Evidence
13 regression tests cover complete handoff, tracking mismatch, wrong order, exhausted lines, malformed input, duplicate groups, timestamp identity, failed/indeterminate writes, concurrent claims, restart and duplicate receipt. Existing shipping, verifier, writer, API adapter, auditor and effect dry-runs pass. Shared Death Loss regressions remain green. A read-only production adapter capability probe and current order snapshot are retained in the central evidence folder; neither establishes a successful V2 write.

## Deployment state and one acceptance action
This source is canonical; do not infer that an old Fred checkout or dirty runtime mirror has the new boundary. No real order was fulfilled during closeout. No customer notification was sent.

For the next genuinely dispatched shipment, have the established fulfillment operator execute one exact authorized event through execute_shipment with a persistent private SQLite ledger, the existing create_fulfilment adapter, and a separate fresh Shopify reader that normalizes actual quantities and tracking. Set notify_customer=false for this acceptance. Retain the event, before/readback, writer receipt and PASS audit. Redeliver the same event after restarting the process: require DUPLICATE_NOOP, the same fulfillment ID and no second Shopify fulfillment. This single operator shipment exercise is the remaining acceptance; do not create a dummy production order.

## Operation and recovery
Archive ledger receipts securely; keep the ledger on persistent disk and back it up with SQLite's backup API. Never delete or restore the ledger blindly: a remote fulfillment can outlive a failed local run. Reconcile INDETERMINATE against the exact order, lines and tracking before any explicitly authorized retry. No automatic mutation retry is supplied. Stop write-enable and restore the prior source revision to roll back code while retaining the current ledger. Shopify fulfillments require business-controlled correction, not automatic deletion.

## Limitations/backlog
The runtime must supply authenticated callbacks and fresh normalization. Carrier selection, label buying, notifications and unrelated order orchestration are outside this skill. Optional carrier URLs and richer reporting are deferred.
