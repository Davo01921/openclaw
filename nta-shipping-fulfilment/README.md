# NTA Shipping Fulfilment V2

**READY FOR FINAL LIVE ACCEPTANCE** — engineering completed in PR #17. [Closeout and exact acceptance](docs/CLOSEOUT.md).

Canonical flow: deterministic event → verifier handoff → guarded writer → independent auditor, protected by a durable SQLite shipment ledger. Tracking is preserved and ambiguous outcomes require reconciliation.

Run `python3 -B -m unittest discover -s nta-shipping-fulfilment/tests -v` from repository root and `python3 -B nta-shipping-fulfilment/scripts/dry_run.py`. See SOP.md for operation and TECHDOC.md for persistence/recovery.
