# Batch state machine

Persist a machine-readable batch ledger. Recommended item states:

1. `DISCOVERED`
2. `SAVED`
3. `VISUAL_PENDING`
4. `VISUAL_ACCEPTED`
5. `BLOCKED_VISUAL`
6. `PRODUCT_RESOLVED`
7. `BLOCKED_PRODUCT`
8. `CSV_READY`
9. `IMAGES_READY`
10. `FILES_READY`
11. `MUTATION_PENDING`
12. `MUTATED`
13. `VERIFIED`
14. `PASS`
15. `FIX_REQUIRED`
16. `ARCHIVED`

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
- Never set `PASS` before fresh Shopify read-back succeeds.
- Never archive unless every fish is `PASS`.
- `FIX_REQUIRED` and `BLOCKED_*` are terminal for the current automated pass.
- Reruns continue from persisted state rather than restarting successful stages.

## Suggested ledger fields

```json
{
  "batch_id": "",
  "thread_id": "",
  "created_at": "",
  "updated_at": "",
  "batch_state": "ASSEMBLING",
  "items": [
    {
      "source_file_id": "",
      "discord_message_id": "",
      "discord_attachment_id": "",
      "source_path": "",
      "source_sha256": "",
      "tank_id": null,
      "photo_date": null,
      "proposed_title": null,
      "sex": "Uncertain",
      "confidence": {
        "tank": 0,
        "date": 0,
        "identity": 0,
        "title": 0,
        "sex": 0
      },
      "shopify_product_id": null,
      "original_shopify": {},
      "hero_path": null,
      "reference_path": null,
      "shopify_file_ids": {},
      "media_ids": {},
      "state": "DISCOVERED",
      "errors": [],
      "cost": {
        "cheap_calls": 0,
        "sol_calls": 0,
        "usd": 0
      }
    }
  ]
}
```
