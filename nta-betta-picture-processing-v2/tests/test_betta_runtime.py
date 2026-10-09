"""Offline unit tests for the Betta runtime safety helpers.

No network, Shopify or paid model calls are made. Temporary ledgers, temporary
SQLite databases and synthetic files only.
"""

import hashlib
import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "betta_runtime.py"
spec = importlib.util.spec_from_file_location("betta_runtime", SCRIPT)
rt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rt)
bb = rt.bb


def write_file(path: Path, data: bytes) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def protected_snapshot() -> dict:
    snapshot = {key: f"before-{key}" for key in bb.PROTECTED}
    snapshot.update(status="ACTIVE", inventory=1, inventory_policy="DENY", tracked=True)
    return snapshot


def mutation_item(root: Path, tank: str = "4BT41") -> dict:
    source = write_file(root / f"{tank}-source.png", tank.encode())
    hero = write_file(root / f"{tank}-hero.png", (tank + "-hero").encode())
    title = f"{tank} - Galaxy Koi Halfmoon Male"
    before = protected_snapshot()
    before.update(title="Old Title", arrival_date="2026-01-01",
                  media_hashes=["a" * 64, "b" * 64])
    return {
        "id": tank,
        "state": "MUTATION_PENDING",
        "history": [{"from": None, "to": "DISCOVERED", "at": "2026-10-09T00:00:00+00:00"}],
        "source": source,
        "catalogue": {
            "tank_id": tank,
            "photo_date": "2026-09-04",
            "fish_name": "Galaxy Koi",
            "tail_type": "Halfmoon",
            "sex": "Male",
            "sex_confidence": 0.0,
            "title": title,
            "evidence": {
                "provider": "fake", "model": "fake-vision", "call_id": f"cat-{tank}",
                "timestamp": "2026-10-09T00:00:00+00:00",
                "input_hashes": [source["sha256"]], "output": {"tank_id": tank},
            },
        },
        "product": {
            "id": "gid://shopify/Product/1",
            "variant_id": "gid://shopify/ProductVariant/1",
            "location_id": "gid://shopify/Location/1",
            "source": "FRESH_SHOPIFY_READ",
            "tank_id": tank,
            "before": before,
        },
        "images": {"hero": hero},
        "image_qa": {
            "deterministic": {key: "PASS" for key in bb.QA_DETERMINISTIC},
            "visual": {
                "provider": "fake", "model": "fake-vision", "call_id": f"qa-{tank}",
                "timestamp": "2026-10-09T00:00:00+00:00",
                "input_hashes": [source["sha256"], hero["sha256"], source["sha256"]],
                "output": {"verdict": "PASS"},
                "assertions": {key: "PASS" for key in bb.QA_VISUAL}, "overall": "PASS",
            },
            "outcome": "PASS",
        },
        "mutation": {
            "title": title, "arrival_date": "2026-09-04", "inventory": 1,
            "media": [hero["sha256"], source["sha256"]],
        },
        "write": {"write_id": "write-1", "completed_at": "2026-10-09T00:00:00+00:00",
                  "baseline": {"title": "Old Title", "arrival_date": "2026-01-01",
                               "media_hashes": ["a" * 64, "b" * 64]}},
    }


def readback_for(item: dict, *, applied: bool, fetch_id: str = "fetch-1") -> dict:
    before = item["product"]["before"]
    after = dict(before)
    after.update({
        "source": "FRESH_SHOPIFY_READ",
        "product_id": item["product"]["id"],
        "variant_id": item["product"]["variant_id"],
        "location_id": item["product"]["location_id"],
        "fetch_id": fetch_id,
        "fetched_at": "2026-10-09T00:00:05+00:00",
        "writer_response_used": False,
    })
    if applied:
        after.update({
            "title": item["mutation"]["title"],
            "arrival_date": item["mutation"]["arrival_date"],
            "inventory": 1,
            "media_hashes": list(item["mutation"]["media"]),
        })
    else:
        after.update({
            "title": "Old Title", "arrival_date": "2026-01-01",
            "inventory": before["inventory"], "media_hashes": ["a" * 64, "b" * 64],
        })
    return after


class LedgerStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.item = mutation_item(self.root)
        self.item["state"] = "SAVED"
        self.ledger = {"schema_version": 2, "batch_id": "b1", "batch_state": "PROCESSING",
                       "items": [self.item]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_update_persists_and_validates(self):
        path = self.root / "ledger.json"
        bb.save(path, self.ledger)
        store = rt.LedgerStore(path)

        def mutate(data):
            data["items"][0]["history"].append(
                {"from": "SAVED", "to": "VISUAL_PENDING", "at": "2026-10-09T01:00:00+00:00"})
            data["items"][0]["state"] = "VISUAL_PENDING"
            return "ok"

        self.assertEqual(store.update(mutate), "ok")
        self.assertEqual(json.loads(path.read_text())["items"][0]["state"], "VISUAL_PENDING")

    def test_update_rejects_invalid_result_without_touching_disk(self):
        path = self.root / "ledger.json"
        bb.save(path, self.ledger)
        store = rt.LedgerStore(path)
        previous = path.read_bytes()

        def mutate(data):
            data["items"][0]["source"]["sha256"] = "0" * 64  # breaks file hash gate
            return None

        with self.assertRaises(bb.LedgerError):
            store.update(mutate)
        self.assertEqual(path.read_bytes(), previous)

    def test_concurrent_updates_are_serialized(self):
        path = self.root / "ledger.json"
        ledger = dict(self.ledger)
        ledger["counter"] = 0
        bb.save(path, ledger)
        store = rt.LedgerStore(path, lock_timeout=30.0)
        threads = []

        def worker():
            for _ in range(25):
                def mutate(data):
                    data["counter"] = int(data.get("counter", 0)) + 1
                store.update(mutate)

        for _ in range(8):
            thread = threading.Thread(target=worker)
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(json.loads(path.read_text())["counter"], 200)


class IntakeRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.registry = rt.IntakeRegistry(self.root / "intake.sqlite3")
        self.asset = write_file(self.root / "a.png", b"fish-a")

    def tearDown(self):
        self.tmp.cleanup()

    def test_rejects_duplicate_intake_across_batches(self):
        self.registry.register("batch-1", "4BT41", "4BT41", self.asset, "2026-10-09T00:00:00+00:00")
        with self.assertRaises(rt.DuplicateIntake):
            self.registry.register("batch-2", "4BT41", "4BT41", self.asset, "2026-10-10T00:00:00+00:00")

    def test_recorded_duplicate_is_allowed(self):
        self.registry.register("batch-1", "4BT41", "4BT41", self.asset, "2026-10-09T00:00:00+00:00")
        allowed = self.registry.register(
            "batch-2", "9BT99", "9BT99", self.asset, "2026-10-10T00:00:00+00:00",
            allow_duplicate_of="batch-1:4BT41",
        )
        self.assertEqual(allowed["allowed_duplicate_of"], "batch-1:4BT41")

    def test_idempotent_same_reference(self):
        first = self.registry.register("batch-1", "4BT41", "4BT41", self.asset, "2026-10-09T00:00:00+00:00")
        second = self.registry.register("batch-1", "4BT41", "4BT41", self.asset, "2026-10-09T00:00:00+00:00")
        self.assertEqual(first["source_sha256"], second["source_sha256"])
        self.assertEqual(len(self.registry.find(self.asset["sha256"])), 1)


class ClassificationTests(unittest.TestCase):
    def test_write_applied(self):
        self.assertEqual(rt.classify_write_result({"ok": True, "user_errors": []}), (rt.APPLIED, None))

    def test_write_rejected_on_user_error(self):
        result = rt.classify_write_result({"ok": True, "user_errors": [{"message": "bad"}]})
        self.assertEqual(result, (rt.REJECTED, "user_error"))

    def test_write_rejected_on_graphql_error(self):
        result = rt.classify_write_result({"ok": False, "graphql_errors": ["Access denied"]})
        self.assertEqual(result, (rt.REJECTED, "graphql_error"))

    def test_write_uncertain_on_transport_timeout_and_server(self):
        self.assertEqual(rt.classify_write_result({"transport_ok": False})[0], rt.UNCERTAIN)
        self.assertEqual(rt.classify_write_result({"status_code": 504})[0], rt.UNCERTAIN)
        throttled = rt.classify_write_result({"ok": False, "graphql_errors": ["Throttled, try again"]})
        self.assertEqual(throttled, (rt.UNCERTAIN, "server_error"))

    def test_write_uncertain_on_unknown_shape(self):
        self.assertEqual(rt.classify_write_result({})[0], rt.UNCERTAIN)

    def test_read_classification(self):
        self.assertEqual(rt.classify_read_result({"source": "FRESH_SHOPIFY_READ"}), rt.READ_OK)
        self.assertEqual(rt.classify_read_result({"transport_ok": False}), rt.READ_RETRYABLE)
        self.assertEqual(rt.classify_read_result({"source": "WRITER_RESPONSE"}), rt.READ_BLOCKED)


class IndependentReadbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.item = mutation_item(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_accepts_fresh_independent_read(self):
        rt.verify_independent_readback(self.item, readback_for(self.item, applied=True))

    def test_rejects_writer_derived_evidence(self):
        readback = readback_for(self.item, applied=True)
        readback["writer_response_used"] = True
        with self.assertRaises(bb.LedgerError):
            rt.verify_independent_readback(self.item, readback)

    def test_rejects_reused_writer_fetch_id(self):
        readback = readback_for(self.item, applied=True, fetch_id="write-1")
        with self.assertRaises(bb.LedgerError):
            rt.verify_independent_readback(self.item, readback)

    def test_rejects_read_before_write_completed(self):
        readback = readback_for(self.item, applied=True)
        readback["fetched_at"] = "2026-10-08T23:59:59+00:00"
        with self.assertRaises(bb.LedgerError):
            rt.verify_independent_readback(self.item, readback)

    def test_rejects_changed_protected_field(self):
        readback = readback_for(self.item, applied=True)
        readback["vendor"] = "someone-else"
        with self.assertRaises(bb.LedgerError):
            rt.verify_independent_readback(self.item, readback)


class CsvTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.item = mutation_item(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_and_validate(self):
        text = rt.build_inventory_csv([self.item])
        self.assertEqual(text.splitlines()[0], "Tank Number,Proposed Title,Cost,Retail Price")
        rt.validate_inventory_csv(text, [self.item])

    def test_rejects_wrong_header(self):
        with self.assertRaises(bb.LedgerError):
            rt.validate_inventory_csv("Tank,Title,Cost,Price\n4BT41,x,y,z\n", [self.item])

    def test_rejects_price_change(self):
        text = rt.build_inventory_csv([self.item]).replace("before-price", "0.01")
        with self.assertRaises(bb.LedgerError):
            rt.validate_inventory_csv(text, [self.item])

    def test_rejects_missing_row(self):
        with self.assertRaises(bb.LedgerError):
            rt.validate_inventory_csv("Tank Number,Proposed Title,Cost,Retail Price\n", [self.item])


class TelemetryGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "telemetry.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_row_blocks_pass(self):
        with self.assertRaises(bb.LedgerError):
            rt.require_telemetry_before_pass(self.db, "b1", "4BT41")

    def test_present_row_allows_pass(self):
        con = rt.bt.connect(self.db)
        rt.bt.upsert(con, {"batch_id": "b1", "tank_number": "4BT41",
                           "date_entered": "2026-10-09T00:00:00+10:00"})
        con.close()
        rt.require_telemetry_before_pass(self.db, "b1", "4BT41")


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.item = mutation_item(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_detects_applied(self):
        self.assertEqual(rt.determine_reconciliation(self.item, readback_for(self.item, applied=True)), "APPLIED")

    def test_detects_not_applied(self):
        self.assertEqual(rt.determine_reconciliation(self.item, readback_for(self.item, applied=False)), "NOT_APPLIED")

    def test_unresolved_on_partial_state(self):
        readback = readback_for(self.item, applied=True)
        readback["arrival_date"] = "2026-01-01"
        self.assertEqual(rt.determine_reconciliation(self.item, readback), "UNRESOLVED")

    def test_unresolved_on_changed_protected_field(self):
        readback = readback_for(self.item, applied=False)
        readback["price"] = "changed"
        self.assertEqual(rt.determine_reconciliation(self.item, readback), "UNRESOLVED")


class UncertainStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.item = mutation_item(Path(self.tmp.name))
        self.ledger = {"schema_version": 2, "batch_id": "b1", "batch_state": "PROCESSING",
                       "items": [self.item]}

    def tearDown(self):
        self.tmp.cleanup()

    def uncertain(self):
        self.item["uncertain_write"] = {
            "attempted_at": "2026-10-09T00:00:00+00:00", "reason": "timeout",
            "writer_result_class": "UNCERTAIN", "write_id": "write-1",
        }
        bb.advance(self.ledger, "4BT41", "MUTATION_UNCERTAIN")

    def test_uncertain_requires_recorded_result(self):
        with self.assertRaises(bb.LedgerError):
            bb.advance(self.ledger, "4BT41", "MUTATION_UNCERTAIN")

    def test_cannot_auto_retry_uncertain(self):
        self.uncertain()
        self.item["reconciliation"] = {"outcome": "NOT_APPLIED", "readback_at": "2026-10-09T00:01:00+00:00"}
        with self.assertRaises(bb.LedgerError):
            bb.advance(self.ledger, "4BT41", "MUTATION_PENDING")

    def test_not_applied_with_authority_can_retry(self):
        self.uncertain()
        self.item["reconciliation"] = {"outcome": "NOT_APPLIED", "readback_at": "2026-10-09T00:01:00+00:00",
                                       "retry_authorised": True}
        bb.advance(self.ledger, "4BT41", "MUTATION_PENDING")
        self.assertEqual(self.item["state"], "MUTATION_PENDING")

    def test_applied_reconciles_to_mutated(self):
        self.uncertain()
        self.item["reconciliation"] = {"outcome": "APPLIED", "readback_at": "2026-10-09T00:01:00+00:00"}
        bb.advance(self.ledger, "4BT41", "MUTATED")
        self.assertEqual(self.item["state"], "MUTATED")

    def test_uncertain_is_not_scheduled(self):
        self.uncertain()
        self.assertEqual(bb.execution_plan(self.ledger, 4)["waves"], [])


if __name__ == "__main__":
    unittest.main()

