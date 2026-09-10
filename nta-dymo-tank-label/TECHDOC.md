# TECHDOC — NTA DYMO tank labels

Version: 2.0

Runtime owner: Fred/OpenClaw

Canonical repository: `Davo01921/openclaw-skills`

## System overview

The integration is a local deterministic Python path:

```text
Discord / Telegram / WhatsApp
              |
              v
        Fred / OpenClaw
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
Formatting, validation, rendering, discovery, printing, and result
interpretation are deterministic code and require zero model calls.

## Components

- `SKILL.md`: discovery, execution boundaries, and concise usage guidance.
- `scripts/label_formatter.py`: canonical structured livestock formatter.
- `scripts/nta_label_print.py`: validation, raster rendering, BLE status, dry
  run, preview, and physical print operations.
- `nta-label-print`: launcher for the isolated Python environment.
- `requirements.lock`: pinned printer dependency.
- `tests/test_label_print.py`: non-mutating regression suite.
- `scripts/dry_run.py`: canonical formatter regression fixture.
- `SOP.md`: staff operating procedure.
- `SPECDOC.md`: normative behavior and acceptance contract.

The deployed Fred skill is under
`~/.openclaw/workspace/fred/skills/nta-label-print`. The canonical shared source
is `nta-dymo-tank-label` in the skills repository.

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
  "source": "shopify_readback"
}
```

Allowed sources are `shopify_readback` and
`dry_run_proposed_shopify_state`. The formatter returns `REVIEW_REQUIRED`
instead of inventing an invalid or missing required field.

## Rendering

Standard two-line labels use Arial Bold 15 px, one row of inter-line spacing,
and an ordinary ASCII dollar sign. The raster is monochrome and exactly 30
pixels high. Horizontal pixels are doubled with nearest-neighbour scaling to
match the LetraTag head geometry and driver convention.

The renderer preserves single and triple pipe runs and rejects all other pipe
runs. It reports the number of visible `|||` markers but never exposes a cutter
control operation.

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
- the seven-test regression suite;
- a structured Cardinal Tetra dry-run preview;
- skill frontmatter and reference validation.

A physical acceptance test requires a powered printer and explicit authority
for exactly one test label. Do not describe a preview, BLE connection, or dry
run as a successful physical print.
