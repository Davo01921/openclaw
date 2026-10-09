"""Offline integration tests for the Betta runtime.

Fake adapters, temporary ledgers, temporary SQLite databases and synthetic files
only. No network, Shopify or paid model calls are made. The tests exercise the
complete intake-to-archive path plus failures, recovery, duplicate intake,
concurrent processing and completed-batch resume.
"""

import hashlib
import importlib.util
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "betta_runtime.py"
spec = importlib.util.spec_from_file_location("betta_runtime", SCRIPT)
rt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rt)
bb = rt.bb


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeWorld:
    def __init__(self):
        self.clock = rt.SystemClock()
        self.catalogue = {}
        self.snapshots = {}
        self.sha_to_tank = {}
        self.product_tank = {}
        self.mutate_result = {"ok": True, "user_errors": []}
        self.applied_on_uncertain = False
        self.fail_hero = False

    def add_tank(self, tank_id, *, name="Galaxy Koi", tail="Halfmoon", photo_date="2026-09-04",
                 inventory=1, product_seq=1):
        self.catalogue[tank_id] = {
            "tank_id": tank_id, "fish_name": name, "tail_type": tail,
            "sex": None, "sex_confidence": 0.0, "photo_date": photo_date,
        }
        product_id = f"gid://shopify/Product/{product_seq}"
        snapshot = {
            "id": product_id,
            "variant_id": f"gid://shopify/ProductVariant/{product_seq}",
            "location_id": f"gid://shopify/Location/{product_seq}",
            "source": "FRESH_SHOPIFY_READ",
            "tank_id": tank_id,
            "before": {
                "description": f"desc-{tank_id}", "price": "49.00", "cost": "18.00",
                "vendor": "NTA", "product_type": "Betta", "handle": f"betta-{tank_id.lower()}",
                "status": "ACTIVE", "inventory": inventory, "inventory_policy": "DENY",
                "tracked": True, "title": f"Old {tank_id}",
                "arrival_date": "2026-01-01", "media_hashes": ["a" * 64, "b" * 64],
            },
        }
        self.snapshots[tank_id] = snapshot
        self.product_tank[product_id] = tank_id


class FakeSourceStore:
    def __init__(self, root, world):
        self.root = Path(root)
        self.world = world

    def save(self, attachment, tank_id):
        data = Path(attachment["path"]).read_bytes()
        dest = self.root / "sources" / f"{tank_id}-source.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        digest = sha(data)
        self.world.sha_to_tank[digest] = tank_id
        return {"path": str(dest), "sha256": digest}


class FakeVision:
    def __init__(self, world):
        self.world = world

    def catalogue(self, asset):
        tank = self.world.sha_to_tank[asset["sha256"]]
        output = dict(self.world.catalogue[tank])
        return {
            "provider": "fake", "model": "fake-vision",
            "call_id": f"cat-{tank}-{sha(tank.encode())[:8]}",
            "timestamp": self.world.clock.now(), "input_hashes": [asset["sha256"]],
            "output": output,
        }

    def qa(self, source, hero, original):
        return {
            "provider": "fake", "model": "fake-vision", "call_id": f"qa-{hero['sha256'][:8]}",
            "timestamp": self.world.clock.now(),
            "input_hashes": [source["sha256"], hero["sha256"], original["sha256"]],
            "output": {"verdict": "PASS"},
            "assertions": {key: "PASS" for key in bb.QA_VISUAL}, "overall": "PASS",
        }


class FakeHero:
    def __init__(self, root, world):
        self.root = Path(root)
        self.world = world

    def generate(self, ledger, item_id):
        if self.world.fail_hero:
            raise RuntimeError("simulated hero generation failure")
        dest = self.root / "heroes" / f"{item_id}.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = ("hero-" + item_id).encode()
        dest.write_bytes(data)
        return {
            "asset": {"path": str(dest), "sha256": sha(data)},
            "record": {
                "provider": "xai", "model": "grok-imagine-image-2.0",
                "tokens_input": 0, "tokens_output": 0, "grokai_cost": 0.07,
                "grokai_cost_currency": "USD", "grokai_cost_source": "nta_default_0.07",
            },
        }


class FakeShopify:
    def __init__(self, world):
        self.world = world
        self.applied = False
        self.last_envelope = None
        self.reads = 0

    def resolve(self, tank_id):
        return {"status": "RESOLVED", "snapshot": self.world.snapshots[tank_id]}

    def mutate(self, envelope):
        self.last_envelope = envelope
        result = self.world.mutate_result
        if result.get("ok") is True and not result.get("user_errors") \
                and result.get("transport_ok") is not False:
            self.applied = True
        elif self.world.applied_on_uncertain:
            self.applied = True
        return result

    def read(self, product_id):
        self.reads += 1
        tank = self.world.product_tank[product_id]
        snapshot = self.world.snapshots[tank]
        before = snapshot["before"]
        readback = dict(before)
        readback.update({
            "source": "FRESH_SHOPIFY_READ", "product_id": snapshot["id"],
            "variant_id": snapshot["variant_id"], "location_id": snapshot["location_id"],
            "fetch_id": f"fetch-{self.reads}", "fetched_at": self.world.clock.now(),
            "writer_response_used": False,
        })
        if self.applied and self.last_envelope:
            changes = self.last_envelope["changes"]
            readback.update({
                "title": changes["title"], "arrival_date": changes["arrival_date"],
                "inventory": 1, "media_hashes": list(changes["media"]),
            })
        else:
            readback.update({
                "title": before["title"], "arrival_date": before["arrival_date"],
                "inventory": before["inventory"], "media_hashes": list(before["media_hashes"]),
            })
        return readback


class FakeArchiver:
    def __init__(self, root, world):
        self.root = Path(root)
        self.world = world

    def archive(self, item, archive_date):
        src_dir = self.root / "archived" / archive_date / "Betta Processing"
        hero_dir = self.root / "archived" / archive_date / "Betta Processed"
        src_dir.mkdir(parents=True, exist_ok=True)
        hero_dir.mkdir(parents=True, exist_ok=True)
        ext = Path(item["source"]["path"]).suffix
        dest_source = src_dir / f"{item['id']} Original {archive_date}{ext}"
        dest_hero = hero_dir / f"{item['id']}.png"
        shutil.copy2(item["source"]["path"], dest_source)
        shutil.copy2(item["images"]["hero"]["path"], dest_hero)
        return {
            "verified_at": self.world.clock.now(),
            "source": {"path": str(dest_source), "sha256": item["source"]["sha256"]},
            "hero": {"path": str(dest_hero), "sha256": item["images"]["hero"]["sha256"]},
        }


class IntegrationTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.world = FakeWorld()
        self.world.add_tank("4BT41", product_seq=1)

    def tearDown(self):
        self.tmp.cleanup()

    def make_runtime(self):
        return rt.BettaRuntime(
            ledger_path=self.root / "ledger.json",
            intake_registry_path=self.root / "intake.sqlite3",
            telemetry_db=self.root / "telemetry.sqlite3",
            source_store=FakeSourceStore(self.root, self.world),
            vision=FakeVision(self.world),
            hero_generator=FakeHero(self.root, self.world),
            shopify=FakeShopify(self.world),
            archiver=FakeArchiver(self.root, self.world),
        )

    def attachment(self, tank_id, data=None):
        path = self.root / f"{tank_id}-upload.raw"
        path.write_bytes(data if data is not None else tank_id.encode())
        return {"path": str(path)}

    def run_full(self, runtime, tank_id="4BT41"):
        return runtime.run_to_archive(
            batch_id="batch-1", tank_id=tank_id, attachment=self.attachment(tank_id),
            csv_path=self.root / "betta-inventory.csv", archive_date="2026-10-09",
        )


class FullPathTests(IntegrationTestCase):
    def test_complete_intake_to_archive(self):
        runtime = self.make_runtime()
        record = self.run_full(runtime)
        ledger = runtime.store.read()
        item = ledger["items"][0]
        self.assertEqual(item["state"], "ARCHIVED")
        self.assertEqual(ledger["batch_state"], "DONE")
        self.assertTrue(rt.telemetry_row_exists(runtime.telemetry_db, "batch-1", "4BT41"))
        rt.validate_inventory_csv(
            (self.root / "betta-inventory.csv").read_text(), [item])
        for asset in (record["source"], record["hero"]):
            self.assertEqual(rt.bb.sha256(asset["path"]), asset["sha256"])
        # Approved hero first, byte-identical source second.
        self.assertEqual(item["mutation"]["media"],
                         [item["images"]["hero"]["sha256"], item["source"]["sha256"]])
        self.assertEqual(item["readback"]["inventory"], 1)

    def test_rejected_mutation_holds_item(self):
        self.world.mutate_result = {"ok": True, "user_errors": [{"message": "denied"}]}
        runtime = self.make_runtime()
        runtime.intake("batch-1", "4BT41", self.attachment("4BT41"))
        runtime.catalogue("4BT41")
        runtime.prepare("4BT41")
        runtime.build_csv(self.root / "betta-inventory.csv")
        runtime.run_image_qa("4BT41")
        runtime.begin_mutation("4BT41")
        self.assertEqual(runtime.apply_mutation("4BT41"), rt.REJECTED)
        self.assertEqual(runtime.store.read()["items"][0]["state"], "FIX_REQUIRED")

    def test_qa_uses_bound_source_hero_and_original(self):
        runtime = self.make_runtime()
        self.run_full(runtime)
        item = runtime.store.read()["items"][0]
        expected = [item["source"]["sha256"], item["images"]["hero"]["sha256"], item["source"]["sha256"]]
        self.assertEqual(item["image_qa"]["visual"]["input_hashes"], expected)


class UncertainWriteTests(IntegrationTestCase):
    def _drive_to_mutation(self, runtime):
        runtime.intake("batch-1", "4BT41", self.attachment("4BT41"))
        runtime.catalogue("4BT41")
        runtime.prepare("4BT41")
        runtime.build_csv(self.root / "betta-inventory.csv")
        runtime.run_image_qa("4BT41")
        runtime.begin_mutation("4BT41")

    def test_uncertain_write_never_auto_retries(self):
        self.world.mutate_result = {"transport_ok": False, "error": "socket reset"}
        runtime = self.make_runtime()
        self._drive_to_mutation(runtime)
        self.assertEqual(runtime.apply_mutation("4BT41"), rt.UNCERTAIN)
        self.assertEqual(runtime.store.read()["items"][0]["state"], "MUTATION_UNCERTAIN")
        with self.assertRaises(bb.LedgerError):
            runtime.apply_mutation("4BT41")

    def test_uncertain_not_applied_holds_for_operator(self):
        self.world.mutate_result = {"transport_ok": False}
        runtime = self.make_runtime()
        self._drive_to_mutation(runtime)
        runtime.apply_mutation("4BT41")
        self.assertEqual(runtime.reconcile("4BT41"), "NOT_APPLIED")
        self.assertEqual(runtime.store.read()["items"][0]["state"], "MUTATION_UNCERTAIN")

    def test_uncertain_not_applied_with_authority_returns_to_pending(self):
        self.world.mutate_result = {"transport_ok": False}
        runtime = self.make_runtime()
        self._drive_to_mutation(runtime)
        runtime.apply_mutation("4BT41")
        runtime.reconcile("4BT41", retry_authorised=True)
        self.assertEqual(runtime.store.read()["items"][0]["state"], "MUTATION_PENDING")

    def test_uncertain_that_actually_applied_recovers(self):
        self.world.mutate_result = {"transport_ok": False}
        self.world.applied_on_uncertain = True
        runtime = self.make_runtime()
        self._drive_to_mutation(runtime)
        runtime.apply_mutation("4BT41")
        self.assertEqual(runtime.reconcile("4BT41"), "APPLIED")
        self.assertEqual(runtime.store.read()["items"][0]["state"], "MUTATED")
        runtime.verify("4BT41")
        runtime.finalize("4BT41")
        self.assertEqual(runtime.store.read()["items"][0]["state"], "PASS")


class DuplicateIntakeTests(IntegrationTestCase):
    def test_cross_batch_duplicate_source_rejected(self):
        runtime = self.make_runtime()
        attachment = self.attachment("4BT41")
        runtime.intake("batch-1", "4BT41", attachment)
        with self.assertRaises(rt.DuplicateIntake):
            runtime.intake("batch-2", "4BT41", attachment)

    def test_recorded_duplicate_allowed(self):
        runtime = self.make_runtime()
        attachment = self.attachment("4BT41")
        runtime.intake("batch-1", "4BT41", attachment)
        runtime.intake(
            "batch-2", "4BT41", attachment,
            intake_ref="resend", allow_duplicate_of="batch-1:4BT41",
        )
        self.assertEqual(len(runtime.intake_registry.find(sha(attachment_path_bytes(attachment)))), 2)


class ResumeTests(IntegrationTestCase):
    def test_completed_batch_resume_does_no_work(self):
        runtime = self.make_runtime()
        self.run_full(runtime)
        ledger = runtime.store.read()
        self.assertEqual(bb.execution_plan(ledger, 4)["waves"], [])
        previous = ledger["items"][0]["state"]
        runtime.intake("batch-1", "4BT41", self.attachment("4BT41"))  # idempotent
        self.assertEqual(len(runtime.store.read()["items"]), 1)
        self.assertEqual(runtime.store.read()["items"][0]["state"], previous)
        with self.assertRaises(bb.LedgerError):
            runtime.apply_mutation("4BT41")

    def test_partial_resume_only_runs_missing_branch(self):
        runtime = self.make_runtime()
        runtime.intake("batch-1", "4BT41", self.attachment("4BT41"))
        runtime.catalogue("4BT41")
        # Shopify resolves, hero generation fails: only the missing branch remains.
        self.world.fail_hero = True
        with self.assertRaises(RuntimeError):
            runtime.prepare("4BT41")
        ledger = runtime.store.read()
        self.assertEqual(ledger["items"][0]["state"], "VISUAL_ACCEPTED")
        plan = bb.parallel_preparation_plan(ledger, 4)
        self.assertEqual([task["operation"] for task in plan["tasks"]], ["grok_hero"])
        self.assertEqual(plan["ready_to_join"], [])
        # Retry resumes only the hero branch and then joins.
        self.world.fail_hero = False
        self.assertEqual(runtime.prepare("4BT41")["tasks"], ["grok_hero"])
        self.assertEqual(runtime.store.read()["items"][0]["state"], "PRODUCT_RESOLVED")


class ConcurrencyTests(IntegrationTestCase):
    def test_two_items_process_concurrently_on_one_ledger(self):
        self.world.add_tank("5BT51", product_seq=2)
        runtime = self.make_runtime()
        tanks = ["4BT41", "5BT51"]
        for tank in tanks:
            runtime.intake("batch-1", tank, self.attachment(tank))

        def catalogue(tank):
            runtime.catalogue(tank)

        def prepare(tank):
            runtime.prepare(tank)

        for stage in (catalogue, prepare):
            threads = [threading.Thread(target=stage, args=(tank,)) for tank in tanks]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        ledger = runtime.store.read()
        bb.validate_ledger(ledger)
        self.assertEqual({item["state"] for item in ledger["items"]}, {"PRODUCT_RESOLVED"})
        self.assertEqual(len({item["product"]["id"] for item in ledger["items"]}), 2)


def attachment_path_bytes(attachment):
    return Path(attachment["path"]).read_bytes()


if __name__ == "__main__":
    unittest.main()

