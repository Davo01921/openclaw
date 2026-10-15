# Fixtures — incident 2BT23 (P1 misidentification, 2026-10-15)

Provenance for every byte used by
`tests/test_betta_incident_2bt23.py`. All shas are SHA-256.

## Byte-immutable incident uploads (never modify)

| File | sha256 | Bytes | Origin |
|---|---|---|---|
| `incident-photo.png` | `6e4a4f573f8cfc829218f798eeb5b45cd08803689d31d7db6fce4920cdca9ca9` | 2,936,221 | The owner's genuine Discord upload #1, staged `openclaw-staged-226ab65c-…/input-dji_export_photo_20261014154253374---14b28048….png` (forensics §1.2). Visibly reads `2 BT 23` / `14/10/2026` / `$35`. |
| `incident-photo-second-upload.png` | `6e4a4f573f8cfc829218f798eeb5b45cd08803689d31d7db6fce4920cdca9ca9` | 2,936,221 | The owner's second upload (09:24:40), byte-identical to the first (forensics §1.2). |

Both are **byte-immutable**: the repair workstream must never modify, re-encode
or overwrite them. `tests/test_betta_incident_2bt23.py` re-hashes them on every
run and fails on any drift.

## Near-confusion photo (verbatim copy)

| File | sha256 | Bytes | Origin |
|---|---|---|---|
| `near-confusion-5bt43-original.png` | `6c1d0e92004f5170c23797e7da5aabb11d72daade97f418308fc679fd6a15ecc` | 2,714,532 | Verbatim copy of `/Users/davidlo/Documents/Archived Bettas/2026-10-10/betta-20261010-203829-0l1v8t/Betta Processing/5BT43 Original 2026-10-10.png` (copied 2026-10-15 by A5; `cp` only, no re-encode). Visibly reads `5BT 43` / `9/10/2026` / `$35`. This is the archived file Fred's "5BT43 / 9 October 2026" claim actually matches (forensics §3.3, Shopify audit). |

## Evidence receipts (read-only for this suite)

| File | sha256 | Bytes |
|---|---|---|
| `evidence/2BT23-repair-receipt.json` | `3aba10fe8dcd71c3cf11fdf26077fded7eeedc9e95056cddd85a01ddc6818b2c` | 1,114 |
| `evidence/5BT43-unauthorized-receipt.json` | `41d982c87bd54f6b950f3c7b4c3588d2a1230f5c1902cacebf059c5c61b848e3` | 629 |

These two receipts are the incident's real Shopify mutation receipts; the
regression suite reads them but never rewrites them.

## Rules

1. The two incident PNGs are **byte-immutable** — never modify or overwrite.
2. `near-confusion-5bt43-original.png` is a verbatim archival copy for the
   confusion/concurrency tests; do not edit it either.
3. New fixtures for this incident must be added by the agent that owns this
   directory (A5) and documented here with path, sha and provenance.
