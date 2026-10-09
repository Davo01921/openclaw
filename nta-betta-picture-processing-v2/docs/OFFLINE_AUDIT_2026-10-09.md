# Offline audit — 9 October 2026

Base: main at 11aef1a. Review branch: codex/betta-v2-offline-audit-20261009.

The 30 original tests passed. Added regressions reproduced source-evidence substitution, boolean/float inventory acceptance, missing nullable protected fields and whole-batch transition bypass. Fixed those four defects and included exact variant/location identity in the mutation envelope. The expanded 37-test suite passes; CLI tests use temporary synthetic ledgers and never call external services. All seven scripts parse successfully.

PR #21 previously merged V2.1 intake safety. PRs #2 and #3 are closed experiments, not replacement production workflows. The V2.1 one-new-fish acceptance described in CLOSEOUT.md remains outstanding and intentionally excluded from this audit. No live Shopify read/write, paid generation, runtime installation, restart, activation or merge occurred.

Limits: the helper validates evidence; it is not a standalone end-to-end runtime. Actual API provenance/errors, multi-writer serialization, cross-batch intake deduplication, CSV values and telemetry persistence before PASS remain adapter obligations. No new unattended runtime or production readiness is claimed. Historical ledgers retain their original schema/evidence and were not modified.

## Follow-up implementation — 9 October 2026 (offline only)

Added `scripts/betta_runtime.py`: a deterministic orchestration layer over injected adapters that closes the adapter obligations listed above, and a `MUTATION_UNCERTAIN` hold state in `scripts/betta_batch.py`.

Implemented and covered offline:

- serialized ledger writes (`LedgerStore`, advisory `fcntl.flock` + fsync + atomic replace);
- cross-batch intake / source deduplication (`IntakeRegistry`), including an explicitly recorded duplicate override;
- API-error classification (`classify_write_result`, `classify_read_result`);
- uncertain-write reconciliation (`determine_reconciliation`) — an inconclusive mutation is held, never automatically retried; it returns to `MUTATION_PENDING` only on a confirmed `NOT_APPLIED` read with explicit retry authority, or reconciles to `MUTATED` on a confirmed `APPLIED` read;
- inventory CSV construction and validation (`build_inventory_csv`, `validate_inventory_csv`);
- telemetry-before-PASS gating (`require_telemetry_before_pass`);
- independent-readback trust (`verify_independent_readback`) rejecting writer-derived evidence, reused writer identities and reads that pre-date the write.

`tests/test_betta_runtime.py` (32 tests) and `tests/test_betta_integration.py` (12 tests) exercise these with fake adapters, temporary ledgers and temporary SQLite databases, covering complete intake-to-archive, mutation rejection, uncertain-write hold and recovery, duplicate intake, concurrent processing on one ledger and completed-batch resume. The full suite is 81 tests (37 baseline + 44 added). No live Shopify read/write, paid generation, runtime installation, restart, activation or merge occurred.

Remaining blocker (unchanged): there is no concrete, runnable Shopify adapter or single end-to-end orchestrator in this repository. See [RUNTIME_ADAPTER_STATUS_2026-10-09.md](RUNTIME_ADAPTER_STATUS_2026-10-09.md). Offline implementation completion must not be reported as verified production acceptance.
