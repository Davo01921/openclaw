# Batch state machine

Persist a machine-readable batch ledger. `scripts/betta_batch.py` is the authoritative validator and transition gate. Run `validate` after recording evidence and before every mutation or archive transition. Use `mutation-envelope` to emit the only permitted Shopify change set.

Recommended item states:

1. `DISCOVERED`
2. `SAVED`
3. `VISUAL_PENDING`
4. `VISUAL_ACCEPTED`
5. `BLOCKED_VISUAL`
6. `PRODUCT_RESOLVED`
7. `BLOCKED_PRODUCT`
8. `CSV_READY`
9. `IMAGE_CANDIDATE_READY`
10. `IMAGE_QA_PENDING`
11. `IMAGES_READY`
12. `MUTATION_PENDING`
13. `MUTATED`
14. `VERIFIED`
15. `PASS`
16. `FIX_REQUIRED`
17. `ARCHIVED`

Batch states:

- `ASSEMBLING`
- `READY_TO_PROCESS`
- `PROCESSING`
- `INCOMPLETE`
- `READY_TO_ARCHIVE`
- `DONE`

## Parallel preparation after visual acceptance

`VISUAL_ACCEPTED` is a fan-out checkpoint, not a serial queue.

As soon as tank/date/title components are accepted, the orchestrator may run these two independent operations concurrently:

- `shopify_resolve` — resolve the exact existing Shopify Product ID and save the full pre-write snapshot;
- `grok_hero` — generate and persist the versioned hero candidate and its usage/cost record.

Use:

```text
scripts/betta_batch.py execution-plan <ledger> --workers 4
```

and consume `parallel_preparation.tasks`. The value of `max_concurrency` is the total external-operation ceiling across both branches, not a per-branch limit.

Persist each successful branch immediately. Re-run `execution-plan` after completions or failures. A branch whose output is still valid MUST NOT be scheduled again. Therefore:

- Shopify success + Grok failure → retry only `grok_hero`;
- Grok success + Shopify failure → retry only `shopify_resolve`;
- both success → item appears in `ready_to_join` and may advance to `PRODUCT_RESOLVED`;
- neither success → both operations remain pending.

`PRODUCT_RESOLVED` is retained as the compatibility join state. The validator now requires both the exact Shopify snapshot and a hash-valid hero before allowing this transition.

## Transition rules

- Never move beyond `VISUAL_ACCEPTED` without accepted tank identity and the deterministic title contract.
- Never move to `PRODUCT_RESOLVED` until both parallel-preparation branches are valid.
- Never mutate Shopify before `PRODUCT_RESOLVED`, `CSV_READY`, and `IMAGES_READY`.
- `CSV_READY` requires cost and retail copied from the live pre-write snapshot; fixed recommendations are prohibited.
- `IMAGE_CANDIDATE_READY` requires source and hero hashes, a reference record with the identical source hash, plus renderer parameters.
- `IMAGES_READY` requires complete deterministic checks and one recorded source/hero/reference visual comparison with every mandatory assertion PASS.
- Missing QA, incomplete QA, zero visual comparison calls, or an unapproved candidate version forces `FIX_REQUIRED`.
- Never set `PASS` before image QA, fresh Shopify read-back, and the per-tank telemetry write succeed.
- The only authorised product changes are deterministic title, physical-photo arrival date, inventory `1`, and approved media/order.
- Description, price, cost, vendor, product type, handle, and status must match the pre-write snapshot.
- Never archive unless every fish is `PASS`.
- `FIX_REQUIRED` and `BLOCKED_*` are terminal for the current automated pass.
- Reruns continue from persisted evidence and hashes rather than restarting successful stages.

## Uncertain write hold

`MUTATION_UNCERTAIN` is a non-terminal hold, outside the linear chain, for an
inconclusive Shopify mutation result (transport error, timeout, server error or
ambiguous response). It is entered from `MUTATION_PENDING` only when the attempt is
recorded with a reason and an `UNCERTAIN` writer-result class.

- `MUTATION_UNCERTAIN -> MUTATED` is allowed only when an independent read confirms
  the intended change applied (`reconciliation.outcome == "APPLIED"`).
- `MUTATION_UNCERTAIN -> MUTATION_PENDING` is allowed only on a confirmed
  `NOT_APPLIED` read with `reconciliation.retry_authorised == true`.
- Any other result stays held for operator review (`UNRESOLVED`).
- `MUTATION_UNCERTAIN` is never scheduled by `execution-plan`; an uncertain write is
  never automatically retried. The `write.baseline` captured before the attempt is
  what allows a later read to distinguish applied from not-applied state.

## Mandatory image QA ledger shape

Each item must include:

```json
{
  "image_qa": {
    "source_sha256": "",
    "hero_sha256": "",
    "reference_sha256": "",
    "candidate_version": "",
    "deterministic": {
      "dimensions": "PASS",
      "filenames": "PASS",
      "label": "PASS",
      "framing": "PASS",
      "original_reference_hash": "PASS"
    },
    "visual": {
      "provider": "",
      "model": "",
      "call_id": "",
      "timestamp": "",
      "assertions": {},
      "overall": "PASS"
    },
    "outcome": "PASS"
  }
}
```

An absent/empty value is not PASS. Schema validation must fail closed.

## Suggested ledger fields

Retain identity, catalogue confidence, product evidence, paths, hashes, Shopify IDs, errors, cost telemetry, `date_entered`, and transition timestamps for each item. The transition history is also the timing source for per-Betta onboarding duration and slowest-state analysis.
