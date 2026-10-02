# Death Loss closeout — 2 October 2026

**Final status: READY FOR FINAL LIVE ACCEPTANCE.** Initial classification C. Engineering hardening is complete; scheduler acceptance is distinct from an approved manual close.

Purpose: turn traceable authorized death reports into exactly one verified daily Shopify loss order. Canonical architecture: trusted Discord metadata/text/photo interpretation → exact variant identity → locked durable daily queue → native scheduled Python close → existing persisted-session bridge → order and fulfillment → independent order and inventory audits. The legacy standalone-order mutation path is disabled; the older modular planner is reference only. v1.4.1 (`797a7a4`, PR #19) is the installed source, not a second competing “v3” path.

## Current production evidence

- **65 offline tests pass**, plus the existing deterministic planner dry-run. Tests cover concurrent intake/close, stable duplicate references, quantity amendments, truncated reads, stale tanks, stock checks, durable mutation intent/recovery, no mutation retry, transient-read retry bounds, error redaction and Sydney DST boundaries.
- The active job is `2900ada8-d36a-43e2-8243-be4c80e7bf90`: enabled, native `command`, `0 18 * * *`, `Australia/Sydney`, zero staggering, 600-second timeout, process-scoped write flag and Node 24. It invokes Fred's installed `scheduled_close.py`; no closing model is launched.
- On inspection, its private configuration file was missing. Restored the non-secret configuration at the existing configured path from the prior authorized Discord channel/sender/location contract and a fresh exact `NTA Losses` customer read. Credential file and bridge are unchanged. Configuration mode is 0600, directory 0700.
- A read-only installed-helper preview then independently re-read **#17407**, the October 1 real loss order: exactly one daily order, exact two lines/references, NTA Losses customer, Ntalosses discount, PAID, FULFILLED, zero AUD total and outstanding, not cancelled. All returned contract checks passed; no order, inventory or queue write occurred.
- Its original CLOSED_VERIFIED journal records inventory **10 → 9** and **6 → 5**, with independent affected-variant reads. Current stock is not reused to recreate a historical baseline after later sales.
- October 1's scheduled run failed preflight; the real successful close was separately authorized and manual. The subsequently deployed v1.4.1 gateway probe recovered an injected read 503 and audited that real order without mutation or Discord delivery. Neither establishes a successful nonempty scheduled close.

Private source evidence: `/Users/davidlo/Documents/Codex/nta-death-loss-investigation-2026-10-01/ROLLOUT.md`, `approved-real-close-result.json`, `read-resilience-validation.json`; live queue/result journals in Fred's configured state directory. They contain operator details and remain outside Git.

## Exactly one final acceptance action

**Observe the next genuine nonempty 18:00 Sydney scheduled close.** Preserve the scheduler receipt and private JSON result journal. Require CLOSED_VERIFIED, exactly one `DeathBatch-<Sydney date>` order, exact lines/customer/discount/source references, PAID/FULFILLED/$0 AUD/zero balance and verified frozen-before/fresh-after inventory deltas. Then run a read-only preview for that date and confirm it identifies the same existing order; there must be no second daily order. Mark CLOSED only after this evidence exists.

An empty scheduled run is expected and cannot satisfy nonempty acceptance. Today had no queued October 2 batch at inspection. No synthetic event, test Discord message or manual order was created during closeout.

BAU: staff provide accurate reports; operator resolves ambiguous intake and failed/indeterminate recovery alerts. Preserve result journals and source references. Follow [SOP](../SOP.md) and [DEVELOPMENT](../DEVELOPMENT.md) for recovery. Before any mutation attempt the deployment backup can restore code/config; after an attempt preserve recovery state and reconcile the exact existing order before any retry. Never restore an OPEN queue snapshot over a mutation journal.

Deferred: broader synonym matching, alternative schedule mechanisms and richer reporting are unnecessary for closure and belong to future backlog.
