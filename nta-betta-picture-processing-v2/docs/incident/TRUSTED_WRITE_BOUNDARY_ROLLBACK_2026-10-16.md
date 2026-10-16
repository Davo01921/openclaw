# TRUSTED SHOPIFY WRITE BOUNDARY — ROLLBACK / EMERGENCY STOP (2026-10-16)

Scope: what to do when the trusted write boundary must stop immediately, what
keeps working, how to recover an interrupted mutation without blind replays, and
the credential-rotation rules for break-glass. All actions here are owner-gated
(root for daemon/state changes). Symmetric document:
`TRUSTED_WRITE_BOUNDARY_MIGRATION_2026-10-16.md`.

Never delete evidence before hashing it. Receipts are HMAC-signed and are the
only authoritative record of what the daemon did.

## 1. Fail-closed emergency stop (do the flag FIRST, then the daemon)

```bash
# 1a. Immediate, persistent write stop (fail closed; reads keep working):
sudo /usr/local/bin/nta-betta-write --state-dir /var/db/nta-betta-write \
  disable --operator "owner: <short reason>"
#   or, equivalent and faster when the CLI is unavailable:
sudo touch /var/db/nta-betta-write/disabled

# 1b. Full stop of the daemon (optional, e.g. to take the boundary fully down):
sudo launchctl bootout system/com.nanotanksaustralia.betta-write

# 1c. Optional full removal (keeps state by default — see §6):
sudo deploy/uninstall-trusted-writer.sh
```

Why this order: the `disabled` flag persists across restarts, so even if the
LaunchDaemon is reloaded (`RunAtLoad`/`KeepAlive`) all writes continue to be
refused with `boundary_disabled` until the owner deliberately re-enables.
Booting out alone leaves the plist installed: the service restarts at next boot.

Expected evidence after 1a: `status` shows `"disabled": true`; a write request
returns `{"ok": false, "outcome": "REFUSED", "error_code": "boundary_disabled"}`.

## 2. What pauses, what keeps working

**Pauses (by design):**

- every Shopify mutation through the boundary (`update_details`,
  `set_inventory`, `media_append`) → refused with `boundary_disabled`;
- batch uploaders that reach the write stage → the process reports
  `AWAITING_LIVE` / `PENDING_RECONCILIATION` / quarantined per its normal
  semantics; nothing is written;
- any attempt to use the retired legacy write path → cannot authenticate at all
  (the pre-migration write credential was rotated and removed from every
  davidlo-readable file — see the migration plan P2/P3).

**Keeps working (read-only):**

- `scripts/shopify_live.mjs resolve/preflight` and pipeline preflight/readback
  via the read-only credential;
- image processing, generation, QA, intake, watcher discovery and all local
  stage transitions;
- `status`/`verify` boundary ops (read-back only) via the socket;
- archiving of batches that already hold verified receipts;
- telemetry.

## 3. Recovery after an interrupted mutation

An interruption (crash, power loss, daemon restart) between "intent persisted"
and "outcome recorded" leaves the product's request in a reconciliation-pending
state. The boundary never replays a mutation blindly.

1. Inspect state:

```bash
sudo /usr/local/bin/nta-betta-write --state-dir /var/db/nta-betta-write status
#   look for pending_reconciliations > 0; note the request_id(s)
```

2. Settle by fresh read-back with the read-only `verify` op (this is the
   daemon's designed reconciliation path: it compares the fresh Shopify state
   with the persisted intent and marks it `RECONCILED_APPLIED` or
   `RECONCILED_NOT_APPLIED`):

```bash
V=/Users/davidlo/openclaw-skills-v3/nta-betta-picture-processing-v2/.venv/bin/python
"$V" - <<'PY'
import importlib.util, json
from pathlib import Path
spec = importlib.util.spec_from_file_location(
    "bwc", Path("/usr/local/libexec/nta-betta-write/betta_write_client.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
client = mod.WriteBoundaryClient("/var/run/nta-betta-write/boundary.sock")
# product id from the batch manifest / status output:
response = client.verify({
    "product_id": "gid://shopify/Product/<ID>",
    "location_id": "gid://shopify/Location/<ID>",
}, {})
print(json.dumps(response, indent=2, sort_keys=True))
PY
```

Expected evidence: `"outcome": "VERIFIED"` with
`readback.reconciliations[*].state` in `RECONCILED_APPLIED` /
`RECONCILED_NOT_APPLIED`. `APPLIED` means the mutation did happen (a receipt
exists); `NOT_APPLIED` means it did not.

3. Re-drive through the normal batch flow only after settlement. The bindings'
   reconcile path re-sends the **identical deterministic request** (same
   manifest SHA-256, tank, operation, idempotency key); the daemon answers with
   the stored receipt for applied requests and with the stored reconciliation
   instruction for settled-not-applied ones. There is intentionally no
   automatic retry with fresh authority:

   - settled `APPLIED` → the batch converges (`VERIFIED`);
   - settled `NOT_APPLIED` → the fish stays `PENDING_RECONCILIATION` by design.
     A fresh request (new request_id + idempotency key) for a
     read-back-proven-not-applied operation is phase-2 work and must go through
     an owner authorisation record — do not improvise it by hand.

4. If the daemon was booted out: re-enable it first
   (`sudo launchctl bootstrap system /Library/LaunchDaemons/com.nanotanksaustralia.betta-write.plist`)
   while leaving the `disabled` flag in place if writes should stay off; remove
   the flag only via `… enable` when the incident is resolved.

## 4. Credential-rotation caveat / break-glass

**There is no silent re-enable of the user-side write path.** The pre-boundary
write path (agent-readable `.env` + `shopify_live.mjs`/uploader) no longer has
write credentials after migration P2/P3; that is the point of the boundary.
"Rolling back" by restoring those credentials reopens H1 (the incident vector)
and must be treated as a break-glass event, never as routine recovery.

Break-glass procedure (owner only; time-boxed; logged):

1. Record the reason and the intended action in writing (incident log / commit
   message) before doing anything.
2. Create a **new** temporary write app credential in the Shopify admin — never
   reuse the retired one.
3. Prefer performing the specific manual write **as root through the supervised
   script** in the migration plan P6 (single tank, receipts archived) over
   re-credentialing the agent path at all.
4. If — and only if — the legacy path must run: place the temporary credential
   in a 0600 file, run the specific operation, then rotate it again and delete
   the file within the same window. Record start/end times and the operator.
5. After the window: re-run migration P2/P3 checks
   (`cut -d= -f1` on the user `.env` shows read-only keys only; no
   session/token stores), and quarantine any ad-hoc scripts created.
6. File a new incident entry describing that the boundary was bypassed.

Re-enabling the boundary afterwards: `… enable` (or remove
`/var/db/nta-betta-write/disabled`), confirm `status` shows `disabled: false`,
then re-run the migration plan P6 supervised test before any batch resumes.

## 5. Evidence preservation (before any purge / uninstall)

```bash
Q=/var/db/nta-betta-quarantine-20261016
sudo mkdir -p "$Q"
sudo tar czf "$Q/boundary-state-$(date -u +%Y%m%dT%H%M%SZ).tgz" -C /var/db \
  nta-betta-write/receipts nta-betta-write/ledger \
  nta-betta-write/corrections nta-betta-write/authorisations \
  nta-betta-write/boundary-policy.json
sudo cp /var/log/nta-betta-write.out.log "$Q/nta-betta-write.out.log.$(date -u +%Y%m%dT%H%M%SZ)"
sudo cp /var/log/nta-betta-write.err.log "$Q/nta-betta-write.err.log.$(date -u +%Y%m%dT%H%M%SZ)"
sudo shasum -a 256 "$Q"/*.tgz "$Q"/*.log | sudo tee "$Q/boundary-evidence-$(date -u +%Y%m%d).sha256"
sudo chmod 600 "$Q"/*.tgz "$Q"/*.sha256
sudo chmod 700 "$Q"
```

The write credential (`/var/db/nta-betta-write/shopify.env`) is deliberately
**not** copied into the archive. Receipts and the ledger must never be pruned:
`… verify-receipt --file <receipt>` re-verifies each HMAC later.

## 6. Uninstall behaviour (what is removed / kept)

`deploy/uninstall-trusted-writer.sh` (root; `--dry-run` safe as a normal user):

- removes: LaunchDaemon + plist, installed code + `version.json`, the admin CLI
  symlink, the runtime socket dir;
- keeps by default: `/var/db/nta-betta-write` (state, receipts, ledger,
  credentials) and `/etc/sudoers.d/nta-betta-write` (a security control);
- `--remove-sudoers-hardening` removes the sudoers fragment (marker-checked);
- `--purge-state` requires `--force` and deletes the state dir **including the
  write credential and evidence receipts** — archive first per §5.

After any uninstall: the boundary is gone and the retired user-side path still
has no write credentials, so **writes remain impossible until a deliberate
re-deploy** (migration plan P5) or a documented break-glass (§4). Do not
re-create write credentials in agent-readable files to "restore service".

## NOT DONE in this workstream

No fail-closed flag, no bootout, no uninstall and no credential action was
performed by this workstream; every command above is an owner-gated runbook
item.
