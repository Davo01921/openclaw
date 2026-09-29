# SOP — NTA DYMO tank labels

Owner: Nano Tanks Australia

Skill: `nta-dymo-tank-label`

Runtime: Fred/OpenClaw on the local Mac

Printer: DYMO LetraTag 200B over Bluetooth LE

## Purpose

Create consistent two-line livestock tank labels from approved NTA product
facts, preview them safely, and print exactly one label only when a staff member
explicitly authorises the physical print.

## Before starting

- Use Discord, Telegram, WhatsApp, or another channel already routed to Fred.
- For a physical print, keep the Mac awake with OpenClaw running.
- Turn on the LetraTag 200B, keep it near the Mac, and confirm its lid, cassette,
  and four batteries are ready.
- Do not pair or add the printer as a normal macOS printer.

## Required label facts

Provide or verify:

- approved customer-facing product name;
- approved retail price per selling unit;
- approved bulk price and minimum quantity, when applicable;
- Shopify `custom.arrival_date` in write mode, or the proposed value for that
  same field in dry-run mode;
- received quantity in Shopify selling units.
- verified Shopify variant barcode for every normal structured product label.

Never guess a missing name, price, date, quantity, bulk threshold, selling
unit, or barcode inside the DYMO presentation skill. If the resolved Shopify
variant has no barcode, Fred must route upstream to `nta-product-barcode`, which
creates only the deterministic internal `NTA-V-<legacyResourceId>` value,
collision-checks it, writes it to Shopify through the canonical verifier, and
freshly verifies it before printing. Do not print a text-only structured
product label.

## Preview procedure

1. Ask Fred to preview the label and send the PNG.
2. Check that the preview contains exactly two lines:

   ```text
   {Name} | ${price}ea[ | ${bulk_price}ea/{minimum}+]
   {DDMMYY} | Q{quantity}
   ```

3. Confirm the name, price, optional bulk tier, date, and quantity against the
   approved source.
4. Confirm the text uses Arial Bold 15 px and an ordinary `$` symbol.
5. Confirm full-height Code 128 bars appear after the text with blank quiet
   margins and no printed value below the bars.
6. If anything is wrong, correct the approved input and request another preview.
   Previewing never scans for the printer or consumes tape.

Example request:

```text
Fred, preview a tank label for Cardinal Tetra, $7 each, bulk $6 each for 10+,
arrival 9 September 2026, quantity 40, using verified Shopify barcode
X12ENA3C59. Send me the PNG.
```

## Missing-barcode procedure

If the exact resolved Shopify variant has a null or blank barcode:

1. Fred fresh-reads the variant barcode and numeric `legacyResourceId` from Shopify.
2. `nta-product-barcode` proposes `NTA-V-<legacyResourceId>`.
3. Fred checks Shopify for a collision with another variant.
4. If collision-free, the exact variant barcode field is written through `nta-shopify-write-verifier`.
5. Fred independently re-reads Shopify and requires the exact barcode value to match.
6. Fred searches the barcode again; any different variant match blocks printing.
7. Only a final `VERIFIED` barcode may be passed to the DYMO label skill.

Existing non-empty Shopify barcodes are preserved and are never automatically overwritten.
The generated NTA barcode is an internal scan identifier, not a GTIN/UPC/EAN/ISBN/MPN.

## Physical print procedure

1. Review the exact label text or preview first.
2. Explicitly authorise one physical print and include the exact label facts or
   text in the same request.
3. Wait for Fred to report the printer driver's result.
4. Treat the operation as complete only when Fred reports `PRINTED`.
5. Manually operate the printer's cutter after printing.

Example request:

```text
Fred, print exactly one physical tank label now for Cardinal Tetra, $7 each,
bulk $6 each for 10+, arrival 9 September 2026, quantity 40. I authorise one
print.
```

Creating a request, finding the printer, or connecting over Bluetooth is not
proof that a label printed.

## Printer-status procedure

Ask `Fred, check the DYMO printer status` only when checking readiness or
diagnosing a connection problem. A print operation already discovers and
connects to the printer, so a separate status check before every print wastes a
Bluetooth scan.

## Failure procedure

- `PRINTER_NOT_FOUND`: turn on the nearby printer and check the lid, cassette,
  and batteries.
- `BLUETOOTH_PERMISSION_REQUIRED`: enable the OpenClaw host under macOS
  **Privacy & Security > Bluetooth**.
- `BLUETOOTH_OFF`: restore macOS Bluetooth.
- Other print failure: inspect the reported message and printer condition.

After any failed or indeterminate physical attempt, stop. Do not resend or
automatically retry because the first attempt may have consumed a label. Check
the physical printer and request status before explicitly authorising another
single print.

## Separator and cutter rules

- A single `|` is a visible field separator.
- A triple `|||` is a visible manual physical-cut marker.
- Any other consecutive pipe count is invalid.
- Never treat a single pipe as a cut instruction.
- Never attempt to actuate, simulate, or control the manual cutter.

## Production boundary

`nta-dymo-tank-label` itself formats, previews, checks, and prints labels and
must not mutate Shopify. The wider Fred/OpenClaw workflow may invoke
`nta-product-barcode` before the label step solely to populate a missing variant
barcode through the canonical Shopify write-verification boundary. That upstream
write must complete and verify before a physical label print is allowed.
