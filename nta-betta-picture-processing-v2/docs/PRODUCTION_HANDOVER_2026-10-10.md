# NTA Betta Processing V2.2 — Production Handover Record

Date: 2026-10-10 · Version: 2.2 · Repository: https://github.com/Davo01921/openclaw-skills

## Status

**PRODUCTION RELEASE BLOCKED — ACTION REQUIRED.**
Code and documentation are released to `main` and the canonical local skill is
synchronised, but unattended production is **NOT ACTIVATED**: the watcher and the
standing Shopify authorisation remain disabled, and the production paid-generation
budget/retry ceilings have not been set.

## Record

| Item | Value |
|---|---|
| Production version | 2.2 |
| Release date | 2026-10-10 |
| Release PR | see PR opened from `codex/betta-v2.2-production-release-20261010` |
| Pre-release main | `6aead9c` |
| Runtime location | `~/openclaw-skills-v3/nta-betta-picture-processing-v2/` |
| Watcher status | **DISABLED** (not loaded under launchd) |
| Standing-policy status | **DISABLED** (`automation-policy.json` absent) |
| Paid-generation budget | **NOT SET** (see blocker) |
| Shopify connection | read-only resolve verified OK; live writes gated |
| Discord notification | skill entry present; routine reporting not yet exercised live |
| Archive root | `~/Documents/Archived Bettas/` |
| Intake | `~/Documents/Betta Processing/` |
| Telemetry DB | `~/Documents/Betta Processing/betta-telemetry.sqlite3` |

## Activation gates (all required)

1. Set per-fish and per-batch generation ceilings and the retry policy in
   `automation-policy.json` (owner decision). **Outstanding.**
2. Perform one supervised live run **through the unified orchestrator** (not manual
   script coordination) and pass independent Shopify verification. **Outstanding.**
3. Prove idempotency by a resume re-run (no duplicate Shopify writes/stock).
4. Confirm archive completion + destination SHA-256 for that run.
5. `betta_policy.py grant <manifest-sha256> --receipt …` then `set-enabled true`
   (and `set-paid-generation true` only if approved for unattended use).
6. Configure and enable the watcher under launchd (`com.nta.betta-watch`).
7. Configure automatic Discord reporting; verify restart persistence.

## Emergency stop

```sh
launchctl unload ~/Library/LaunchAgents/com.nta.betta-watch.plist
python3 scripts/betta_policy.py set-enabled false
python3 scripts/betta_policy.py set-paid-generation false
```

Then inspect `<batch>/state/process.json`; reconcile any uncertain Shopify result
by an independent read before any retry. Do not delete evidence.

## Rollback

`git revert <release-merge-commit>` on `main`, fast-forward the canonical checkout,
and keep the watcher/policy disabled. Archive output is additive; nothing is
overwritten or deleted by the release.

## Recovery

Resumable from the batch checkpoint; the processed-source registry prevents
duplicate intake; quarantined fish retain evidence.

## Known limitations

- No supervised live orchestrator run has been performed yet.
- Production paid-generation ceilings/retry policy are undefined.
- Vision identification of unseen label formats depends on the live model;
  ambiguous cases quarantine.

## Classification

**PRODUCTION RELEASE BLOCKED — ACTION REQUIRED** (activation gates 1, 2 and 6
outstanding). The system is not live and must not be described as BAU until these
gates pass with evidence.
