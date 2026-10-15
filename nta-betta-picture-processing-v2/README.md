# Betta Processing — canonical V2.1

**ONE CANONICAL VERSION — READY FOR FINAL LIVE ACCEPTANCE.** Installed skill: betta-picture-processing. [Closeout, production limits and exact one-fish acceptance](docs/CLOSEOUT.md).

The V3 quota/overnight experiment is deferred. The V2.1 workflow protects product fields, checks exact tank/product/variant/location identity, prevents unauthorized zero-stock revival, verifies independent readback, and verifies archived source/hero hashes.

Run `python3 -B -m unittest discover -s nta-betta-picture-processing-v2/tests -p 'test_*.py' -v` from repository root. Operation: [docs/SOP.md](docs/SOP.md). Contract: [references/shopify-contract.md](references/shopify-contract.md). Deterministic runtime composition: `scripts/betta_runtime.py`. Verified resumable archive: `scripts/betta_archive.py`. Generic manifest-bound Shopify batch uploader: [docs/SHOPIFY_BATCH_UPLOADER.md](docs/SHOPIFY_BATCH_UPLOADER.md). Retain historical ledgers; do not reinterpret old titles as current acceptance.

The generic live adapters (`scripts/betta_shopify_batch.py`, `scripts/betta_finish_heroes.py`, the authenticated Shopify bridge) currently exist only in the local canonical checkout and are not yet committed to this repository; see [docs/RUNTIME_ADAPTER_STATUS_2026-10-09.md](docs/RUNTIME_ADAPTER_STATUS_2026-10-09.md) for the boundary. Offline helper and fixture completion is not live acceptance.

2026-10-14 autonomy hardening (zero-mutation reconciliation, APE tank namespace, focus-label identify retry, pre-generation eligibility): [docs/AUTONOMY_RECONCILIATION_2026-10-14.md](docs/AUTONOMY_RECONCILIATION_2026-10-14.md).

2026-10-15 autonomy completion (deterministic working-photo preparation with fish-protection gates, QA calibration against genuine owner-accepted evidence, full-chain acceptance): [docs/AUTONOMY_COMPLETION_2026-10-15.md](docs/AUTONOMY_COMPLETION_2026-10-15.md) and [docs/QA_CALIBRATION_2026-10-15.md](docs/QA_CALIBRATION_2026-10-15.md).

2026-10-15 P1 identity incident (FredAPP misidentified an upload of tank 2BT23 as 5BT43; fail-closed dual label reads, gate-aware retry rules, uploader identity firewall with scoped owner corrections): forensics, audits and design under [docs/incident/](docs/incident/) — start with [INCIDENT_BRIEF.md](docs/incident/INCIDENT_BRIEF.md).
