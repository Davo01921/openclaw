---
name: "nta-dymo-tank-label"
version: "2.0"
description: "Deterministically format, preview, check, and explicitly print NTA livestock tank labels to a local DYMO LetraTag 200B over Bluetooth LE."
---

# NTA DYMO Tank Label

## Purpose

Render the compact two-line DYMO text for a received livestock item, preview it,
check the local printer, and print only when physical printing is explicitly
authorized. This presentation module does not resolve identity, decide price or
bulk pricing, interpret stock, set arrival dates, or write to Shopify.

It is called by `nta-inventory-update` through `nta-product-orchestrator` only
after the intake state has been resolved. In write mode, use the fresh Shopify
read-back value for `custom.arrival_date`; in dry-run mode, use the proposed
value for that same Shopify field. There is no separate physical arrival or
availability date for labels.

## Execution rule

Use `scripts/label_formatter.py` as the canonical runtime formatter and
`scripts/nta_label_print.py` through the `nta-label-print` launcher for preview,
status, and print operations. Formatting, validation, raster rendering, BLE
communication, and result handling are deterministic and consume zero model
calls. Do not delegate these operations to another model. Do not perform a
redundant `printer-status` operation immediately before every print. If identity,
price, quantity, selling-unit conversion, arrival date, or another upstream
field is ambiguous, stop at the upstream review boundary rather than asking a
model to guess inside this skill.

If an upstream workflow genuinely requires model reasoning before this skill is
called, use the narrowest configured general model that can safely resolve that
upstream ambiguity. The formatter and printer client never select or call a
model.

## Local installation

From this skill directory, create its isolated Python environment once:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
```

The maintained macOS-compatible BLE dependency is pinned in
`requirements.lock`. The printer connects directly over BLE and is not added as
a normal macOS printer. If macOS prompts for Bluetooth access, allow it for the
OpenClaw host process.

## Operations

```sh
./nta-label-print printer-status
./nta-label-print preview --label-json '{...}' --output /tmp/label.png
./nta-label-print print --label-json '{...}' --dry-run
./nta-label-print print --label-json '{...}' --confirm
```

- `printer-status` scans and connects without printing.
- `preview` validates and creates a PNG without using Bluetooth.
- `print --dry-run` validates and creates a preview without scanning,
  connecting, or printing.
- A physical print requires `print --confirm`; never infer authorization.
- Do not automatically retry a failed physical print because that can create a
  duplicate label.

## Required input

```yaml
label:
  product_name:             # approved Shopify customer-facing name
  retail_price:             # approved retail price per Shopify selling unit
  bulk_price: null          # optional approved discounted price per same unit
  bulk_min_quantity: null   # required when bulk_price is present; integer >= 2
  shopify_arrival_date:     # custom.arrival_date, ISO YYYY-MM-DD
  quantity:                 # received Shopify-selling units; positive integer
  source: shopify_readback | dry_run_proposed_shopify_state
```

`quantity` is the received quantity after the established supplier-pack to
Shopify-selling-unit conversion. It is not silently replaced with a different
on-hand or preorder quantity.

## Exact output contract

Output exactly two lines, with one newline between them and no prefixes,
suffixes, date labels, tank values, or extra whitespace:

```text
{Name} | ${price}ea[ | ${bulk_price}ea/{bulk_min_quantity}+]
{Shopify arrival date formatted DDMMYY} | Q{quantity}
```

Examples:

```text
Blue Emperor Tetra | $8ea
090926 | Q30
```

```text
Cardinal Tetra | $7ea | $6ea/10+
090926 | Q40
```

Format valid money without unnecessary trailing zeroes (`8`, `8.5`, `8.25`).
Do not round a supplied approved price to create a label value.

The standard two-line raster uses **Arial Bold 15 px** and an ordinary ASCII
`$` symbol. A single `|` is a field separator. A triple `|||` is only a printed
manual physical-cut marker. The LetraTag cutter is manual: never attempt to
actuate, simulate, or control it.

## Bulk-pricing rule

Append the optional bulk segment only when all of the following are true:

1. an approved numeric `bulk_price` exists;
2. `bulk_min_quantity` is an integer of at least 2; and
3. `bulk_price` is strictly less than `retail_price` for the same Shopify
   selling unit.

An equal, higher, missing, malformed, or unit-mismatched bulk value is not a
real bulk price. Omit it and return a warning for the upstream review report;
do not invent a threshold or discount.

## Validation and failure handling

- Require a non-empty approved name, a non-negative retail price, a positive
  integer quantity, and a valid ISO date from `custom.arrival_date`.
- Reject missing, non-ISO, or impossible arrival dates. Do not substitute
  today's date, supplier ETA, photo date, availability date, or a tank date.
- Reject quantity or price unit ambiguity rather than formatting a misleading
  label.
- Return `READY` with `text` and `warnings`, or `REVIEW_REQUIRED` with the
  missing/invalid fields. Never mutate Shopify.
- For BLE failures, return a concise code and message covering printer not
  found, Bluetooth permission, Bluetooth unavailable, or print failure.
- Treat a print as successful only when the printer driver returns success.

## Output state

```yaml
labels:
  dymo_tank:
    status: READY | REVIEW_REQUIRED
    text: |
      Blue Emperor Tetra | $8ea
      090926 | Q30
    source: shopify_readback | dry_run_proposed_shopify_state
    warnings: []
```
