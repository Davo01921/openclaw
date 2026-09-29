# Project Closeout — NTA DYMO Labels + Shopify Barcode Fallback

**Status:** COMPLETED  
**Closed:** 29 September 2026  
**Owner:** Nano Tanks Australia  
**Runtime:** Fred / OpenClaw  
**Canonical source of truth:** `Davo01921/openclaw-skills`

## Final production scope

The completed workflow provides deterministic NTA livestock DYMO labels on the
local DYMO LetraTag 200B and guarantees that every normal structured product
label carries the verified Shopify variant barcode encoded as Code 128-B.

Final label data includes:

- approved product name;
- retail price;
- optional validated bulk price/minimum;
- verified Shopify `custom.arrival_date`;
- received quantity in Shopify selling units;
- verified Shopify variant barcode.

## Final barcode behavior

For a label request:

1. Resolve the exact Shopify product and variant.
2. Fresh-read the live variant barcode.
3. If a non-empty barcode already exists, preserve it unchanged.
4. If the barcode is null or blank, deterministically generate the internal
   barcode `NTA-V-<legacyResourceId>`.
5. Search Shopify for any different variant already using that barcode.
6. If collision-free, write only the exact target variant's `barcode` field
   through the canonical Shopify write-verification boundary.
7. Fresh-read the variant independently from the mutation response and require
   the exact barcode value to match.
8. Search the barcode again for uniqueness.
9. Only a final verified live barcode may be passed to the DYMO print step.

The generated `NTA-V-...` value is an internal NTA scan identifier only. It is
not a GTIN, UPC, EAN, ISBN, MPN, or other standards-issued retail identifier and
must never be represented to Google Merchant Center or another external system
as one.

## Final DYMO behavior

- Structured labels require a verified Shopify barcode.
- Barcodes render as Code 128-B.
- Bars use the full 30-pixel print-head height.
- Quiet zones are preserved.
- No human-readable barcode value is printed below the bars.
- The DYMO presentation skill never writes Shopify itself.
- Physical printing still requires explicit authorization for that exact print.
- Failed or indeterminate physical attempts are never automatically retried.
- The manual cutter remains manual.

## Architecture

Canonical modules:

- `nta-product-barcode` — existing-barcode preservation, deterministic internal
  barcode generation, collision policy, Shopify adapter, fresh read-back and
  uniqueness verification.
- `nta-shopify-write-verifier` — canonical authorised Shopify mutation and
  verification boundary.
- `nta-dymo-tank-label` — deterministic label formatter, renderer, previewer
  and BLE printer client.
- `nta-inventory-update` / `nta-product-orchestrator` — route the barcode
  policy before the final label step.

## Source-of-truth hierarchy

1. **Canonical:** `Davo01921/openclaw-skills`
2. **Fred repository mirror:** `Davo01921/agent-memory/skills`
3. **Fred local deployment mirror:** `~/.openclaw/workspace/fred/skills`

The mirrors must follow the canonical repository and must not introduce
conflicting behavior.

## Verification coverage

The repository contains deterministic regression coverage for:

- preserving an existing Shopify barcode;
- deterministic generation of `NTA-V-<variant-id>`;
- missing live-state evidence;
- foreign-variant collision blocking;
- dry-run proposal without Shopify mutation;
- exact Shopify barcode write;
- fresh read-back verification;
- post-write uniqueness checking;
- read-back mismatch failure;
- Code 128-B symbol/checksum/quiet-zone/full-height rendering;
- required barcode on structured DYMO labels;
- write verification occurring before the DYMO label step.

Shopify Admin GraphQL shapes used by the concrete adapter were validated against
the current schema for variant read, barcode search, and
`productVariantsBulkUpdate`.

## Closeout decision

The implementation scope is complete and accepted for production use. There are
no remaining build phases for this project.

From this point forward:

- ordinary use is operational;
- bug fixes, API/schema changes, printer changes, or requested label-format
  changes are maintenance;
- substantial new functionality should open a new project/change request rather
  than reopening this completed implementation.
