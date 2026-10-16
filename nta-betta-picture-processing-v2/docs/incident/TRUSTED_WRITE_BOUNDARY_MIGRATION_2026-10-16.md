# TRUSTED SHOPIFY WRITE BOUNDARY — STAGED MIGRATION PLAN (2026-10-16)

**STATUS: NOT DEPLOYED — NOTHING IN THIS DOCUMENT IS DONE.**
This workstream produced reviewable artefacts only. No installer was executed;
nothing under `/var`, `/etc`, `/Library/LaunchDaemons`, `~/.openclaw` was
created, modified or removed. Every step below is **owner-gated** and must be
performed deliberately by the owner (`davidlo`, uid 501, admin — with root via
`sudo`). Steps are ordered; do not re-order them.

Related documents:

- `TRUSTED_WRITE_BOUNDARY_BRIEF_2026-10-16.md` — pinned architecture/protocol.
- `TRUSTED_WRITE_BOUNDARY_ROLLBACK_2026-10-16.md` — emergency stop + break-glass.
- R1 design doc `TRUSTED_WRITE_BOUNDARY_DESIGN_2026-10-16.md` (in flight at the
  time of writing; check it exists before deployment).

## Artefact inventory (this workstream)

| Path | State |
|---|---|
| `scripts/betta_write_boundary.py`, `betta_write_daemon.py`, `betta_write_client.py`, `betta_write_admin.py` | R1 core; on disk, review before install (hash-pinned by the installer) |
| `scripts/betta_bindings.py` | R2 additive integration; default path unchanged; boundary path opt-in per run |
| `tests/test_betta_write_boundary_bindings.py` | R2 tests (mapping, fail-closed, seam against R1 validators, deploy artefacts) |
| `deploy/install-trusted-writer.sh` | root-gated installer; `--dry-run` safe as a normal user |
| `deploy/uninstall-trusted-writer.sh` | root-gated uninstaller; state kept by default |
| `deploy/com.nanotanksaustralia.betta-write.plist.template` | LaunchDaemon template (absolute root-owned paths) |
| `deploy/nta-betta-write.sudoers.template` | `Defaults:davidlo timestamp_timeout=0` hardening |
| `deploy/boundary-policy.production.json` | conservative root policy (passes R1's `validate_policy`; asserted in tests) |

## Step 0 — preflight (expect the pre-migration state)

```bash
cd /Users/davidlo/openclaw-skills-trust-boundary/nta-betta-picture-processing-v2

ls -l /usr/local/libexec/nta-betta-write 2>/dev/null || echo "boundary: not installed"
sudo launchctl print system/com.nanotanksaustralia.betta-write 2>&1 | head -2
#   expected: "Could not find service"

stat -f '%Sp %Su %N' ~/.openclaw/workspace/nta-betta-picture-processor/.env
#   expected: 0600 davidlo  (permissions only — NEVER print the contents)

deploy/install-trusted-writer.sh --dry-run
#   expected: full plan, rc 0, "DRY RUN complete … NO changes were made"
```

Evidence to record: the four outputs; a note of which Shopify apps/credentials
currently exist (from the admin UI, values never written down here).

## Ordering rationale (why this sequence)

1. **Read path first (P1):** agents keep discovering/reading products while the
   write path is dismantled. The read-only credential exists before anything
   else changes, so "reads keep working" is never at risk.
2. **Rotate the write secret before touching agent-readable stores (P2):** the
   new secret must never exist in a davidlo-readable file. Rotating first makes
   the old reader copies worthless immediately.
3. **Then remove write creds from the user `.env` + retire token stores (P3):**
   with the new secret not yet placed anywhere readable, the legacy write path
   dies here. That is why the boundary must not be flipped before P5/P6: from
   P3 until P6 the only correct writer is the (not yet installed) daemon.
4. **Quarantine the incident artefacts (P4) before installation:** bridge copies
   are the H1 vector; they are inert once P2/P3 land, but quarantining *before*
   the boundary exists keeps the risk window closed even if the install is
   deferred.
5. **Install (P5) then supervised verification (P6), then flip (P7):** the flip
   is a deliberate code/config change (agents cannot make it). Post-flip
   monitoring (P8) is a separate checkpoint so a bad flip can be attributed.

## PREREQUISITES (owner, in order — all NOT DONE)

### P1. Create/confirm a READ-ONLY Shopify app credential for the agent read paths — NOT DONE

- Shopify admin → Apps → Develop apps → create (or confirm) an app for reads,
  scopes: read products only (the read paths are `shopify_live.mjs`
  `resolve`/`preflight` and the pipeline's preflight). Install it and take the
  client id/secret.
- Write those values into the agent-readable env file used by the read path
  (`~/.openclaw/workspace/nta-betta-picture-processor/.env`) — this file becomes
  **read-only-credential only** after P3. Edit it in an editor, never via argv
  (shell history leaks arguments).

Expected evidence:

```bash
cut -d= -f1 ~/.openclaw/workspace/nta-betta-picture-processor/.env   # KEYS only
#   expected: only read-only app settings + non-credential settings
node scripts/shopify_live.mjs preflight
#   expected: {"ok":true,...,"capabilities":["authenticate","fresh_resolve"]}
```

Shopify admin must show the app's access scope as read-only. Do not probe
writes with this credential.

### P2. Rotate the Betta write client secret; hold it for the root state dir only — NOT DONE

- In the Shopify admin, rotate the write app's client secret (recommended: keep
  a dedicated write app for the boundary, separate from the read app of P1).
  Rotating invalidates the old secret; the old reader copies become useless.
- Keep the new secret in a password manager only. **Do not place it in any
  davidlo-readable file yet.** It is installed at P5 into
  `/var/db/nta-betta-write/shopify.env` (root:wheel 0600, contents never read by
  the installer).

Expected evidence: rotation confirmation in the admin UI; no command output
here (never echo the secret). Record only *when* it was rotated.

### P3. Remove write credentials from the user `.env` + retire user-readable session/token stores — NOT DONE

- Edit `~/.openclaw/workspace/nta-betta-picture-processor/.env` so it contains
  only the P1 read-only credential set (remove the write app id/secret).
- Locate and remove the user-readable session/refresh token stores from the
  client-credentials flow (the brief: tokens persist under the project's
  `prisma/` area). Enumerate first, then hash + quarantine (P4 procedure):

```bash
find ~/.openclaw/workspace/nta-fred-shopify-auth -maxdepth 4 \
  \( -name '*session*' -o -name '*token*' \) -print
```

Expected evidence:

```bash
cut -d= -f1 ~/.openclaw/workspace/nta-betta-picture-processor/.env   # KEYS only
#   expected: no write-app credential keys remain
node scripts/shopify_live.mjs resolve 2BT12
#   expected: {"ok":true,"status":"RESOLVED",...} (read path still works)
ls ~/.openclaw/workspace/nta-fred-shopify-auth/nta-betta-picture-processor/prisma 2>/dev/null
#   expected: no session/token store for the retired write credential
```

From this point until P6, do **not** run any Betta write pipeline.

### P4. Purge/quarantine the agent-writable bridge copies — NOT DONE

Known incident artefacts (from `P1_FORENSICS_2026-10-15.md` /
`INDEPENDENT_REVIEW_2026-10-15.md`; hash **before** any move):

| # | Path | Recorded SHA-256 (bridge copy) |
|---|---|---|
| 1 | `~/.openclaw/workspace/fred/tmp/betta-merch-20261014/` (whole tree; `scripts/shopify-session-bridge.mjs`) | `2251f7097c0b5b09b81776a717df4a32154f02e1ee37bdd8564aa31866cae9d6` (mtime 2026-10-15 09:22:52) |
| 2 | `~/.openclaw/workspace/fred/tmp/betta_merch_update_5bt43_20261015.mjs` | `6fb0b9931845ff724707cd9d7b60907076d82bd3ca87a7bcdcfd287a1f11da59` |
| 3 | `~/.openclaw/workspace/fred/tmp/betta_merch_repair_2bt23_20261015.mjs` | `d1f7ff288b77f3a719c063b4b701cdc223fe34f9017dee7e8c5aab6e709d1e84` |
| 4 | `~/.openclaw/workspace/fred/tmp/betta_merch_update_20261014.mjs` | not recorded in forensics — hash at quarantine time |
| 5 | `*.before-*` backups and any other `*before*` files under `~/.openclaw/workspace/fred/tmp/` (expected set; the review names the `.before-*` backups) | enumerate + hash at quarantine time; confirm the full list with the owner before moving |
| 6 | `~/.openclaw/workspace/fred/tmp/receipts/` (incident EVIDENCE — preserve, do not delete) | copy, do not move/tamper |

Quarantine (root-owned, outside every agent-writable tree):

```bash
Q=/var/db/nta-betta-quarantine-20261016
sudo mkdir -p "$Q/2026-10-16"
sudo chmod 700 "$Q"

# enumerate, hash, then move — every hash recorded BEFORE the move
find ~/.openclaw/workspace/fred/tmp -maxdepth 6 \
  \( -name 'betta-merch-20261014' -o -name 'betta_merch_*.mjs' -o -name '*before*' \) \
  -print | sort | sudo tee "$Q/2026-10-16/quarantine-list.txt"
while read -r p; do shasum -a 256 "$p"; done < "$Q/2026-10-16/quarantine-list.txt" \
  | sudo tee -a "$Q/2026-10-16/quarantine-list.txt"

sudo cp -Rp ~/.openclaw/workspace/fred/tmp/receipts "$Q/2026-10-16/fred-tmp-receipts-2026-10-16"
# move each enumerated path (repeat per path):
sudo mv "<path>" "$Q/2026-10-16/"
```

Expected evidence: quarantine list contains the three recorded SHA-256s exactly
(1–3 above); `ls ~/.openclaw/workspace/fred/tmp/betta-merch-20261014` → "No such
file or directory"; `~/.openclaw/workspace/fred/tmp/receipts` first copied then
removed from the agent workspace. The canonical bridge
`~/.openclaw/workspace/nta-fred-shopify-auth/nta-betta-picture-processor/scripts/shopify-session-bridge.mjs`
is left in place as the phase-2 reference but is now inert (P2/P3 removed its
credentials and token stores).

## INSTALL & VERIFY (owner, root)

### P5. Install the boundary — NOT DONE

```bash
cd /Users/davidlo/openclaw-skills-trust-boundary/nta-betta-picture-processing-v2

deploy/install-trusted-writer.sh --dry-run        # review as a normal user
sudo deploy/install-trusted-writer.sh             # install
# optional, owner consent required (closes the 5-minute sudo window):
sudo deploy/install-trusted-writer.sh --upgrade --consent-timestamp-timeout
```

Create the write credential file (owner only; **never** via the installer, never
in argv/history; contents are never printed):

```bash
sudo /usr/bin/install -o root -g wheel -m 600 /dev/null /var/db/nta-betta-write/shopify.env
sudo /usr/bin/pico /var/db/nta-betta-write/shopify.env   # paste the P2 rotated write settings
sudo chmod 600 /var/db/nta-betta-write/shopify.env
```

Expected evidence:

```bash
sudo ls -la /usr/local/libexec/nta-betta-write
#   expected: 4 .py + version.json, root wheel; 0755/0644
sudo /usr/bin/python3 -m json.tool /usr/local/libexec/nta-betta-write/version.json >/dev/null && echo version.json-ok
sudo /usr/bin/plutil -lint /Library/LaunchDaemons/com.nanotanksaustralia.betta-write.plist
#   expected: OK
sudo launchctl print system/com.nanotanksaustralia.betta-write | head -8
#   expected: service present, running
sudo ls -l /var/run/nta-betta-write/boundary.sock
#   expected: srw-rw---- root staff
sudo stat -f '%Sp %Su:%Sg %N' /var/db/nta-betta-write /var/db/nta-betta-write/shopify.env
#   expected: 700 root:wheel  /  600 root:wheel
sudo tail -3 /var/log/nta-betta-write.out.log
#   expected: JSON daemon_start with socket/state_dir/code_root/version_sha256
```

Installed-file hashes must equal the repository sources, e.g.:

```bash
shasum -a 256 scripts/betta_write_boundary.py
sudo grep -A2 '"betta_write_boundary.py"' /usr/local/libexec/nta-betta-write/version.json
```

### P6. Verify with `status` + a supervised test request — NOT DONE

The admin CLI requires the explicit state dir (no production default yet):

```bash
sudo /usr/local/bin/nta-betta-write --state-dir /var/db/nta-betta-write status
```

Expected: `"ok": true`, `policy_loaded: true`, `disabled: false`,
`allowed_uids: [501]`, `writes_today: 0`, `pending_reconciliations: 0`,
`signing_key_present: true`, `shopify_env_present: true`.

Supervised test request — **performs ONE REAL write** for one owner-chosen tank
in an allowed batch root. Preconditions: the manifest item is the owner's
intended content, and the product already has an `arrival_date` metafield (see
Seam R2-S1 — otherwise the bound path refuses).

```bash
cd /Users/davidlo/openclaw-skills-trust-boundary/nta-betta-picture-processing-v2
V=/Users/davidlo/openclaw-skills-v3/nta-betta-picture-processing-v2/.venv/bin/python
TANK=2BT12                       # owner-chosen
BATCH="/Users/davidlo/Documents/Betta Processing/batches/<BATCH>"
node scripts/shopify_live.mjs resolve "$TANK" > "${TMPDIR:-/tmp}/nta-boundary-resolve.json"

"$V" - "$BATCH" "$TANK" "${TMPDIR:-/tmp}/nta-boundary-resolve.json" <<'PY'
import hashlib, importlib.util, json, sys
from pathlib import Path

batch_dir = Path(sys.argv[1]); tank = sys.argv[2]
snapshot = json.loads(Path(sys.argv[3]).read_text())
assert snapshot.get("ok") and snapshot["snapshot"]["tank_id"] == tank
before = snapshot["snapshot"]["before"]

spec = importlib.util.spec_from_file_location(
    "betta_bindings_supervised", Path("scripts/betta_bindings.py").resolve())
bnd = importlib.util.module_from_spec(spec); spec.loader.exec_module(bnd)

manifest_path = batch_dir / "manifest" / "shopify-production.json"
digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
entry = {"tank_id": tank, "product": {"before": {
    "title": before["title"], "arrival_date": before["arrival_date"],
    "inventory": before["inventory"]}}}
result = bnd.trusted_writer_execute(
    entry, manifest_path, digest,
    trusted_writer_socket="/var/run/nta-betta-write/boundary.sock")
print(json.dumps(result, indent=2, default=str))
PY
```

Expected evidence:

- printed `"status": "VERIFIED"` with a receipt (`boundary: true`);
- `<BATCH>/reports/shopify/<TANK>-boundary-verify.json` written, with
  `items[0].status == "FINAL_SHOPIFY_READBACK_PASS"` and the signed daemon
  receipt under `items[0].boundary`;
- `status` now shows `writes_today` incremented and receipts present;
- signature check of a stored receipt:

```bash
sudo ls -t /var/db/nta-betta-write/receipts | head -5
sudo /usr/local/bin/nta-betta-write --state-dir /var/db/nta-betta-write \
  verify-receipt --file /var/db/nta-betta-write/receipts/receipt-<request-id>.json
#   expected: {"ok": true, "reason": ...}
```

### P7. Flip the watcher/uploader to the boundary socket — NOT DONE

This is a deliberate **code + runtime-config** change (agents cannot make it).
`scripts/betta_bau.py` currently passes a fixed kwargs dict to
`bind_runners`; add the socket so the opt-in reaches the bindings:

```python
# scripts/betta_bau.py, in _wire_and_process (~line 426)
    runners = _call_supported(bind, {
        "archive_root": Path(paths["archive"]),
        ...
        "live": live_shopify,
        "live_shopify": live_shopify,
        "trusted_writer_socket": paths.get("trusted_writer_socket"),
    })
```

and add to the watcher configuration's `paths`:

```json
"trusted_writer_socket": "/var/run/nta-betta-write/boundary.sock"
```

Expected evidence after the flip: the next watched batch's process state records
`shopify_receipt.boundary == true` and `reports/shopify/*-boundary-verify.json`
files; `sudo ... status` shows `writes_today` advancing; the daemon log shows
the corresponding request events.

### P8. Post-flip verification + monitoring — NOT DONE

- Run one supervised single-tank batch through the watcher; confirm the receipt
  fields above and that no legacy uploader invocation occurred.
- Daily (owner):

```bash
sudo /usr/local/bin/nta-betta-write --state-dir /var/db/nta-betta-write status
sudo tail -50 /var/log/nta-betta-write.out.log
#   alert on: RECONCILIATION_REQUIRED, internal_error, peer_not_allowed,
#   boundary_disabled, and writes_today approaching 60 (max_daily_writes)
sudo ls -t /var/db/nta-betta-write/receipts | head
cut -d= -f1 ~/.openclaw/workspace/nta-betta-picture-processor/.env   # keys only: read-only set
ls /var/db/nta-betta-quarantine-20261016/2026-10-16                  # quarantine untouched
```

## Known seams / remaining risks (review before deployment)

- **R2-S1 — absent `arrival_date`:** the pinned daemon CAS requires a date
  string for `update_details.expected`; the bindings fail closed with a clear
  `BindingError` for products whose metafield is absent rather than skipping it
  (test: `test_operation_plan_refuses_null_arrival_baseline`). Either backfill
  the metafield for such products before the first boundary run, or R1 extends
  the CAS to accept `null` expected when the metafield is absent.
- **R2-S2 — admin CLI needs `--state-dir`:** `betta_write_admin.py` has no
  production default, so every command in these docs passes
  `--state-dir /var/db/nta-betta-write`. A production default (or a wrapper)
  would reduce operator error; recorded as an open item.
- **R2-S3 — socket group:** this host has no `davidlo` group; the plist pins
  `--socket-group staff` (davidlo's primary group) so uid 501 can reach the
  socket. Authorisation remains the daemon's kernel-verified peer-uid allowlist
  (`allowed_uids: [501]`, root for admin); other local users are refused and
  logged (`peer_not_allowed`).
- **R2-S4 — archive binding:** `archive_runner` still validates the
  davidlo-written `*-boundary-verify.json` (which embeds the daemon receipt +
  HMAC signature). Phase 2 should verify the receipt signature directly; until
  then archive independence is no weaker than before, but not yet stronger.
- **R2-S5 — the flip is not automatic:** P7 requires the one-line
  `betta_bau.py` + config change above (deliberately not made in this
  workstream, so the running watcher is untouched).
- **R2-S6 — policy schema is pinned:** `deploy/boundary-policy.production.json`
  is validated against R1's `validate_policy` by
  `test_production_policy_passes_pinned_daemon_validator`; a schema change on
  either side fails the test loudly rather than silently disabling a control.
- **R2-S7 — mixed batches:** batches verified before the flip keep their legacy
  receipts; boundary receipts are per tank, so both formats can coexist.
- **R2-S8 — supervised test writes for real:** P6 performs one real mutation;
  choose the tank deliberately and record it.

## NOT DONE tracker

| Step | Description | State |
|---|---|---|
| P1 | read-only credential for agent read paths | **NOT DONE** |
| P2 | rotate write client secret (root-only placement pending) | **NOT DONE** |
| P3 | remove write creds from user `.env`; retire token stores | **NOT DONE** |
| P4 | quarantine `fred/tmp` bridge copies + `.before-*` backups | **NOT DONE** |
| P5 | install boundary (+ optional sudoers hardening) | **NOT DONE** |
| P6 | `status` + supervised single-tank test request | **NOT DONE** |
| P7 | flip watcher/uploader to the boundary socket | **NOT DONE** |
| P8 | post-flip verification + monitoring | **NOT DONE** |
