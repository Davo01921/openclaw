# Betta Processing — canonical V2.1

**ONE CANONICAL VERSION — READY FOR FINAL LIVE ACCEPTANCE.** Installed skill: betta-picture-processing. [Closeout, production limits and exact one-fish acceptance](docs/CLOSEOUT.md).

The V3 quota/overnight experiment is deferred. The V2.1 workflow protects product fields, checks exact tank/product/variant/location identity, prevents unauthorized zero-stock revival, verifies independent readback, and verifies archived source/hero hashes.

Run `python3 -B -m unittest discover -s nta-betta-picture-processing-v2/tests -p 'test_*.py' -v` from repository root (81 offline tests). Operation: docs/SOP.md. Contract: references/shopify-contract.md. Deterministic runtime composition: scripts/betta_runtime.py. Retain historical ledgers; do not reinterpret old titles as current acceptance.

The runtime/adapters that execute the live workflow are not present in this repository; see docs/RUNTIME_ADAPTER_STATUS_2026-10-09.md before claiming anything about production. Offline test success is not live acceptance.
