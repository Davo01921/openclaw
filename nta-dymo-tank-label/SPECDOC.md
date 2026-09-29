# SPECDOC — NTA DYMO tank labels

Version: 2.3

Status: COMPLETED / production-capable with explicit per-print authorization

Normative words `MUST`, `MUST NOT`, `SHOULD`, and `MAY` indicate requirement
strength.

## Objective

The system MUST deterministically format and preview approved NTA livestock
tank labels and MAY print one label to the local DYMO LetraTag 200B only after
explicit authorization for that exact physical print.

## Input contract

Structured input MUST contain:

- `product_name`: non-empty approved customer-facing string;
- `retail_price`: finite, non-negative approved price per Shopify selling unit;
- `shopify_arrival_date`: valid ISO `YYYY-MM-DD` value from
  `custom.arrival_date` or its dry-run proposal;
- `quantity`: positive integer in Shopify selling units;
- `source`: `shopify_readback` or `dry_run_proposed_shopify_state`.

`bulk_price` and `bulk_min_quantity` MAY be null. A bulk segment MUST be shown
only when the price is finite and non-negative, the minimum is an integer of at
least 2, and the bulk price is strictly less than retail for the same selling
unit. Invalid optional bulk data MUST be omitted with a warning.

`shopify_barcode` MUST be present for every structured NTA product label. It
MUST be the verified Shopify variant barcode, contain 1-48 printable ASCII
characters, and be encoded without alteration as Code 128-B. The DYMO
presentation module MUST NOT generate or infer a barcode value. When the wider
Fred/OpenClaw workflow encounters a missing Shopify variant barcode, it MUST
route upstream to `nta-product-barcode`; only a final verified Shopify barcode
may enter this skill. A missing or invalid barcode at this skill boundary MUST
produce `REVIEW_REQUIRED`; the system MUST NOT silently fall back to a text-only
product label.

Missing, invalid, ambiguous, or unit-mismatched required input MUST produce
`REVIEW_REQUIRED`. The system MUST NOT invent or infer a replacement.

## Text contract

The standard output MUST contain exactly two lines separated by one newline:

```text
{Name} | ${price}ea[ | ${bulk_price}ea/{bulk_min_quantity}+]
{DDMMYY} | Q{quantity}
```

Money MUST retain the approved value without unnecessary trailing zeroes and
MUST NOT be rounded to create a label value. The dollar sign MUST be the normal
ASCII `$` character.

## Separator and cutter contract

- A single `|` MUST remain a visible field separator.
- A triple `|||` MUST remain a visible manual physical-cut marker.
- Any other consecutive pipe count MUST be rejected.
- The system MUST NOT interpret a single pipe as a cut request.
- The system MUST NOT actuate, simulate, or expose control of the manual cutter.
- Results MUST report `cutter_action: NONE` for rendered or printed labels.

## Raster contract

A standard two-line label MUST use Arial Bold at 15 px. The raster MUST be
monochrome and 30 pixels high. Horizontal scaling MAY compensate for the
printer's pixel geometry but MUST preserve hard monochrome edges.

The verified barcode raster MUST be appended after the text with a 12-pixel
source-raster gap. Bars MUST occupy the full 30-pixel print-head
height and MUST include at least 12 quiet modules on both sides. The raster
MUST NOT include human-readable characters below the bars. Barcode results
MUST identify `barcode_format: CODE128_B` and
`barcode_human_readable: false`.

## Operation contract

### `printer-status`

The operation MUST discover and connect directly over BLE without sending
print data. A successful status result MUST be `READY` and MUST NOT imply that
cassette presence, battery condition, or future printing is verified.

### `preview`

The operation MUST validate and render a PNG without scanning, connecting, or
printing. It MUST report `READY` and `dry_run: true` on success.

### `print --dry-run`

The operation MUST follow the same no-Bluetooth, no-print boundary as preview.
It MUST report `DRY_RUN` and `physical_print: false` on success.

### Physical `print`

The operation MUST require explicit confirmation immediately before the
physical attempt. Without confirmation, it MUST return `REVIEW_REQUIRED` and
MUST NOT scan or print.

One confirmed invocation MUST make at most one physical print attempt. The
system MUST NOT automatically retry a failed or indeterminate attempt. It MUST
report `PRINTED` only when the driver returns `SUCCESS` or
`SUCCESS_LOW_BATTERY`.

## Bluetooth contract

The printer MUST be accessed directly through macOS CoreBluetooth/BLE. The
integration MUST NOT depend on adding the device as a normal macOS printer.

The client MUST disconnect after status or print completion, including handled
failure paths where a connection was established. Bluetooth dependencies SHOULD
load only for operations that require Bluetooth.

## Channel contract

Discord, Telegram, WhatsApp, and other configured OpenClaw channels MAY invoke
the same skill through Fred. Channel wording MAY be conversational, but the
physical authorization and exact-input requirements MUST remain unchanged.

An instruction such as “make a label” without an explicit physical-print
request MUST default to preview or clarification. A channel message MUST NOT be
treated as authorization for additional copies or future prints.

## Model and execution contract

Formatting, validation, rendering, BLE communication, and result interpretation
MUST use deterministic Python and MUST consume zero model calls. A conversation
model MAY collect the required facts, but MUST NOT guess missing facts or choose
print retry behavior.

## Production boundary

`nta-dymo-tank-label` MUST NOT mutate Shopify, inventory, pricing, product copy,
media, metafields, collections, or any unrelated workflow. The wider label
orchestration MAY invoke `nta-product-barcode` before this skill solely when the
resolved variant barcode is null or blank. That upstream module may propose the
internal `NTA-V-<legacyResourceId>` barcode and route the exact variant barcode
write through `nta-shopify-write-verifier`; fresh read-back and uniqueness
verification MUST succeed before physical printing. Existing non-empty barcodes
MUST be preserved. The internal NTA barcode MUST NOT be represented as a
GTIN/UPC/EAN/ISBN/MPN. In write-mode orchestration, label generation MUST use
freshly verified Shopify state. In dry-run orchestration, it MAY use a proposed
internal barcode for preview only and MUST NOT physically print it.

## Status contract

- `READY`: validation, preview, or printer status succeeded; no physical print
  is implied.
- `DRY_RUN`: print-path validation and preview succeeded without Bluetooth.
- `PRINTED`: one physical print returned a successful driver result.
- `REVIEW_REQUIRED`: label data or authorization was invalid or incomplete.
- `UNAVAILABLE`: printer status could not establish readiness.
- `FAILED`: a physical attempt or printer operation failed.

Failures MUST include a concise machine-readable code and a useful message.
Permission, disabled Bluetooth, unsupported BLE, printer-not-found, and generic
print errors MUST be distinguishable.

## Acceptance criteria

The release is acceptable when:

1. the canonical formatter dry run passes;
2. all label regression tests pass;
3. structured preview produces the exact expected two-line text and 30-pixel
   raster without Bluetooth;
4. pipe and cutter invariants are covered by tests;
5. Code 128-B symbol, checksum, quiet-zone, full-height, required-structured-
   barcode, and rendering invariants are covered by tests;
6. a powered-printer acceptance test, when explicitly authorised, returns a
   successful driver result for exactly one label;
7. no model call, Shopify mutation, cutter action, or automatic physical retry
   occurs inside the deterministic DYMO print path;
8. missing-barcode orchestration is covered by deterministic tests for preserve-existing, generate-internal, collision block, Shopify write, fresh read-back verification, and mismatch failure;
9. the canonical source is `Davo01921/openclaw-skills`; Fred deployment copies are mirrors only.
