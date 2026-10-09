"""Offline tests for the generic Betta batch lifecycle."""

import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "betta_batches.py"
spec = importlib.util.spec_from_file_location("betta_batches", SCRIPT)
bl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bl)


class BatchLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "batches"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_assigns_unique_isolated_workspace(self):
        a = bl.create_batch(self.root, label="batch-a")
        b = bl.create_batch(self.root, label="batch-b")
        self.assertNotEqual(a["batch_id"], b["batch_id"])
        self.assertTrue(bl.NEW_BATCH_RE.fullmatch(a["batch_id"]))
        for entry in (a, b):
            directory = bl.batch_dir(self.root, entry["batch_id"])
            for sub in bl.SUBDIRS:
                self.assertTrue((directory / sub).is_dir(), sub)
            self.assertTrue((directory / "batch.json").is_file())
        self.assertEqual(len(bl.list_batches(self.root)), 2)

    def test_many_batches_get_distinct_ids(self):
        ids = {bl.create_batch(self.root)["batch_id"] for _ in range(25)}
        self.assertEqual(len(ids), 25)

    def test_historical_batch_does_not_block_new_work(self):
        manifest = self.root / "old" / "manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"batch_id": "betta-20261010-000000-old123"}), encoding="utf-8")
        historical = bl.register_historical(self.root, manifest)
        self.assertEqual(historical["status"], bl.COMPLETE)
        fresh = bl.create_batch(self.root, label="next-batch")
        active = bl.active_batches(self.root)
        self.assertEqual([e["batch_id"] for e in active], [fresh["batch_id"]])
        self.assertNotIn(historical["batch_id"], [e["batch_id"] for e in active])

    def test_closed_batch_is_immutable(self):
        entry = bl.create_batch(self.root)
        bl.close_batch(self.root, entry["batch_id"])
        with self.assertRaises(bl.BatchLifecycleError):
            bl.assert_batch_writable(self.root, entry["batch_id"])
        # idempotent close preserves the original record
        first = bl.get_batch(self.root, entry["batch_id"])
        second = bl.close_batch(self.root, entry["batch_id"])
        self.assertEqual(first["closed_at"], second["closed_at"])
        self.assertEqual(second["status"], bl.COMPLETE)

    def test_abandoned_batch_is_terminal(self):
        entry = bl.create_batch(self.root)
        bl.close_batch(self.root, entry["batch_id"], bl.ABANDONED)
        self.assertEqual(bl.get_batch(self.root, entry["batch_id"])["status"], bl.ABANDONED)
        with self.assertRaises(bl.BatchLifecycleError):
            bl.assert_batch_writable(self.root, entry["batch_id"])

    def test_register_historical_preserves_existing(self):
        manifest = self.root / "m.json"
        manifest.write_text(json.dumps({"batch_id": "betta-20261010-010101-abc123"}), encoding="utf-8")
        bl.register_historical(self.root, manifest)
        marker = bl.batch_dir(self.root, "betta-20261010-010101-abc123") / "reports" / "keep.json"
        marker.write_text("{}", encoding="utf-8")
        bl.register_historical(self.root, manifest)  # must not clobber
        self.assertTrue(marker.is_file())

    def test_invalid_manifest_batch_id_rejected(self):
        manifest = self.root / "bad.json"
        manifest.write_text(json.dumps({"batch_id": "bad id with spaces"}), encoding="utf-8")
        with self.assertRaises(bl.BatchLifecycleError):
            bl.register_historical(self.root, manifest)

    def test_unknown_batch_errors(self):
        with self.assertRaises(bl.BatchLifecycleError):
            bl.assert_batch_writable(self.root, "betta-20260101-000000-zzzzzz")
        with self.assertRaises(bl.BatchLifecycleError):
            bl.batch_status(self.root, "betta-20260101-000000-zzzzzz")

    def test_status_reports_workspace_and_counts(self):
        entry = bl.create_batch(self.root)
        (bl.batch_dir(self.root, entry["batch_id"]) / "intake" / "photo.png").write_bytes(b"x")
        status = bl.batch_status(self.root, entry["batch_id"])
        self.assertEqual(status["counts"]["intake"], 1)
        self.assertEqual(status["batch"]["status"], bl.ACTIVE)

    def test_concurrent_creation_is_serialized(self):
        results = []
        lock = threading.Lock()

        def worker():
            entry = bl.create_batch(self.root)
            with lock:
                results.append(entry["batch_id"])

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(set(results)), 8)
        self.assertEqual(len(bl.list_batches(self.root)), 8)


if __name__ == "__main__":
    unittest.main()
