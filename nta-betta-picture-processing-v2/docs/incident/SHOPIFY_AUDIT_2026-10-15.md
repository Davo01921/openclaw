# SHOPIFY READ-ONLY AUDIT — 5BT43 and 2BT23 (2026-10-15)

Agent: A3 (mutation firewall). Scope: documentation only — **no Shopify mutation was
performed**. Both resolves are read-only (`resolve` command) against the live store.

## Method

Run from `/Users/davidlo/openclaw-skills-incident-repair` on 2026-10-15 10:22 AEDT:

```
BETTA_SHOPIFY_ENV=/Users/davidlo/.openclaw/workspace/nta-betta-picture-processor/.env \
  /opt/homebrew/bin/node nta-betta-picture-processing-v2/scripts/shopify_live.mjs resolve 5BT43
BETTA_SHOPIFY_ENV=/Users/davidlo/.openclaw/workspace/nta-betta-picture-processor/.env \
  /opt/homebrew/bin/node nta-betta-picture-processing-v2/scripts/shopify_live.mjs resolve 2BT23
```

Both exited 0 with `status: RESOLVED` (fresh reads, one exact product each):

| Tank | Resolved | fetch_id | fetched_at (UTC) |
|---|---|---|---|
| 5BT43 | `gid://shopify/Product/7239072481489` | `1e55b134-27e7-4a12-aca8-2874eb1b3301` | 2026-10-14T23:05:59.143Z |
| 2BT23 | `gid://shopify/Product/7255867588817` | `e41221ef-8bac-48a4-a071-c90f84baa626` | 2026-10-14T23:06:00.486Z |

Inventory location for both: `My Home Business`
(`gid://shopify/Location/65890615505`).

## Current live state — 5BT43

- Product `gid://shopify/Product/7239072481489`; variant
  `gid://shopify/ProductVariant/41532067512529`; inventory item
  `gid://shopify/InventoryItem/43628755353809`.
- Title `5BT43 - White Turquoise Halfmoon Male`; handle `5bt43`; status `ACTIVE`;
  vendor `NTA Imports`; product type `Domesticated Betta`.
- Price `25.00`; cost `1.0` (numeric value of the receipt's `"1.00"`);
  inventory policy `DENY`, tracked, exactly one variant.
- Inventory: available `1`, on_hand `1`, committed `0` (aggregate
  `inventoryQuantity` `1`).
- Arrival date (`custom.arrival_date`): **`2026-10-09`**.
- Media (2, both `READY`):
  - `gid://shopify/MediaImage/27287081418961` — 2048×2048 PNG hero
    `…/5bt43-white-turquoise-halfmoon-male-9200747.png?v=1791735249`
  - `gid://shopify/MediaImage/27287081451729` — 1152×2048 PNG original
    `…/5bt43-white-turquoise-halfmoon-male-4590272.png?v=1791735249`

## Current live state — 2BT23

- Product `gid://shopify/Product/7255867588817`; variant
  `gid://shopify/ProductVariant/41571765453009`; inventory item
  `gid://shopify/InventoryItem/43668588003537`.
- Title `2BT23 - Black Base Red Galaxy Koi Betta Male`; handle `2bt23`; status
  `ACTIVE`; vendor `Renial`; product type `Domesticated Betta`.
- Price `35.00`; cost `15.0` (numeric value of the receipt's `"15.00"`);
  inventory policy `DENY`, tracked, exactly one variant.
- Inventory: available `0`, on_hand `0`, committed `0` (aggregate
  `inventoryQuantity` `0`).
- Arrival date (`custom.arrival_date`): **`2026-06-30`**.
- Media (2, both `READY`):
  - `gid://shopify/MediaImage/26946788753617` — 1254×1254 PNG hero
    `…/2bt23-black-base-red-galaxy-koi-betta-male-7614108.png?v=1787323567`
  - `gid://shopify/MediaImage/26952541962449` — 2048×2048 JPG original
    `…/2bt23-black-base-red-galaxy-koi-betta-male-2694250.jpg?v=1787414286`

## Comparison against the incident receipts

Sources: `tests/fixtures/incident_2bt23/evidence/5BT43-unauthorized-receipt.json`
(`nta-protected-merchandising-receipt-v1`, plan
`b691ee3b…806ece5`, verified 2026-10-14T21:54:33.683Z) and
`2BT23-repair-receipt.json` (`nta-protected-merchandising-repair-receipt-v1`,
plan `5ed84ede…1ed64c`, verified 2026-10-14T22:23:12.900Z).

| Field | Receipt record | Live 2026-10-15 | Match |
|---|---|---|---|
| 5BT43 vendor | `NTA Imports` (post-revert/repair) | `NTA Imports` | ✅ |
| 5BT43 price | `25.00` | `25.00` | ✅ |
| 5BT43 cost | `1.0` (`"1.00"`) | `1.0` | ✅ |
| 2BT23 vendor | `Renial` (repair after) | `Renial` | ✅ |
| 2BT23 price | `35.00` | `35.00` | ✅ |
| 2BT23 cost | `15.0` (`"15.00"`) | `15.0` | ✅ |

**No discrepancies found**: both products are in the state the 09:23 AEDT repair
receipt claims. The unauthorised 5BT43 merch change (offer: `Renial / 35.00 /
15.00`) is fully reverted; the 2BT23 repair stands (offer: `Renial / 35.00 /
15.00`). Numeric equality of cost/price holds; the only difference is Shopify's
display normalisation (`1.0` vs `1.00`).

Identifier cross-check: variant IDs in the receipts
(`41532067512529` for 5BT43, `41571765453009` for 2BT23) equal the live variant
IDs; product IDs equal.

## Observations recorded (no action — read-only; not silently reverted)

1. **5BT43 arrival date `2026-10-09`** matches its own archived label from the
   2026-10-10 batch photo. It was not touched by the incident or the repair.
2. **2BT23 arrival date `2026-06-30`** does *not* match the 14/10/2026 date on the
   incident photo. The incident/repair receipts only covered vendor/price/cost;
   the uploader pipeline's details/metafield step for this fish has not run.
   Flagged to the owner; **not changed by this audit**.
3. **2BT23 inventory is 0** (available/on_hand). The repair receipt did not cover
   inventory, and 0 was both the pre- and post-repair value implied by the
   receipt scope. 5BT43 inventory is 1 (from its 2026-10-10 onboarding).
4. Both products use the same standard description template on disk
   (sha256 `40f9c040a6aca922c5a246ae08eec2d6ff875a665001e87c28dc28895d67feb4`,
   4269 chars) — informational.

## Image verification (read-only, visual)

- Incident upload fixture (`tests/fixtures/incident_2bt23/incident-photo.png`)
  re-hashed: `6e4a4f573f8cfc829218f798eeb5b45cd08803689d31d7db6fce4920cdca9ca9`
  (matches the brief; `incident-photo-second-upload.png` identical). Visually
  re-confirmed: label reads **`2 BT 23`**, date **`14/10/2026`**, price `$35`.
- Archived original
  `~/Documents/Archived Bettas/2026-10-10/betta-20261010-203829-0l1v8t/Betta Processing/5BT43 Original 2026-10-10.png`
  visually assessed: label reads **`5BT 43`**, **`9/10/2026`**, `$35`.
  This is the real 5BT43 photo from the 2026-10-10 batch and directly explains
  the "5BT43 / 9 October 2026" claim Fred asserted about a different photo —
  the assertion matches this archived file, not the incident upload.

## Verdict

- Production state for both products is consistent with the repair receipt.
- No Shopify mutation was made, suggested as automatic, or hidden by this audit.
- Remaining owner decisions (out of scope here): 2BT23 arrival date/metafield and
  inventory posture if the 14/10/2026 fish is to be onboarded through the normal
  pipeline.
