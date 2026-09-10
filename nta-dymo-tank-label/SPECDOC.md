# SPECDOC — NTA DYMO tank labels

Version: 2.0

Status: production-capable with explicit per-print authorization

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

This system MUST NOT mutate Shopify, inventory, pricing, product copy, media,
metafields, collections, or any unrelated workflow. In write-mode orchestration,
label generation MUST use freshly verified Shopify state. In dry-run
orchestration, it MAY use the proposed value for the same Shopify field.

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
5. a powered-printer acceptance test, when explicitly authorised, returns a
   successful driver result for exactly one label;
6. no model call, Shopify mutation, cutter action, or automatic physical retry
   occurs in the deterministic print path.
