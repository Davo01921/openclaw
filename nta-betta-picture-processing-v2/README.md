# Betta Processing — canonical V2.1

**ONE CANONICAL VERSION — READY FOR FINAL LIVE ACCEPTANCE.** Installed skill: betta-picture-processing. [Closeout, production limits and exact one-fish acceptance](docs/CLOSEOUT.md).

The V3 quota/overnight experiment is deferred. The V2.1 workflow protects product fields, checks exact tank/product/variant/location identity, prevents unauthorized zero-stock revival, verifies independent readback, and verifies archived source/hero hashes.

Run `python3 -B -m unittest discover -s nta-betta-picture-processing-v2/tests -p 'test_*.py' -v` from repository root. Operation: [docs/SOP.md](docs/SOP.md). Contract: [references/shopify-contract.md](references/shopify-contract.md). Deterministic runtime composition: `scripts/betta_runtime.py`. Verified resumable archive: `scripts/betta_archive.py`. Generic manifest-bound Shopify batch uploader: [docs/SHOPIFY_BATCH_UPLOADER.md](docs/SHOPIFY_BATCH_UPLOADER.md). Retain historical ledgers; do not reinterpret old titles as current acceptance.

The generic live adapters (`scripts/betta_shopify_batch.py`, `scripts/betta_finish_heroes.py`, the authenticated Shopify bridge) currently exist only in the local canonical checkout and are not yet committed to this repository; see [docs/RUNTIME_ADAPTER_STATUS_2026-10-09.md](docs/RUNTIME_ADAPTER_STATUS_2026-10-09.md) for the boundary. Offline helper and fixture completion is not live acceptance.
