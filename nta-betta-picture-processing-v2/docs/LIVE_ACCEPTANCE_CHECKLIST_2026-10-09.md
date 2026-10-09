# Betta V2.1 one-new-fish live acceptance checklist — 9 October 2026

Purpose: close V2.1 with one genuine newly received fish through the established
live path, with no invented fish, no paid test assets and no unauthorised writes.

Status: NOT EXECUTED. This is a prepared operator checklist only. Nothing in this
document authorises a live run. Execute only against a genuine fish with staff
authority and David present.

## Preconditions (confirm before starting)

1. A genuinely new fish exists, physically received, with its labelled source photo
   and an approved hero/source pair (or ability to generate one under the approved
   path). Do not simulate, recycle an old photo, or generate a paid test asset.
2. The exact Shopify tank product is identified; confirm the exact Product ID,
   Variant ID and Location ID. No product creation.
3. If the existing product's stock is `0`, obtain explicit new-fish intake authority
   from staff with the exact `source_reference` and the source SHA-256 bound to that
   authority. Stock may be 0 or 1 only; negative/multiple stock or an inactive
   product is an operator review hold.
4. Confirm no photo/text identity conflict (tank/title vs label). If present, resolve
   explicitly before any write.
5. Back up active ledgers, the telemetry SQLite database and approved assets.
6. Confirm adaptive-model-router availability, the fixed Grok hero service, and the
   concrete Shopify resolve/write/read-back adapter are reachable. If the adapter
   cannot be located, stop and report the missing adapter/configuration instead.
7. Confirm dry-run disabled only for this explicitly approved live test.

## Execution

1. Intake: save the original without overwrite; record thread/message/attachment
   IDs, path, MIME, byte size, SHA-256 and immutable `date_entered` (Australia/Sydney).
   Confirm `IntakeRegistry` accepts the source (no cross-batch duplicate).
2. Catalogue: resolve tank/date/name/tail/sex through the router; code assembles the
   deterministic title `<Tank> - <Fish Name> <Tail Type> <Male/Female>`. Send the
   mapping preview to David before writes.
3. Parallel preparation: run Shopify resolve and Grok hero; persist each branch as it
   completes. Resume must re-plan and run only missing work.
4. CSV: write `betta-inventory.csv` with the exact header and snapshot cost/price;
   validate tank-set equality.
5. Image QA: hero 2048x2048, hero first, complete uncropped byte-identical source
   second; all mandatory deterministic and visual assertions PASS.
6. Mutation: emit the envelope (title, arrival_date, inventory 1, hero+source);
   verify target identity and that no protected field is in the change set.
7. Read-back: fresh independent read (own fetch identity, timestamped after the
   write) confirming Product/Variant/Location identity, exact title, arrival date,
   inventory exactly 1, hero Image 1, byte-identical source Image 2, protected fields
   unchanged. The writer response is never accepted as proof.
8. If the mutation result is inconclusive: do NOT retry. Reconcile by independent
   read. Reconcile to MUTATED only if the change applied; return to MUTATION_PENDING
   only if definitely not applied and retry is explicitly authorised; otherwise hold.
9. Telemetry: persist one per-tank row, then advance to PASS. Telemetry must exist
   before PASS.
10. Archive: move sources/hero/CSV/ledger/telemetry export under the dated archive;
    verify hashes and tank-set equality; update ledger paths; advance to ARCHIVED.
11. Resume the same ledger once and confirm completed work is not repeated: no second
    mutation, no regeneration, `execution-plan` returns no work.

## PASS criteria (all required)

- Tank ID correct; final title exactly the deterministic format.
- Uncertain sex resolved to Male; Female only at >= 0.85 confidence.
- Exactly one existing product mapped, with exact variant/location.
- Hero Image 1; source Image 2 byte-identical.
- Inventory exactly 1; arrival date equals physical label.
- All protected fields unchanged (description, price, cost, vendor, product type,
  handle, status).
- Fresh independent read-back PASS; persisted telemetry row exists; onboarding
  seconds populated; Grok cost recorded from provider or the USD 0.07 fallback.
- Resume does not repeat completed work.

## On failure

Stop the batch. Record the failing stage and exact error. Do not expand to a larger
batch. Reconcile any uncertain Shopify state by read before any retry. Keep the
receipt (ledger, readback, telemetry, archive hashes) for review.

## Explicit non-actions

No product creation, no sold/zero-stock revival without source-linked authority, no
price/cost/description/handle/status change, no inventory batch reset, no paid test
generation, no secret retrieval, no deployment/merge.
