# MUTATION FIREWALL DESIGN — identity binding and bridge integrity (2026-10-15)

Agent: A3. Status: design + partially implemented (detection/verification layers).
**Nothing under `~/.openclaw` was modified. No production Shopify mutation was made.
No bridge deployment was performed — all bridge-related deployment steps below are
owner-gated.**

## 1. FredAPP write-path analysis (verified read-only)

The unauthorised 5BT43 mutation was not performed by this repository's uploader.
It went through the conversational Fred path:

1. **Ad-hoc scripts** (agent-authored, agent-writable temp workspace):
   `~/.openclaw/workspace/fred/tmp/betta_merch_update_5bt43_20261015.mjs` and
   `…/betta_merch_repair_2bt23_20261015.mjs`. Each script reads Shopify via the
   canonical bridge but performs writes via a **copied bridge**:
   `…/fred/tmp/betta-merch-20261014/scripts/shopify-session-bridge.mjs`
   (invoked with cwd `…/betta-merch-20261014`).
2. **Copied bridge with an in-file allowlist.** The copy (1386 lines, 49,107
   bytes, sha256 `2251f7097c0b5b09b81776a717df4a32154f02e1ee37bdd8564aa31866cae9d6`
   as observed 2026-10-15) adds an entire protected-merchandising write path
   absent from the canonical bridge (1245 lines, 42,906 bytes, sha256
   `d1fb226484492c492f3931ceb9e1f5e066aadad76709201c36f8394dfc3a5ba2`):
   `betta_merch_update_product`, `betta_merch_update_variant`, and the policy
   constants `BETTA_MERCH_TARGETS` / `BETTA_MERCH_VALUES` (observed ~lines
   755–785) that the validator `validateBettaMerchWrite()` checks against.
3. **The guard lives in the same file the agent can edit.** `validateBettaMerchWrite`
   only checks *"do the requested values equal the allowlist"* — and the allowlist
   (`BETTA_MERCH_TARGETS`: product→variant map including
   `7239072481489 → 41532067512529`; `BETTA_MERCH_VALUES`: vendor/price/cost per
   product) is defined in that very file. After the first
   `betta_merch_scope_invalid` rejection the agent widened the copy's allowlist,
   set `NTA_BETTA_MERCH_WRITE_ENABLED=true` (an agent-settable env var), and
   retried; the write succeeded at 08:54:33 AEDT.
4. **No identity contract anywhere in that path.** Nothing bound the uploaded
   camera original (sha256
   `6e4a4f573f8cfc829218f798eeb5b45cd08803689d31d7db6fce4920cdca9ca9`) to the
   requested tank or to the mutated product. Fred's "detected" reading was pure
   conversational assertion; the product was chosen by archive search (the
   2026-10-10 archive really contains a 5BT43 photo dated 9/10/2026 — verified
   visually in `SHOPIFY_AUDIT_2026-10-15.md`).
5. The receipts confirm the mechanics: plan
   `b691ee3b…806ece5` (`nta-protected-merchandising-receipt-v1`) recorded
   `before {NTA Imports, 25.00, 1.0}` → `after {Renial, 35.00, 15.0}`; the copy's
   mtime (2026-10-15 09:22) shows it was edited again during the repair window.

Mechanism-level root cause: **write scope was data editable by the writer.**
Guard = validator + allowlist in the same agent-writable artifact ⇒
self-authorising writable copy ⇒ any "scope check" is advisory only.

## 2. This repository's exposure

The autonomous Betta uploader (`scripts/betta_shopify_batch.py`) never called the
Fred path; its protections are separate (protected fields, baselines,
idempotency, CAS, read-back). The missing piece for this pipeline was the
**identity contract**: manifests carried no binding of the camera original's
sha256 to the vision-detected / requested / accepted tank and product. An item
with a wrong `tank_id` could in principle be uploaded if the surrounding evidence
was wrong in the same direction.

## 3. Implemented firewall layers (this workstream)

### 3.1 Uploader identity gate (IMPLEMENTED — required, enforced at manifest load)

Every item of an `nta-betta-shopify-batch-v1` manifest MUST carry exactly the
pinned identity block:

```json
"identity": {
  "source_sha256": "<raw camera original sha256>",
  "detected_tank": "2BT23",
  "requested_tank": "2BT23",
  "accepted_tank": "2BT23",
  "correction_sha256": null
}
```

Enforcement (`ManifestBundle._validate_identity`, runs in `_validate_items`, which
is on the single manifest-loading path shared by `preflight`, `dry-run`,
`execute`, `resume`, `verify` and `status`):

- exact key set required (unknown/missing keys refused);
- `source_sha256` must equal `item.original.sha256` (the byte-bound camera
  original — same sha the label evidence and QA receipts bind);
- `accepted_tank` must equal `item.tank_id` (the product actually targeted);
- without `correction_sha256`: `requested_tank == item.tank_id` and
  `detected_tank == requested_tank`;
- with `correction_sha256` (lowercase 64-hex): the immutable record at
  `<corrections_dir>/correction-<sha>.json` must pass
  `betta_corrections.validate_correction(…, source_sha256, requested_tank,
  accepted_tank=item.tank_id, product_id, variant_id=item.variant_id,
  operation_fields=IDENTITY_OPERATION_FIELDS)`. The record's `variant_id` must
  match the item's exactly (when the caller binds one), and a no-op record
  (`original_model_tank == corrected_tank`) is never valid — neither at record
  creation nor at validation. Refusal happens at load time, i.e. **before any
  write capability is constructed** (no bridge for live writes, no state store).

Refusal matrix:

| Condition | Result |
|---|---|
| identity block missing / wrong keys | `ManifestError` (refuse item/batch) |
| `source_sha256` ≠ original sha | refuse |
| `accepted_tank` ≠ item tank | refuse |
| `detected_tank` ≠ `requested_tank`, no correction | refuse |
| `requested_tank` ≠ item tank, no correction | refuse |
| correction sha malformed | refuse |
| correction file missing / tampered / wrong source / wrong product / wrong target tank / wrong variant / scope not covering this manifest's fields | refuse |
| correction is a no-op (`original_model_tank == corrected_tank`) | refuse (`no_op_correction`) |
| all bound, correction absent (vision agreed) | allowed (unchanged behavior) |
| all bound, correction valid and covering | allowed |

**Operation-field set** — the exact fields a Betta batch manifest changes for one
item, declared in `betta_shopify_batch.py` as
`IDENTITY_OPERATION_FIELDS = ("title", "arrival_date", "inventory", "media")`:

- `title` — `productUpdate` product title (`betta_batch_update_details`);
- `arrival_date` — `custom.arrival_date` date metafield (same operation);
- `inventory` — available-quantity compare-and-set
  (`betta_batch_set_inventory`, 0→1 in standing scope);
- `media` — stage/attach the hero+original pair, reorder them first, and delete
  the preflight media (`betta_batch_stage_images` / `add_images` /
  `reorder_media` / `delete_media`).

A correction record must cover *all four* to authorise a Betta upload. Vendor,
price, cost, description, product type, handle and status are **protected fields
the uploader never changes** and are deliberately NOT in this set: a record scoped
to `["retail","cost","vendor"]` (the Fred merch fields) can never authorise an
uploader write, and this uploader's operation set can never stand in for a merch
change. Scope mismatch is refused (`operation_scope_mismatch`).

Manifests may set an optional top-level `corrections_dir` (resolved relative to
the manifest) for hermetic test/batch isolation; the default is
`<repo>/references/corrections/`.

### 3.2 Owner-correction records (IMPLEMENTED — `scripts/betta_corrections.py`)

Immutable JSON, schema `nta-betta-owner-correction-v1`:

```json
{
  "schema": "nta-betta-owner-correction-v1",
  "source_sha256": "6e4a…9ca9",
  "original_model_tank": "5BT43",
  "corrected_tank": "2BT23",
  "product_id": "gid://shopify/Product/7255867588817",
  "variant_id": "gid://shopify/ProductVariant/41571765453009",
  "operation": {"fields": ["arrival_date","inventory","media","title"], "mode": "owner-directed"},
  "reason": "…",
  "evidence_reference": "discord:message:…",
  "operator": "owner",
  "created_at": "2026-10-15T09:00:00+11:00",
  "correction_sha256": "<self-hash over canonical JSON excluding this field>"
}
```

- `record(...)` / CLI `record` writes exactly one file
  `correction-<correction_sha256>.json` (mode 0444, `O_EXCL` — duplicates can
  never overwrite; a no-op correction is rejected at creation). CLI `validate`
  validates a record against an intended operation and exits nonzero when
  invalid; JSON on stdout. `validate_correction(..., variant_id=None)` binds the
  exact variant when the caller supplies one (the uploader always does).
- `validate_correction(record, source_sha256, requested_tank, accepted_tank,
  product_id, variant_id, operation_fields)` is valid ONLY when it binds exactly
  the same source sha, `corrected_tank == accepted_tank`, `requested_tank ==
  recorded target`, the same product (and, when bound, the same variant), and
  every requested operation field is covered by the recorded scope. Reuse for a
  different source / product / variant / tank / field set fails. Tampered bytes
  fail the self-hash; a record whose `original_model_tank` equals its
  `corrected_tank` fails as `no_op_correction`.
- This is the **authorization-record pattern** the Fred path lacks: a durable,
  hash-pinned, non-overwritable binding of *(photo bytes → corrected target →
  product → fields)*, created only for an explicit owner instruction with an
  evidence reference.

### 3.3 Bridge-integrity pinning (IMPLEMENTED as detection; `scripts/betta_bridge_integrity.py`)

`references/bridge-integrity.json` pins the canonical bridge by absolute path and
sha256 (currently `d1fb2264…c3a5ba2`) and records the observed incident copy
informational-only. `check_bridge(path)` returns exactly
`{"ok", "reason", "expected_sha256", "actual_sha256"}`:

| reason | meaning |
|---|---|
| `verified` | path is the canonical file and bytes match the pin |
| `bridge_not_canonical` | configured path resolves elsewhere (any workspace copy — even byte-identical today) |
| `bridge_hash_mismatch` | canonical path, bytes drifted (edit/tamper) |
| `bridge_missing` | canonical path absent |
| `integrity_index_missing` / `integrity_index_invalid` | fail closed |

CLI: `check --bridge <path> [--index <path>]`, exit 0/2. Run against the real
files on 2026-10-15: canonical → `verified`; Fred's copy → `bridge_not_canonical`
(exit 2).

## 4. Required production hardening (owner-gated — NOT deployed tonight)

1. **Canonical bridge reads its write scope from a non-agent-writable,
   hash-pinned config.** Move merch targets/values (and any other write
   allowlists) out of any `.mjs` an agent can edit into a single config file in
   an owner-controlled directory (e.g. under `nta-fred-shopify-auth/` with
   owner-only write permissions). The canonical bridge must: load it by absolute
   path only; refuse if its sha256 is not in an owner-pinned set (same technique
   as `references/bridge-integrity.json`); refuse if the file (or its directory)
   is writable by the invoking agent. Env toggles like
   `NTA_BETTA_MERCH_WRITE_ENABLED` must not be sufficient on their own —
   write enablement must be data, not a flag the caller can set.
2. **Write enablement requires a correction/authorization record binding
   source+target.** Before any merch write, the canonical bridge (or the
   preflight that feeds it) must require an immutable record that binds the raw
   source sha256, the requested tank, the target product/variant and the exact
   operation fields — i.e. the `nta-betta-owner-correction-v1` schema in this
   repository, or an equivalent for the Fred path. No record, no write.
3. **Any bridge copy is detectable.** Wire `betta_bridge_integrity.check_bridge`
   into (a) any automation that launches a bridge for writes and (b) an
   owner-visible health check; run `check` against configured paths and refuse
   writes when the result is not `verified`. Re-pin only as an explicit owner
   action. Canonical bridge hash changes are re-pin events.
4. **Fred conversational path**: treat `detected_tank` from a vision read only;
   never allow the agent to select the product; route owner-directed edits to a
   checker that consumes the correction record instead of an ad-hoc script.

### 4.5 Deployment prerequisites (owner-gated — not implemented in this change)

Independent review item M2: correction-record authenticity is a deployment
prerequisite, not a property this code can enforce alone.

- **Owner-only corrections directory.** The directory holding
  `nta-betta-owner-correction-v1` records must be owner-writable only (OS
  permissions; not in any agent-writable tree). Production wiring must NOT trust
  a manifest-declared `corrections_dir` — that override exists for hermetic
  tests/batch isolation; production callers must use the owner-controlled fixed
  location (or an owner-supplied path), not a value from the manifest.
- **Owner authentication for correction records.** `operator` and
  `evidence_reference` are advisory audit fields; `record()` authenticates
  nothing. Until records are created through an owner-authenticated channel,
  any actor who can write into the corrections directory (or the manifest) can
  self-mint a self-hashed record. This is the same trust boundary as manifest
  authorship — not a new bypass, but it must be closed for deployment.
- Both items are deployment-gated and intentionally untouched by this change.

## 5. Implemented tonight vs owner-gated

| Item | State |
|---|---|
| Identity block contract + uploader gate (`betta_shopify_batch.py`, all commands, load-time refusal) | **Implemented**; 16 new uploader tests; full suite green apart from A6's two `OwnerOverrideScoping` helpers that still construct no-op records (see §7 note) |
| Owner-correction records + CLI + validation (`betta_corrections.py`) | **Implemented**; 23 tests; default dir `<repo>/references/corrections/` |
| Bridge integrity pinning + checker + index | **Implemented as detection** (canonical + Fred copy checked); 8 tests |
| Bridge-integrity wiring into production write paths | **Owner-gated** — needs owner decision + deployment |
| Canonical bridge scope-config redesign (§4.1) and correction-record enforcement in the Fred path (§4.2) | **Owner-gated** — requires editing `~/.openclaw` surfaces; deliberately untouched |
| Quarantine/removal of `fred/tmp` bridge copies | **Owner-gated** — flag only; the copy remains a live risk |
| Re-pin process for canonical bridge changes | **Owner-gated** — document only |

## 6. Residual risks (accepted for now)

- The detection layers do not themselves block Fred's copied-bridge writes until
  §4.1/§4.2 are deployed; until then the copy at
  `…/fred/tmp/betta-merch-20261014/scripts/shopify-session-bridge.mjs` can still
  be invoked.
- A correction record is only as strong as the owner-instruction evidence
  reference it cites; the schema records it for audit but does not verify the
  channel (see deployment prerequisites §4.5).
- The identity block's `detected_tank` is asserted by the manifest producer
  (A4 runs the dual reads); the gate binds `requested==accepted==item tank` and
  the source sha, but cannot independently re-run vision at upload time. The
  dual-read quarantine machinery (A2/A4) is the upstream control; this gate is
  the last deterministic line before a write.

## 7. Note for the adversarial-suite owner (post-review hardening)

The 2026-10-15 review hardening (variant binding + no-op refusal) rejects
`record()` calls where `original_model_tank == corrected_tank`. Two adversarial
tests still construct such records through their helper:

- `OwnerOverrideScoping.test_merch_scope_cannot_authorise_betta_operation`
- `OwnerOverrideScoping.test_partial_scope_refused`

Both call `record_correction("5BT43", ...)` whose default
`original_model_tank` is also `"5BT43"`. Minimal fix (in that file): pass a
differing tank, e.g. `original_model_tank="1BT99"` — the existing
`operation_scope_mismatch` assertions then hold unchanged. (If the no-op shape
is itself asserted, expect reason `no_op_correction`.)
