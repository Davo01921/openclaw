# Generic Shopify Batch Uploader

`scripts/betta_shopify_batch.py` is the reusable, manifest-bound Shopify writer for approved individual-Betta batches. It consumes existing approval, identity, image-QA, protected-snapshot, and new-fish-authority evidence. It does not generate images, reinterpret titles, discover authority, create products, or change protected commercial fields.

## Safety boundary

The CLI is read-only with respect to Shopify unless all of these are true:

1. the command is `execute` or `resume`;
2. `--live` is present;
3. `shopify_write_authorised` is `true` at batch level;
4. every selected item has `write_authorised: true`;
5. `--confirm-manifest-sha256` exactly matches the bytes being executed;
6. the authenticated bridge independently validates the manifest, state file, pending intent, variables hash, local image hashes, and operation scope.

Without a command, the CLI selects `dry-run`. `execute` and `resume` also remain dry-run unless `--live` is supplied. The uploader uses the existing authenticated Shopify bridge and introduces no credential store or Shopify application.

## Manifest contract

The manifest schema is `nta-betta-shopify-batch-v1`. It contains:

- a unique `batch_id` and batch write-authority flag;
- bridge path, Node binary, and existing environment-file path;
- hash-locked approval plan, protected snapshot, Shopify detail, reconciled-label, and new-fish-authority evidence;
- one entry per tank with exact Product, Variant, Inventory Item, and Location GIDs;
- approved title, arrival date, target quantity, and inventory reason;
- source reference and hash-locked HERO, ORIGINAL, and image-QA files;
- an owner-bound exception record when a mandatory image-QA assertion was explicitly accepted;
- optional hash-locked completion receipts for a product already completed and independently reverified.

Duplicate tanks, products, variants, or inventory items are rejected. The uploader also rejects evidence disagreement, changed files, unsupported quantity, stale Shopify identity or stock, protected-field drift, missing new-fish authority, and an unbound failed-QA exception.

Do not edit an approved manifest in place after evidence review. Create a new version, review its dry-run report, and approve its new SHA-256.

## Commands

All commands require `--manifest`. Use `--tank TANK` repeatedly or with comma-separated IDs to select a subset.

```sh
# Default command: dry-run
python3 scripts/betta_shopify_batch.py --manifest /path/to/batch.json

python3 scripts/betta_shopify_batch.py preflight --manifest /path/to/batch.json
python3 scripts/betta_shopify_batch.py dry-run --manifest /path/to/batch.json
python3 scripts/betta_shopify_batch.py status --manifest /path/to/batch.json
python3 scripts/betta_shopify_batch.py verify --manifest /path/to/batch.json

# Still dry-run because --live is absent
python3 scripts/betta_shopify_batch.py execute --manifest /path/to/batch.json
python3 scripts/betta_shopify_batch.py resume --manifest /path/to/batch.json
```

Command behaviour:

- `preflight` validates all local evidence, hashes, identity, authority, and fresh Shopify baselines; it writes no Shopify data.
- `dry-run` performs preflight and emits the exact proposed per-product changes.
- `execute` performs a dry-run unless explicitly live-authorised.
- `status` reads only local persisted state and makes no Shopify call.
- `resume` first reconciles any uncertain intent against fresh Shopify state and never replays it in the same invocation.
- `verify` performs independent fresh Shopify readback and writes a read-only verification report.

## Live per-product sequence

For each authorised product, live execution:

1. revalidates the manifest, evidence hashes, source hashes, identity, and fresh Shopify baseline;
2. records a mutation intent, requests staged uploads, and transfers the approved HERO and ORIGINAL;
3. attaches both images and polls until both Shopify media records are `READY`;
4. identifies both uploads independently from manifest-bound alt metadata;
5. reorders HERO first and ORIGINAL second and verifies actual order;
6. deletes only old media IDs captured during preflight, then verifies exactly two images remain;
7. updates only the approved title and `custom.arrival_date`, then independently verifies both;
8. rechecks stock and applies inventory with `changeFromQuantity` compare-and-set plus a persisted UUID idempotency key;
9. freshly verifies identity, quantity, location, title, date, media, price, cost, description, status, tracking, and `DENY` policy;
10. writes a complete per-product final receipt and telemetry.

Old media is never deleted until both replacements are READY, identified, ordered, and read back. A product with valid completion receipts is freshly reverified and skipped with zero writes.

## State, reports, and recovery

State is namespaced by batch ID and manifest hash, normally under `.betta-shopify-state/`. Reports go to the manifest's `report_dir`. The state includes the preflight snapshot, current stage, immutable event records, pending intent and variables hash, uploaded media IDs, inventory idempotency key, call counters, timings, read/write telemetry, and final receipt path. Existing reports and event files are never overwritten.

Each write is journalled before the bridge is called. If transport fails after dispatch, the intent remains uncertain. Run read-only reconciliation first:

```sh
python3 scripts/betta_shopify_batch.py resume --manifest /path/to/batch.json
```

If fresh readback proves the write happened, state advances without replay. If it cannot prove that, the item remains paused for an operator decision. Only after external evidence establishes that the write did not occur may the operator explicitly record that decision:

```sh
python3 scripts/betta_shopify_batch.py resume \
  --manifest /path/to/batch.json \
  --resolve-uncertain-not-applied
```

That invocation records the decision and exits; it does not replay the mutation. Review state and run a separate authorised resume afterward.

## Safe production procedure

1. Preserve the reviewed dry-run manifest and report as immutable evidence.
2. After explicit owner approval, create a new manifest version with batch authority and only the intended product entries authorised. Keep already-completed products unauthorised.
3. Run `preflight` and `dry-run` against that exact file. Resolve every blocker and review all proposed changes and accepted exceptions.
4. Compute the exact manifest digest: `shasum -a 256 /path/to/approved-batch.json`.
5. Execute only the reviewed digest:

```sh
python3 scripts/betta_shopify_batch.py execute \
  --manifest /path/to/approved-batch.json \
  --live \
  --confirm-manifest-sha256 '<reviewed-sha256>'
```

6. Inspect the per-product receipts and run `verify` against the same manifest.
7. If interrupted, use `status`, then `resume` without `--live` for reconciliation. Do not blindly rerun `execute`.

Live tests must use the production manifest gate; mocked Shopify responses are used for automated write-path tests.
