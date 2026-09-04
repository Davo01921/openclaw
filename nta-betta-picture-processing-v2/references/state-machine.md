# Batch state machine

Persist a machine-readable batch ledger. Recommended item states:

`scripts/betta_batch.py` is the authoritative validator and transition gate. Run `validate` after recording evidence and before every mutation or archive transition. Use `mutation-envelope` to emit the only permitted Shopify change set.

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
12. `FILES_READY`
13. `MUTATION_PENDING`
14. `MUTATED`
15. `VERIFIED`
16. `PASS`
17. `FIX_REQUIRED`
18. `ARCHIVED`

Batch states:

- `ASSEMBLING`
- `READY_TO_PROCESS`
- `PROCESSING`
- `INCOMPLETE`
- `READY_TO_ARCHIVE`
- `DONE`

## Transition rules

- Never move to `PRODUCT_RESOLVED` without accepted tank identity.
- Never mutate Shopify before `PRODUCT_RESOLVED`, `CSV_READY`, and `IMAGES_READY`.
- `CSV_READY` requires cost and retail copied from the live pre-write snapshot; fixed recommendations are prohibited.
- `IMAGE_CANDIDATE_READY` requires source, hero, and reference hashes plus renderer parameters.
- `IMAGES_READY` requires complete deterministic checks and one recorded source/hero/reference visual comparison with every mandatory assertion PASS.
- Missing QA, incomplete QA, zero visual comparison calls, or an unapproved candidate version forces `FIX_REQUIRED`.
- Never set `PASS` before image QA and fresh Shopify read-back both succeed.
- The only authorised product changes are accepted title, physical-photo arrival date, inventory `1`, and approved media/order.
- Description, price, cost, vendor, product type, handle, and status must match the pre-write snapshot.
- Never archive unless every fish is `PASS`.
- `FIX_REQUIRED` and `BLOCKED_*` are terminal for the current automated pass.
- Reruns continue from persisted state rather than restarting successful stages.

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
      "source_specific_crop": "PASS"
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

Retain identity, catalogue confidence, product evidence, paths, hashes, Shopify IDs, errors, and cost telemetry for each item.
