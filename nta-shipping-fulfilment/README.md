# NTA Shipping Fulfilment V2

**CLOSED / BAU — 3 October 2026.** Engineering completed in PR #17 and the owner accepted the production design for closure. The previously planned live restart/replay remains an optional BAU confidence check rather than a project blocker. See [closeout](docs/CLOSEOUT.md).

The runnable `scripts/run_shipment.py` defaults to a read-only preflight and supplies the existing adapter plus independent before/after normalization.

Canonical flow: deterministic event → verifier handoff → guarded writer → independent auditor, protected by a durable SQLite shipment ledger. Tracking is preserved and ambiguous outcomes require reconciliation.

Run `python3 -B -m unittest discover -s nta-shipping-fulfilment/tests -v` from repository root and `python3 -B nta-shipping-fulfilment/scripts/dry_run.py`. See SOP.md for operation and TECHDOC.md for persistence/recovery.
