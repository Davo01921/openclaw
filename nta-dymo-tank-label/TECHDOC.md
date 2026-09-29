# TECHDOC — NTA DYMO tank labels

Version: 2.3

Runtime owner: Fred/OpenClaw

Canonical repository / source of truth: `Davo01921/openclaw-skills`

Deployment mirrors: `Davo01921/agent-memory/skills` and
`~/.openclaw/workspace/fred/skills`. Mirrors must follow the canonical source and
must not introduce conflicting behavior.

## System overview

The integration is a local deterministic Python path:

```text
Discord / Telegram / WhatsApp
              |
              v
        Fred / OpenClaw
              |
              v
 exact Shopify variant resolution
              |
              v
 nta-product-barcode (only if barcode missing)
              |
              v
 Shopify collision check -> verified write -> fresh read-back
              |
              v
  nta-dymo-tank-label formatter
              |
              v
  validation + 1-bit raster rendering
              |
              v
   direct Bluetooth LE connection
              |
              v
       DYMO LetraTag 200B
```

The conversation layer interprets the staff request and collects missing facts.
Barcode fallback policy, formatting, validation, rendering, discovery,
verification sequencing, printing, and result interpretation are deterministic
code and require zero model calls. `nta-product-barcode` owns only the missing-
barcode policy and Shopify verification sequence; the DYMO presentation skill
remains Shopify-read-only.

## Components

- `SKILL.md`: discovery, execution boundaries, and concise usage guidance.
- `scripts/label_formatter.py`: canonical structured livestock formatter.
- `scripts/nta_label_print.py`: validation, raster rendering, BLE status, dry
  run, preview, and physical print operations.
- `nta-label-print`: launcher for the isolated Python environment.
- `requirements.lock`: pinned printer dependency.
- `tests/test_label_print.py`: non-mutating regression suite.
- `scripts/dry_run.py`: canonical formatter regression fixture.
- `../nta-product-barcode/`: canonical missing-barcode policy, Shopify adapter,
  collision checks, read-back verification, and regression tests.
- `SOP.md`: staff operating procedure.
- `SPECDOC.md`: normative behavior and acceptance contract.

The deployed Fred label skill is under
`~/.openclaw/workspace/fred/skills/nta-label-print`; the barcode policy mirror is
under `~/.openclaw/workspace/fred/skills/nta-product-barcode` when synced. The
canonical shared sources are `nta-dymo-tank-label` and `nta-product-barcode` in
`Davo01921/openclaw-skills`.

## Runtime and dependencies

Create an isolated environment in the skill directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
```

The pinned `dymo-bluetooth` package uses Bleak/CoreBluetooth on macOS. BLE
imports are lazy, so preview and dry-run operations do not load the Bluetooth
stack. The `.venv` directory and Python cache files are excluded from Git.

## Command interface

```sh
./nta-label-print printer-status
./nta-label-print preview --label-json '{...}' --output /tmp/label.png
./nta-label-print print --label-json '{...}' --dry-run
./nta-label-print print --label-json '{...}' --confirm
```

`--text` accepts already-approved two-line text. `--label-json` and
`--label-file` route structured data through the canonical formatter. Physical
printing is rejected without `--confirm`.

## Structured input

```json
{
  "product_name": "Cardinal Tetra",
  "retail_price": "7.00",
  "bulk_price": "6.00",
  "bulk_min_quantity": 10,
  "shopify_arrival_date": "2026-09-09",
  "quantity": 40,
  "source": "shopify_readback",
  "shopify_barcode": "X12ENA3C59"
}
```

Allowed sources are `shopify_readback` and
`dry_run_proposed_shopify_state`. The formatter returns `REVIEW_REQUIRED`
instead of inventing an invalid or missing required field.

`shopify_barcode` is required for every structured NTA product label. It must
be the verified Shopify variant barcode containing 1-48 printable ASCII
characters. Missing or invalid barcode data returns `REVIEW_REQUIRED` at the
DYMO skill boundary. If the wider workflow fresh-reads a null or blank barcode,
`nta-product-barcode` generates `NTA-V-<legacyResourceId>`, checks for foreign-
variant collisions, writes only the exact variant barcode through Shopify, then
freshly reads and rechecks uniqueness before the barcode is accepted for print.

## Missing-barcode Shopify sequence

The concrete adapter is `../nta-product-barcode/scripts/shopify_adapter.py`.
With an authenticated Shopify Admin GraphQL transport it performs:

1. fresh variant read (`id`, `legacyResourceId`, `barcode`, `product.id`);
2. preserve existing barcode, or deterministically propose `NTA-V-<legacyResourceId>`;
3. pre-write barcode collision search;
4. one exact `productVariantsBulkUpdate` barcode write when required;
5. independent fresh variant read-back;
6. post-write collision search;
7. return `VERIFIED` only when all checks pass.

A mutation response by itself is never proof of completion. Dry-run may propose
the internal barcode but may not write Shopify or physically print it.

## Rendering

Standard two-line labels use Arial Bold 15 px, one row of inter-line spacing,
and an ordinary ASCII dollar sign. The raster is monochrome and exactly 30
pixels high. Horizontal pixels are doubled with nearest-neighbour scaling to
match the LetraTag head geometry and driver convention.

The renderer preserves single and triple pipe runs and rejects all other pipe
runs. It reports the number of visible `|||` markers but never exposes a cutter
control operation.

The verified Shopify barcode is encoded directly as Code 128-B with a calculated
modulo 103 checksum, 12 quiet modules on each side, full 30-row bar height, and no
human-readable characters. It is appended after a 12-pixel source-raster gap.
The entire image is then horizontally doubled with nearest-neighbour scaling.

## Bluetooth behavior

The client discovers an advertising LetraTag 200B, connects directly through
CoreBluetooth, sends the rendered canvas, reads the driver's result, and
disconnects. It does not use the macOS printer queue and does not require normal
Bluetooth pairing.

`printer-status` connects without printing. `print` performs its own discovery,
so callers should not add a redundant status scan. Physical attempts are never
automatically retried.

## Result and failure semantics

Operations emit concise JSON. Key states are:

- `READY`: preview or status succeeded; no physical print occurred.
- `DRY_RUN`: validation and preview succeeded without Bluetooth.
- `PRINTED`: the driver returned `SUCCESS` or `SUCCESS_LOW_BATTERY`.
- `REVIEW_REQUIRED`: label input or invocation was invalid.
- `UNAVAILABLE` / `FAILED`: printer discovery, permission, connection, or print
  failed.

Known diagnostic codes include `PRINTER_NOT_FOUND`,
`BLUETOOTH_PERMISSION_REQUIRED`, `BLUETOOTH_OFF`, `BLE_UNSUPPORTED`,
`BLE_ERROR`, `PRINT_ERROR`, and `INVALID_LABEL`.

The client reports success only from the printer result. A request, scan, or
connection alone is never treated as proof of printing.

## macOS permissions

Bluetooth must be enabled. The OpenClaw host process must be allowed under
macOS **Privacy & Security > Bluetooth**. Permission is granted to the process
hosting the Python/Bleak call, not by registering a normal printer.

## Verification

Required non-mutating checks are:

- Python compilation;
- canonical formatter dry run;
- the regression suite, including Code 128-B checksum, quiet-zone, full-height,
  required-structured-barcode, and rendering checks;
- `nta-product-barcode` policy tests for preserve-existing, deterministic generation,
  collision handling, and read-back comparison;
- Shopify adapter tests for dry-run no-write, exact write, fresh verification,
  collision block, and mismatch failure;
- a structured Cardinal Tetra dry-run preview;
- skill frontmatter and reference validation.

A physical acceptance test requires a powered printer and explicit authority
for exactly one test label. Do not describe a preview, BLE connection, or dry
run as a successful physical print.
