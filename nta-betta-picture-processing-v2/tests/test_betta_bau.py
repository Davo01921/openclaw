"""Offline tests for the launchd-facing BAU dispatcher.

No model, generation, network, Discord, or Shopify call is made here.
"""

import hashlib
import importlib.util
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parents[1] / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bau = _load("betta_bau_t", "betta_bau.py")


class FakePolicy:
    def __init__(self, *, enabled=True, paid=True, maximum=20, automatic=False):
        self._enabled = enabled
        self._paid = paid
        self._maximum = maximum
        self.data = {"automatic_batch_authorisation": automatic}

    def enabled(self):
        return self._enabled

    def paid_generation_authorised(self):
        return self._enabled and self._paid

    def generation_budget(self):
        return {
            "max_fish_per_batch": self._maximum, "per_fish_usd": 0.14,
            "per_batch_usd": 2.80, "max_attempts_per_fish": 2,
            "max_retries_per_fish": 1, "fallback_cost_usd": 0.07,
        }


class FakeBudget:
    def __init__(self, path, **kwargs):
        self.path = Path(path)
        self.kwargs = kwargs


class DispatcherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.intake = self.root / "intake"
        self.intake.mkdir()
        self.archive = self.root / "archive"
        self.archive.mkdir()
        self.batches = self.root / "batches"
        self.state = self.root / "state"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("python", "node", "openclaw"):
            path = self.bin / name
            path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            path.chmod(0o755)
        self.bridge = self.root / "bridge.mjs"
        self.bridge.write_text("// fixture\n", encoding="utf-8")
        self.env = self.root / "runtime.env"
        self.env.write_text("fixture", encoding="utf-8")
        self.policy_path = self.root / "policy.json"
        policy_data = bau.betta_policy.default_policy()
        policy_data["enabled"] = True
        self.policy_path.write_text(json.dumps(policy_data), encoding="utf-8")
        self.config = {
            "schema": bau.CONFIG_SCHEMA, "enabled": True,
            "live_generation": False, "live_shopify": False,
            "settle_seconds": 0,
            "paths": {
                "python": str((self.bin / "python").resolve()),
                "node": str((self.bin / "node").resolve()),
                "openclaw": str((self.bin / "openclaw").resolve()),
                "bridge": str(self.bridge.resolve()), "env": str(self.env.resolve()),
                "intake": str(self.intake.resolve()), "batches": str(self.batches.resolve()),
                "archive": str(self.archive.resolve()),
                "telemetry": str((self.root / "telemetry.sqlite3").resolve()),
                "registry": str((self.state / "processed.sqlite3").resolve()),
                "policy": str(self.policy_path.resolve()),
                "dispatcher_lock": str((self.state / "dispatcher.lock").resolve()),
            },
            "discord": {"channel": "discord", "target": bau.EXPECTED_DISCORD_TARGET},
        }

    def tearDown(self):
        self.temporary.cleanup()

    def add_source(self, name, content):
        path = self.intake / name
        path.write_bytes(content)
        os.utime(path, (1, 1))
        return path

    def scanner(self, _intake, **_kwargs):
        rows = []
        for path in sorted(self.intake.iterdir()):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest in _kwargs.get("known_hashes", set()):
                continue
            rows.append({"path": str(path), "sha256": digest,
                         "size": path.stat().st_size, "mtime": 1})
        return rows

    def deps(self, process, *, policy=None, command=None):
        def bind(**kwargs):
            return {"binding_kwargs": kwargs}

        def adapters(**kwargs):
            return {"adapter_kwargs": kwargs}

        return {
            "policy": policy or FakePolicy(), "scanner": self.scanner,
            "bind_runners": bind, "make_adapters": adapters,
            "budget_factory": FakeBudget, "process_batch": process,
            "command_runner": command or (lambda _argv: json.dumps({"messageId": "fixture"})),
        }

    def test_once_disabled_by_config_before_any_state_change(self):
        self.config["enabled"] = False
        result = bau.run_once(self.config, deps={"policy": FakePolicy()})
        self.assertEqual(result["status"], "DISABLED")
        self.assertFalse(self.state.exists())

    def test_once_disabled_by_policy(self):
        result = bau.run_once(self.config, deps={"policy": FakePolicy(enabled=False)})
        self.assertEqual(result["status"], "DISABLED")
        self.assertFalse(self.state.exists())

    def test_smoke_is_nonmutating_and_never_binds_or_processes(self):
        self.add_source("stable.png", b"fish")
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))
        report = bau.smoke(self.config, now=100, scanner=self.scanner)
        after = sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))
        self.assertTrue(report["ok"])
        self.assertEqual(report["stable_new_sources"], 1)
        self.assertEqual(before, after)

    def test_rejects_unknown_discord_target(self):
        self.config["discord"]["target"] = "channel:999"
        self.assertIn("discord.target is not the approved #betta-processing channel",
                      bau.validate_config(self.config))

    def test_duplicate_content_selects_one_fish_and_persists_sources_first(self):
        first = self.add_source("a.png", b"same-fish")
        self.add_source("b.png", b"same-fish")
        observed = {}

        def process(batch_dir, batch_id, *, adapters, policy):
            sources = json.loads((Path(batch_dir) / "state" / "sources.json").read_text())
            observed["sources"] = sources["selected_sources"]
            observed["adapters"] = adapters
            return {"batch_id": batch_id, "stage": "COMPLETE", "status": "COMPLETE",
                    "published": 1, "quarantined": 0}

        result = bau.run_once(self.config, deps=self.deps(process))
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(len(observed["sources"]), 1)
        self.assertEqual(observed["sources"][0]["path"], str(first.resolve()))
        adapter_args = observed["adapters"]["adapter_kwargs"]
        self.assertEqual(adapter_args["selected_sources"], observed["sources"])
        self.assertIsInstance(adapter_args["budget"], FakeBudget)

    def test_oversized_scan_blocks_before_allocation_or_processing(self):
        for index in range(3):
            self.add_source(f"{index}.png", f"fish-{index}".encode())
        calls = {"process": 0, "message": 0}

        def process(*_args, **_kwargs):
            calls["process"] += 1

        def message(argv):
            calls["message"] += 1
            self.assertEqual(argv[3:7], ["--channel", "discord", "--target",
                                         bau.EXPECTED_DISCORD_TARGET])
            return "{}"

        result = bau.run_once(
            self.config, deps=self.deps(process, policy=FakePolicy(maximum=2), command=message))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["stable_sources"], 3)
        self.assertEqual(calls, {"process": 0, "message": 1})
        self.assertFalse((self.batches / "registry.json").exists())

    def test_historical_archive_seeds_registry_without_overwriting(self):
        old_hash = "a" * 64
        new_hash = "b" * 64
        manifest_dir = self.archive / "2026-10-10"
        manifest_dir.mkdir()
        (manifest_dir / "archive-manifest.json").write_text(json.dumps({
            "schema": "archive", "batch_id": "historical-batch",
            "files": [{"role": "original", "source_sha256": new_hash}],
        }), encoding="utf-8")
        registry = Path(self.config["paths"]["registry"])
        registry.parent.mkdir()
        con = sqlite3.connect(registry)
        con.execute("CREATE TABLE processed (source_sha256 TEXT PRIMARY KEY, batch_id TEXT, processed_at TEXT)")
        con.execute("INSERT INTO processed VALUES (?,?,?)", (old_hash, "keep-me", "before"))
        con.commit(); con.close()
        self.assertEqual(bau.seed_processed_registry(self.config), 1)
        con = sqlite3.connect(registry)
        rows = dict(con.execute("SELECT source_sha256,batch_id FROM processed"))
        con.close()
        self.assertEqual(rows[old_hash], "keep-me")
        self.assertEqual(rows[new_hash], "historical-batch")
        self.assertEqual(bau.seed_processed_registry(self.config), 0)

    def test_manual_active_batch_is_untouched_and_new_owned_batch_is_used(self):
        manual = bau.betta_batches.create_batch(self.batches, label="manual")
        self.add_source("new.png", b"new-fish")
        seen = {}

        def process(batch_dir, batch_id, **_kwargs):
            seen["batch_id"] = batch_id
            return {"batch_id": batch_id, "stage": "COMPLETE", "status": "COMPLETE",
                    "published": 1, "quarantined": 0}

        bau.run_once(self.config, deps=self.deps(process))
        self.assertNotEqual(seen["batch_id"], manual["batch_id"])
        manual_after = bau.betta_batches.get_batch(self.batches, manual["batch_id"])
        self.assertEqual(manual_after["status"], bau.betta_batches.ACTIVE)
        self.assertFalse((Path(manual["path"]) / "state" / "sources.json").exists())

    def test_owned_interrupted_batch_resumes_without_scanning_new_batch(self):
        source = self.add_source("resume.png", b"resume-fish")
        entry = bau.betta_batches.create_batch(self.batches, label="BAU automatic intake")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        entry["sources"] = bau._persist_sources(entry, [{
            "path": str(source.resolve()), "sha256": digest, "size": source.stat().st_size,
        }])
        (Path(entry["path"]) / "state" / "process.json").write_text(json.dumps({
            "status": "ACTIVE", "stage": "GENERATED",
        }), encoding="utf-8")
        seen = []

        def process(_batch_dir, batch_id, **_kwargs):
            seen.append(batch_id)
            return {"batch_id": batch_id, "stage": "COMPLETE", "status": "COMPLETE",
                    "published": 1, "quarantined": 0}

        bau.run_once(self.config, deps=self.deps(process))
        self.assertEqual(seen, [entry["batch_id"]])

    def test_terminal_owned_batch_is_never_reopened(self):
        source = self.add_source("failed.png", b"failed-fish")
        entry = bau.betta_batches.create_batch(self.batches, label="BAU automatic intake")
        entry["sources"] = bau._persist_sources(entry, [{
            "path": str(source.resolve()), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "size": source.stat().st_size,
        }])
        (Path(entry["path"]) / "state" / "process.json").write_text(json.dumps({
            "status": "PARTIAL", "stage": "SHOPIFY_VERIFIED",
        }), encoding="utf-8")
        calls = []
        result = bau.run_once(self.config, deps=self.deps(lambda *_a, **_k: calls.append(1)))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(calls, [])

    def _owned_batch_with_state(self, state):
        source = self.add_source(f"{state.get('status', 'x').lower()}.png",
                                 str(state.get("status", "x")).encode())
        entry = bau.betta_batches.create_batch(self.batches, label="BAU automatic intake")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        entry["sources"] = bau._persist_sources(entry, [{
            "path": str(source.resolve()), "sha256": digest, "size": source.stat().st_size,
        }])
        bau._record_selected(Path(self.config["paths"]["registry"]), entry["batch_id"],
                             entry["sources"]["selected_sources"])
        state_path = Path(entry["path"]) / "state" / "process.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        return entry, state_path

    def test_zero_mutation_quarantined_batch_reconciles_truthfully_once(self):
        state = {
            "batch_id": "placeholder", "status": "PARTIAL", "stage": "SHOPIFY_RESOLVED",
            "executed": [], "manifest_sha256": None,
            "fish": {"/x.png": {"tank_id": None, "status": "QUARANTINED",
                                "notes": ["identification uncertain"]}},
        }
        entry, state_path = self._owned_batch_with_state(state)
        state_path.write_text(json.dumps({**state, "batch_id": entry["batch_id"]}),
                              encoding="utf-8")
        state_bytes = state_path.read_bytes()
        calls = {"process": 0, "message": 0}

        def process(*_args, **_kwargs):
            calls["process"] += 1

        def message(_argv):
            calls["message"] += 1
            return json.dumps({"messageId": "fixture"})

        result = bau.run_once(self.config, deps=self.deps(process, command=message))
        self.assertEqual(result["status"], "RECONCILED")
        self.assertEqual(result["actionable_status"], "PARTIAL")
        self.assertEqual(result["quarantined"], 1)
        self.assertEqual(calls, {"process": 0, "message": 1})
        self.assertEqual(state_path.read_bytes(), state_bytes)  # evidence is never altered
        outcome = json.loads((Path(entry["path"]) / "state" / "bau-outcome.json").read_text())
        self.assertFalse(outcome["resumable"])
        self.assertEqual(outcome["summary"]["finalization"]["status"],
                         "NOT_REQUIRED_NO_MUTATIONS")
        registry = json.loads((self.batches / "registry.json").read_text())
        owned = next(row for row in registry["batches"]
                     if row["batch_id"] == entry["batch_id"])
        self.assertEqual(owned["status"], bau.betta_batches.ABANDONED)
        # A second run is idle and never repeats the notification.
        second = bau.run_once(self.config, deps=self.deps(process, command=message))
        self.assertEqual(second["status"], "IDLE")
        self.assertEqual(calls, {"process": 0, "message": 1})

    def test_zero_mutation_reconciliation_requires_all_fish_terminal(self):
        state = {
            "batch_id": "placeholder", "status": "PARTIAL", "stage": "SHOPIFY_VERIFIED",
            "executed": [], "fish": {"/x.png": {"status": "VERIFIED"}},
        }
        entry, state_path = self._owned_batch_with_state(state)
        state_path.write_text(json.dumps({**state, "batch_id": entry["batch_id"]}),
                              encoding="utf-8")
        calls = {"process": 0, "message": 0}
        result = bau.run_once(self.config, deps=self.deps(
            lambda *_a, **_k: calls.__setitem__("process", calls["process"] + 1),
            command=lambda _a: calls.__setitem__("message", calls["message"] + 1) or "{}"))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(calls["process"], 0)

    def test_zero_mutation_reconciliation_refuses_executed_batches(self):
        state = {
            "batch_id": "placeholder", "status": "PARTIAL", "stage": "SHOPIFY_VERIFIED",
            "executed": ["/x.png"], "fish": {"/x.png": {"status": "QUARANTINED"}},
        }
        entry, state_path = self._owned_batch_with_state(state)
        state_path.write_text(json.dumps({**state, "batch_id": entry["batch_id"]}),
                              encoding="utf-8")
        result = bau.run_once(self.config, deps=self.deps(lambda *_a, **_k: None))
        self.assertEqual(result["status"], "BLOCKED")

    def test_finalization_gate_accepts_zero_mutation_terminal_without_archive(self):
        batch_dir = self.batches / "zero-mutation"
        (batch_dir / "state").mkdir(parents=True)
        process_path = batch_dir / "state" / "process.json"
        process_path.write_text(json.dumps({
            "batch_id": "zero-mutation", "status": "PARTIAL", "stage": "SHOPIFY_RESOLVED",
            "executed": [], "fish": {"/x.png": {"status": "QUARANTINED"}},
        }), encoding="utf-8")
        summary = {"batch_id": "zero-mutation", "status": "PARTIAL",
                   "stage": "SHOPIFY_RESOLVED", "published": 0, "quarantined": 1}
        entry = {"batch_id": "zero-mutation", "path": str(batch_dir)}
        resolved = bau._finalize_if_required(self.config, entry, summary, deps={})
        self.assertEqual(resolved["finalization"]["status"], "NOT_REQUIRED_NO_MUTATIONS")
        # Anything not provably mutation-free still waits for the archive gate.
        process_path.write_text(json.dumps({
            "batch_id": "zero-mutation", "status": "PARTIAL", "stage": "SHOPIFY_VERIFIED",
            "executed": [], "fish": {"/x.png": {"status": "VERIFIED"}},
        }), encoding="utf-8")
        pending = bau._finalize_if_required(self.config, entry, summary, deps={})
        self.assertEqual(pending["status"], "FINALIZATION_PENDING")

    def test_notification_pending_becomes_uncertain_and_is_not_retried(self):
        batch = self.root / "batch"
        summary = {"batch_id": "b-1", "stage": "COMPLETE", "status": "COMPLETE",
                   "published": 2, "quarantined": 0}
        calls = []

        def uncertain(argv):
            calls.append(argv)
            raise TimeoutError("delivery result unknown")

        first = bau.notify_discord(self.config, batch, summary, command_runner=uncertain)
        second = bau.notify_discord(self.config, batch, summary, command_runner=uncertain)
        self.assertEqual(first["status"], "UNCERTAIN")
        self.assertEqual(second["status"], "UNCERTAIN")
        self.assertEqual(len(calls), 1)
        ledger = json.loads((batch / "state" / "discord-notifications.json").read_text())
        self.assertEqual(next(iter(ledger["events"].values()))["status"], "UNCERTAIN")

    def test_live_generation_requires_policy_authority_before_wiring(self):
        self.config["live_generation"] = True
        self.add_source("paid.png", b"paid")
        called = []
        result = bau.run_once(
            self.config,
            deps=self.deps(lambda *_a, **_k: called.append(1), policy=FakePolicy(paid=False)),
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(called, [])

    def test_live_shopify_requires_automatic_manifest_authority_before_wiring(self):
        self.config["live_shopify"] = True
        self.add_source("shopify.png", b"shopify")
        called = []
        result = bau.run_once(
            self.config,
            deps=self.deps(lambda *_a, **_k: called.append(1),
                           policy=FakePolicy(automatic=False)),
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(called, [])

    def test_reconciliation_pending_keeps_batch_active_and_notifies_once(self):
        self.add_source("uncertain.png", b"uncertain-fish")
        calls = {"process": 0, "message": 0}

        def process(_batch_dir, batch_id, **_kwargs):
            calls["process"] += 1
            return {"batch_id": batch_id, "stage": "SHOPIFY_EXECUTING",
                    "status": "RECONCILIATION_PENDING", "published": 0,
                    "quarantined": 0}

        def message(_argv):
            calls["message"] += 1
            return "{}"

        first = bau.run_once(self.config, deps=self.deps(process, command=message))
        second = bau.run_once(self.config, deps=self.deps(process, command=message))
        self.assertEqual(first["status"], "RECONCILIATION_PENDING")
        self.assertEqual(second["status"], "RECONCILIATION_PENDING")
        self.assertEqual(calls, {"process": 2, "message": 1})
        registry = json.loads((self.batches / "registry.json").read_text())
        owned = [row for row in registry["batches"] if row["label"] == "BAU automatic intake"]
        self.assertEqual(owned[0]["status"], bau.betta_batches.ACTIVE)
        outcome = json.loads((Path(owned[0]["path"]) / "state" / "bau-outcome.json").read_text())
        self.assertTrue(outcome["resumable"])

    def test_finalization_pending_retries_without_closing_process_batch(self):
        self.add_source("finalize.png", b"finalize-fish")
        calls = {"process": 0, "finalize": 0, "message": 0}

        def process(batch_dir, batch_id, **_kwargs):
            calls["process"] += 1
            state = {
                "status": "COMPLETE", "stage": "ARCHIVED", "fish": {},
                "archive_receipt": {"status": "ARCHIVED", "batch_status": "COMPLETE"},
            }
            (Path(batch_dir) / "state" / "process.json").write_text(json.dumps(state))
            return {"batch_id": batch_id, "stage": "COMPLETE", "status": "COMPLETE",
                    "published": 1, "quarantined": 0}

        def finalize(_config, batch_dir, _summary):
            calls["finalize"] += 1
            if calls["finalize"] == 1:
                raise RuntimeError("snapshot interrupted")
            audit = self.archive / "Audit" / "final-audit.json"
            audit.parent.mkdir(parents=True, exist_ok=True)
            audit.write_text('{"audit":true}\n')
            receipt_data = {"status": "FINALIZED", "files": [{
                "destination": str(audit.resolve()),
                "sha256": hashlib.sha256(audit.read_bytes()).hexdigest(),
            }]}
            receipt_bytes = (json.dumps(receipt_data, sort_keys=True) + "\n").encode()
            receipt = Path(batch_dir) / "state" / "completion-receipt.json"
            receipt.write_bytes(receipt_bytes)
            archived_receipt = self.archive / "Audit" / "completion-receipt.json"
            archived_receipt.write_bytes(receipt_bytes)
            return {"status": "FINALIZED", "receipt_path": str(receipt.resolve()),
                    "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
                    "archive_receipt_path": str(archived_receipt.resolve()),
                    "archive_completed_at": "2026-10-11T00:00:00+00:00"}

        def message(_argv):
            calls["message"] += 1
            return "{}"

        dependencies = self.deps(process, command=message)
        dependencies["finalize"] = finalize
        first = bau.run_once(self.config, deps=dependencies)
        self.assertEqual(first["status"], "FINALIZATION_PENDING")
        second = bau.run_once(self.config, deps=dependencies)
        self.assertEqual(second["status"], "COMPLETE")
        self.assertEqual(second["finalization"]["status"], "FINALIZED")
        self.assertEqual(calls, {"process": 2, "finalize": 2, "message": 2})
        registry = json.loads((self.batches / "registry.json").read_text())
        owned = [row for row in registry["batches"] if row["label"] == "BAU automatic intake"]
        self.assertEqual(owned[0]["status"], bau.betta_batches.COMPLETE)

    def test_real_finalizer_receipt_passes_dispatcher_archive_verification(self):
        batch_id = "betta-finalizer-integration"
        batch_dir = self.batches / batch_id
        for name in ("state", "manifest", "reports"):
            (batch_dir / name).mkdir(parents=True, exist_ok=True)
        source = self.add_source("real-finalize.png", b"original")
        source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        manifest = batch_dir / "manifest" / "shopify-production.json"
        manifest.write_text('{"items":[]}\n')
        manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
        archived_dir = self.archive / "2026-10-11" / batch_id
        archived_dir.mkdir(parents=True)
        archived_manifest_copy = archived_dir / manifest.name
        archived_manifest_copy.write_bytes(manifest.read_bytes())
        archived_original = archived_dir / source.name
        archived_original.write_bytes(source.read_bytes())
        archive_manifest = archived_dir / "archive-manifest.json"
        archive_data = {
            "batch_id": batch_id, "batch_status": "COMPLETE",
            "created_at": "2026-10-11T01:02:03+00:00",
            "files": [
                {"role": "manifest", "source_path": str(manifest),
                 "source_sha256": manifest_sha,
                 "destination_path": str(archived_manifest_copy),
                 "destination_sha256": manifest_sha},
                {"role": "original", "source_path": str(source),
                 "source_sha256": source_sha,
                 "destination_path": str(archived_original),
                 "destination_sha256": source_sha},
            ],
        }
        archive_manifest.write_text(json.dumps(archive_data, sort_keys=True))
        archive_sha = hashlib.sha256(archive_manifest.read_bytes()).hexdigest()
        process = {
            "batch_id": batch_id, "status": "COMPLETE", "stage": "ARCHIVED",
            "fish": {}, "executed": [], "manifest_path": str(manifest),
            "manifest_sha256": manifest_sha,
            "archive_receipt": {"status": "ARCHIVED", "batch_status": "COMPLETE",
                                "manifest": str(archive_manifest),
                                "manifest_sha256": archive_sha},
        }
        (batch_dir / "state" / "process.json").write_text(json.dumps(process))
        (batch_dir / "state" / "sources.json").write_text(json.dumps({
            "schema": bau.SOURCES_SCHEMA, "dispatcher_owned": True,
            "batch_id": batch_id, "selected_sources": [{
                "path": str(source), "sha256": source_sha, "size": source.stat().st_size,
            }],
        }))
        summary = {"batch_id": batch_id, "status": "COMPLETE", "stage": "ARCHIVED",
                   "published": 0, "quarantined": 0}
        result = bau._finalize_if_required(
            self.config, {"batch_id": batch_id, "path": str(batch_dir)}, summary, deps={})
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(result["finalization"]["status"], "FINALIZED")
        self.assertFalse(source.exists())


if __name__ == "__main__":
    unittest.main()
