# OpenClaw implementation notes

## Recommended architecture

Do **not** implement the skill as a single giant prompt that lets the active model execute every operation.

Use a deterministic orchestrator script/plugin/tool for the batch state machine, and invoke model workers only for the stages that genuinely require visual judgement.

Recommended components:

```text
Discord batch collector
        |
        v
deterministic orchestrator
        |
        +--> cheap vision batch classifier
        |        |
        |        +--> focused cheap retry
        |                 |
        |                 +--> Sol exception review
        |
        +--> CSV builder
        +--> image pipeline
        +--> nta-product-resolver
        +--> Shopify adapter / nta-shopify-write-verifier
        +--> assertion/read-back layer
        +--> archive manager
        +--> Discord reporter
```

## Why

OpenClaw skills are instructions, while tools/plugins perform actions. OpenClaw also supports per-agent model configuration. Keep stateful/deterministic work in code and use agents only where interpretation is required.

## Suggested implementation boundary

Build or adapt these typed operations:

- `collect_discord_batch(thread_id)`
- `save_source_attachment(...)`
- `hash_source(path)`
- `load_or_create_batch_ledger(batch_id)`
- `cheap_visual_catalogue(image_paths)`
- `cheap_visual_retry(image_path, field)`
- `sol_review(exception_packet)`
- `resolve_nta_product(identity_evidence)`
- `shopify_find_exact_tank(tank_id)`
- `build_inventory_csv(items)`
- `prepare_reference(item)`
- `prepare_hero(item)`
- `shopify_find_ready_file(asset)`
- `shopify_upload_missing_file(asset)`
- `shopify_apply_betta_media(product_id, ...)`
- `shopify_set_arrival_date(product_id, date)`
- `shopify_set_inventory(product_id, 1)`
- `shopify_readback(product_id)`
- `assert_product_state(expected, actual)`
- `archive_passed_batch(batch_id)`
- `render_discord_report(batch_id)`

## Important authority split

The cheap vision worker may return observations only.

It must not:
- issue Shopify mutations;
- create products;
- decide to ignore API errors;
- change price/title/cost;
- archive;
- invent missing mappings.

The Sol reviewer may diagnose exceptions but should not receive unrestricted mutation authority merely because it is the stronger model.

The orchestrator is responsible for enforcing invariants.

For every mutation, create the shared verifier operation record with the batch ID as job ID and a stable per-fish idempotency key. The Shopify adapter is an implementation detail of `nta-shopify-write-verifier`; the Betta-specific assertions supplement, but must not bypass, the verifier's fresh read-back.

## Cost telemetry

Wrap every model invocation with a usage recorder. Prefer provider-reported usage/cost. Otherwise calculate from a configuration price table.

Suggested environment/config values:

```text
BETTA_VISION_MODEL=<qwen vision-capable model id>
BETTA_SOL_MODEL=<gpt-5.6-sol model id>
BETTA_UTILITY_MODEL=<cheap text model id>

BETTA_TANK_ACCEPT=0.90
BETTA_TANK_RETRY=0.70
BETTA_DATE_ACCEPT=0.90
BETTA_DATE_RETRY=0.70
BETTA_SEX_ACCEPT=0.85
BETTA_SEX_RETRY=0.60
BETTA_SOL_MAX_RATIO=0.15
BETTA_SOL_MIN_CAP=2
```

## Rollout

1. Install the v2 skill directory in the workspace skills path.
2. Confirm `openclaw skills list` sees `betta-picture-processing`.
3. Configure the cheap vision and Sol reviewer agents/model IDs.
4. Run a dry-run batch with Shopify mutations disabled.
5. Compare interpreted tank/date/title/sex against the source photos.
6. Enable Shopify writes for one small batch.
7. Confirm media order, inventory, arrival date, title/price preservation, and archive set equality.
8. Review cost telemetry after 20-30 Bettas and adjust thresholds based on real false-positive/false-negative behaviour.

## Do not over-optimise too early

The biggest savings come from eliminating model use for deterministic work and keeping Sol out of the normal path. Shaving tiny token counts from an already cheap call is secondary to avoiding a wrong fish/product mapping.
