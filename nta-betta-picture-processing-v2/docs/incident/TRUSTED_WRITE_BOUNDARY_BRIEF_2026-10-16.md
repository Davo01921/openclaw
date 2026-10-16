# TRUSTED SHOPIFY WRITE BOUNDARY — implementation brief (2026-10-16)

Single source of truth for the boundary implementation agents. Read fully before acting.

## Objective

Close the H1 vulnerability: the FredAPP agent (running as macOS user `davidlo`) must
be **structurally unable** to authorise its own Shopify product mutations. Write
capability moves behind a root-owned, code-pinned daemon that independently validates
every request. Read-only discovery and image processing stay available to agents.

## Verified environment facts (recon, 2026-10-16)

- Fred runs as `davidlo` (uid 501, admin). **Non-interactive `sudo` requires a
  password** (`sudo -n true` → rc 1). Root-owned components are therefore a real OS
  boundary, subject to the **5-minute sudo timestamp window** after a manual sudo
  (deployment hardening: root-owned `/etc/sudoers.d` entry with `timestamp_timeout=0`).
- Keychain is **not** a boundary (a plain shell read of the `nta-betta-xai` item
  succeeds). Root-only files are.
- The OpenClaw runtime (`/opt/homebrew/lib/node_modules/openclaw`) is agent-writable;
  **no enforcement may live in agent-writable code, interpreters or dependencies**.
- Betta Shopify **client credentials are currently readable by the agent** in
  `~/.openclaw/workspace/nta-betta-picture-processor/.env` (0600 davidlo), used by the
  canonical bridge and `shopify_live.mjs`/`betta_bindings.py` (client-credentials
  exchange at `/admin/oauth/access_token`; session/refresh tokens persist under the
  project's `prisma/` area). Further agent-readable Shopify credential sets exist in
  other projects' `.env` files (shipstation-sync, aqua-premium, internal-finance) —
  catalogue + report only, out of this boundary's scope.
- Canonical bridge (`nta-fred-shopify-auth/.../shopify-session-bridge.mjs`, 0600
  davidlo) exposes batch ops: product details, preflight, update details, set
  inventory, stage/add images, reorder/delete media — with in-file guards. An
  agent-writable copy (with merch ops) was the incident vector.

## Architecture (pinned)

```
davidlo processes (Fred / watcher / pipelines)
        │  JSON-line request over UNIX socket
        ▼
/var/run/nta-betta-write/boundary.sock        (dir root:wheel 0711, socket 0660 root:davidlo)
        ▼
com.nanotanksaustralia.betta-write  (LaunchDaemon, root)
  exec: /usr/bin/python3  (Apple-owned, stdlib only, Python 3.9-compatible)
  code: /usr/local/libexec/nta-betta-write/{betta_write_boundary.py,
        betta_write_daemon.py} + version.json (root-owned, hash-pinned)
  state: /var/db/nta-betta-write/  (root:wheel 0700)
    shopify.env              # client id/secret/store — 0600 root; the ONLY write credential
    boundary-policy.json     # root-owned hard caps (operations, batch roots, budgets)
    corrections/  authorisations/  ledger/  receipts/  signing.key(0600)  disabled(flag)
  cli: /usr/local/bin/nta-betta-write  (admin: status/authorise/enable/disable/verify-receipt; root via sudo)
```

Rules that make it a real boundary (enforce in code + tests):
1. **Privilege path contains only root/Apple-owned code**: daemon interpreter is
   `/usr/bin/python3`; daemon imports only stdlib; the repo copy is a REVIEW source —
   the installer snapshots it root-owned and records SHA-256s in `version.json`.
   A changed repo file never changes daemon behaviour until a new (sudo) install.
2. **Environment variables never widen authority**: policy and credentials are read
   only from root-owned files; env vars are ignored for decisions. Tests must set
   hostile env vars and prove no effect.
3. **Peer identity**: daemon accepts connections only from configured uids
   (`allowed_uids`, default `[501]`; root allowed for admin ops). SO_PEERCRED locally.
4. **Every request validated fail-closed** (see pipeline below); refusals are
   deterministic error codes, no partial state.
5. **Receipts** are written root-owned and HMAC-signed with `signing.key`; responses
   carry the receipt + signature so requesters can archive them; `verify-receipt`
   admin op re-verifies later.

## Request protocol (pinned)

JSON line + `\n`; response JSON line. Schemas:

request:
```json
{"schema":"nta-betta-write-request-v1","request_id":"<uuid4>","operation":"<op>",
 "mode":"apply"|"dry_run",
 "authorisation":{"kind":"standing"} |
                {"kind":"owner","authorisation_sha256":"<hex>"},
 "target":{"product_id":"gid://shopify/Product/…","variant_id":"gid://shopify/ProductVariant/…",
           "inventory_item_id":"gid://shopify/InventoryItem/…","location_id":"gid://shopify/Location/…"},
 "evidence":{"manifest_path":"/abs/path/under allowed root","manifest_sha256":"<hex>",
             "source_sha256":"<hex>","identity":{...the 5-key block...},
             "correction_sha256":"<hex>|null","qa_receipt_sha256":"<hex>|null",
             "idempotency_key":"<hex|string>"},
 "operations":[{"type":"update_details","title":"…","arrival_date":"YYYY-MM-DD",
                "expected":{"title":"…","arrival_date":"…"}},
               {"type":"set_inventory","quantity":1,"reason":"received",
                "expected":{"available":0,"inventory_item_id":"…","location_id":"…"}},
               {"type":"media_append","assets":[{"path":"…","sha256":"…","role":"hero"},
                                                {"path":"…","sha256":"…","role":"original"}]},
               {"type":"merch_update","vendor":"…","price":"…","cost":"…",
                "expected":{"vendor":"…","price":"…","cost":"…"}}]}
```
response:
```json
{"schema":"nta-betta-write-response-v1","ok":true|false,"outcome":"APPLIED|DRY_RUN|VERIFIED|REFUSED|RECONCILIATION_REQUIRED",
 "receipt":{...},"receipt_sha256":"…","receipt_signature":"hmac-sha256:…",
 "error_code":null|"<code>","detail":"…","readback":{...on verify...}}
```
receipt core (root copy + response): schema `nta-betta-write-receipt-v1`; request_id,
operation summary, target, evidence hashes, authorisation reference, before/after
(price/cost/vendor/inventory/title/arrival/media ids), checks, created_at, daemon
version hash.

## Operation set v1 (port semantics from the canonical bridge; do not invent)

- `status` (no auth), `verify` (readback only).
- `update_details`: only `title` and metafield `arrival_date`; CAS via `expected`.
- `set_inventory`: quantity ∈ policy `inventory.allowed_from → target` (default 0→1);
  reason ∈ {"received","correction"}; CAS via `expected`; idempotency key required;
  never touches price/cost/vendor.
- `media_append`: hero first, then original, appended ahead of existing media;
  asset path must be under an allowed root; sha256 + mime (png/jpeg) + size cap
  validated by hashing the file as root; duplicates refused by alt/sha convention.
- `merch_update` (vendor/price/cost): **owner authorisation required** (no standing
  mode); fields must ⊆ authorisation scope; CAS via `expected`; this is the incident's
  operation class — by construction redeemable only against an owner record.
- Not in v1 (leave to the existing bridge until later phases; document): reorder,
  delete media, extra image sets.

## Validation pipeline (order, fail-closed, each with a distinct error code)

1. peer uid allowed → else `peer_not_allowed`
2. schema/JSON valid, request_id uuid → else `bad_request`
3. daemon not disabled (`disabled` flag) → else `boundary_disabled`
4. operation known + allowed by root policy → else `operation_not_allowed`
5. replay/duplicate: request_id seen → return the stored receipt for identical
   request hash, else `replay_rejected`; idempotency_key uniqueness per target+op →
   else `duplicate_operation`
6. authorisation: standing → policy must authorise autonomous mode for this op;
   owner → authorisation record must exist in root `authorisations/`, self-hash valid,
   unused (single-use ledger), not expired, and bind source_sha/product/variant/fields
   exactly → else `authorisation_invalid`
7. evidence: manifest path under allowed root + sha matches bytes; identity block
   matches target product/variant + source binding + accepted==requested==item tank;
   correction valid when `detected_tank != requested_tank` (reuse
   `nta-betta-owner-correction-v1` validation semantics; corrections dir root-owned)
   → else `evidence_invalid` / `correction_invalid`
8. operations ⊆ policy caps (field allowlists, inventory rule, budgets:
   `max_operations_per_request`, per-day counters in root ledger) → else `policy_refused`
9. fresh pre-write snapshot (daemon-side read); CAS against `expected` → else
   `baseline_drift`
10. apply (idempotent per op), fresh read-back; receipt written root-owned, HMAC
    signed; on crash/interruption: state marked `RECONCILIATION_REQUIRED`; a re-sent
    identical request returns the stored reconciliation instruction — never replays a
    mutation blindly (mirror the uploader's resumed-mutation semantics).

## Client API (pinned — R1 implements, R2 consumes)

`scripts/betta_write_client.py` (stdlib only; used by davidlo processes):
```python
class WriteBoundaryClient:
    def __init__(self, socket_path: str, timeout: float = 30.0): ...
    def request(self, payload: dict) -> dict           # full response dict
    def status(self) -> dict
    def verify(self, target: dict, evidence: dict) -> dict
    def build_request(self, *, operation, mode, target, evidence, operations,
                      authorisation, request_id=None) -> dict  # helper incl. uuid
```

## Integration (R2, additive, default-off)

`scripts/betta_bindings.py`: optional `trusted_writer_socket` option; when set, the
execute/reconcile runners route write operations through the client (mapping the
uploader's op set: update details → update_details, inventory → set_inventory,
media hero/original → media_append; verify → verify) and REFUSE anything unmapped
(reorder/delete stay on the old path until phase 2 — the flag is opt-in per run).
Default (unset) behaviour must remain byte-for-byte the current bridge path.
Preserve the running watcher: no config changes in this workstream.

## Tests (hermetic; none may need root)

- Core logic: policy intersection, identity/evidence binding, corrections, replay,
  authorisation single-use, field scoping, budgets, receipt signing.
- Daemon integration: spawn the daemon module in-process/subprocess on a TEMP socket
  with temp state dirs, fake uid provider injection, and an injectable Shopify HTTP
  layer (fake server; urllib). Production default stays /usr/bin/python3 + fixed paths.
- Attack classes (adversarial suite by R3, but R1/R2 include basics): edited
  repo/bridge copy has no effect; hostile env vars ignored; forged corrections;
  modified manifests; wrong product targets; replay; interrupted mutation; no
  credential disclosure via any op; `disabled` flag fails closed.
- The 605-test existing suite must stay green (plus the new tests).

## Deliverables

- R1: `scripts/betta_write_boundary.py`, `scripts/betta_write_daemon.py`,
  `scripts/betta_write_client.py`, `scripts/betta_write_admin.py`,
  `tests/test_betta_write_boundary.py`; design doc
  `docs/incident/TRUSTED_WRITE_BOUNDARY_DESIGN_2026-10-16.md` (architecture, threat
  model incl. the sudo-timestamp and GUI-phishing residuals, op mapping).
- R2: `deploy/install-trusted-writer.sh`, `deploy/uninstall-trusted-writer.sh`,
  `deploy/com.nanotanksaustralia.betta-write.plist.template`,
  `deploy/nta-betta-write.sudoers.template`,
  `docs/incident/TRUSTED_WRITE_BOUNDARY_MIGRATION_2026-10-16.md`,
  `docs/incident/TRUSTED_WRITE_BOUNDARY_ROLLBACK_2026-10-16.md`,
  `scripts/betta_bindings.py` (additive), `tests/test_betta_write_boundary_bindings.py`.
- R3 (after R1/R2): `tests/test_betta_write_boundary_adversarial.py`,
  `docs/incident/INDEPENDENT_REVIEW_TRUSTED_WRITE_2026-10-16.md` with GO/NO-GO.

## Hard rules for all agents

- Work only in `/Users/davidlo/openclaw-skills-trust-boundary` (branch
  `codex/betta-trusted-write-boundary-20261016`); no git commits/pushes; master commits.
- **No deployment**: never run installers with sudo, never touch `/var/db`, `/etc`,
  `~/Library/LaunchAgents`, `~/.openclaw`; no production Shopify writes (the daemon's
  Shopify layer is faked in tests).
- Do not print, log or commit secret values from any `.env`; recon facts above are
  redacted already.
- Keep the daemon Python 3.9-compatible and stdlib-only.
- Do not modify files owned by other agents; note seam issues in your report instead.
