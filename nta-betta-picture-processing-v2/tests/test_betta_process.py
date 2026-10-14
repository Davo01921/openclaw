"""Offline tests for the unified Betta batch orchestrator and standing policy."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bp = _load("betta_process_t", "betta_process.py")
policy_mod = _load("betta_policy_t", "betta_policy.py")
watch = _load("betta_watch_t", "betta_watch.py")
bl = _load("betta_batches_t", "betta_batches.py")


MANIFEST_HASH = "deadbeef" * 8


def policy(enabled=True, paid=True, manifest=MANIFEST_HASH):
    data = policy_mod.default_policy()
    data["enabled"] = enabled
    data["paid_generation_authorised"] = paid
    if manifest:
        data["authorisations"] = [{"manifest_sha256": manifest, "receipt": "owner-standing-approval", "at": "t"}]
    return policy_mod.StandingPolicy(data)


class FakeAdapters:
    def __init__(self, *, tanks, qa=None, uncertain=None, duplicates=None, resolved=True, execute_ok=True):
        self.tanks = tanks
        self.qa_results = qa or {t: {"outcome": "PASS"} for t in tanks}
        self.uncertain = uncertain or set()
        self.duplicates = duplicates or {}
        self.resolved = resolved
        self.execute_ok = execute_ok
        self.calls = {"generate": 0, "execute": 0, "reconcile": 0,
                      "telemetry": 0, "archive": 0}

    def intake(self, batch_dir, state):
        return {"fish": [{"path": f"/src/{t}.png", "sha256": f"hash-{t}"} for t in self.tanks]}

    def identify(self, record, batch_dir):
        t = Path(record["path"]).stem
        tank = self.duplicates.get(t, t)
        return {"tank_id": tank, "photo_date": "2026-10-09", "uncertain": t in self.uncertain}

    def generate(self, entry, batch_dir):
        self.calls["generate"] += 1
        return {"hero_path": f"/heroes/{entry['tank_id']}.png", "hero_sha256": f"hero-{entry['tank_id']}"}

    def finish(self, entry, batch_dir):
        return None

    def qa(self, entry, batch_dir):
        return self.qa_results.get(entry["tank_id"], {"outcome": "PASS"})

    def resolve(self, entry, batch_dir):
        if not self.resolved:
            return {"status": "AMBIGUOUS"}
        return {"status": "RESOLVED", "product": {"id": f"gid://shopify/Product/{entry['tank_id']}"}}

    def build_manifest(self, state, batch_dir):
        published = [k for k, e in state["fish"].items()
                     if e["status"] in (bp.FISH_PASS, bp.FISH_PASS_EXCEPTION)]
        return {"manifest": {"items": published}, "manifest_sha256": MANIFEST_HASH}

    def execute(self, entry, state, batch_dir):
        self.calls["execute"] += 1
        if not self.execute_ok:
            return {"status": "FAILED"}
        return {"status": "VERIFIED", "receipt": f"receipt-{entry['tank_id']}"}

    def reconcile(self, entry, state, batch_dir):
        self.calls["reconcile"] += 1
        return {"status": "READ_ONLY_VERIFIED", "receipt": f"verified-{entry['tank_id']}"}

    def telemetry(self, state, batch_dir):
        self.calls["telemetry"] += 1

    def archive(self, state, batch_dir):
        self.calls["archive"] += 1


class AutomaticPolicy:
    """Minimal automatic-batch policy fixture (no uploader manifest involved)."""

    def __init__(self):
        self.data = {"automatic_batch_authorisation": True}

    def paid_generation_authorised(self):
        return True

    def authorise_manifest(self, manifest_path, receipt_path, expected_sha256=None):
        return {"kind": "fixture", "manifest_sha256": expected_sha256}


class AutomaticAdapters(FakeAdapters):
    """FakeAdapters plus the automatic-only pre-generation eligibility seam."""

    def __init__(self, *, eligibility=None, **kwargs):
        super().__init__(**kwargs)
        self.eligibility_results = eligibility or {}
        self.calls["resolve"] = 0

    def eligibility(self, entry, state, batch_dir):
        return self.eligibility_results.get(
            entry["tank_id"],
            {"eligible": True, "reason": "fixture baseline",
             "product": {"id": f"gid://shopify/Product/{entry['tank_id']}"}})

    def resolve(self, entry, batch_dir):
        self.calls["resolve"] += 1
        return super().resolve(entry, batch_dir)

    def build_manifest(self, state, batch_dir):
        base = super().build_manifest(state, batch_dir)
        path = Path(batch_dir) / "manifest" / "fixture.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(base["manifest"]), encoding="utf-8")
        base["manifest_path"] = str(path)
        return base

    def archive(self, state, batch_dir):
        self.calls["archive"] += 1
        return {"status": "ARCHIVED", "batch_status": "COMPLETE"}


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.batches = self.root / "batches"
        entry = bl.create_batch(self.batches, label="test")
        self.batch_dir = Path(entry["path"])
        (self.batch_dir / "state").mkdir(parents=True, exist_ok=True)
        self.batch_id = entry["batch_id"]

    def tearDown(self):
        self.tmp.cleanup()

    def drive(self, adapters, pol, include=()):
        names = ("intake", "identify", "generate", "finish", "qa", "resolve",
                 "build_manifest", "execute", "reconcile", "telemetry", "archive")
        return bp.process_batch(self.batch_dir, self.batch_id, adapters={
            m: getattr(adapters, m) for m in names + tuple(include)}, policy=pol)

    def test_full_happy_path_completes(self):
        adapters = FakeAdapters(tanks=["2BT12", "3BT21"])
        summary = self.drive(adapters, policy())
        self.assertEqual(summary["status"], "COMPLETE")
        self.assertEqual(summary["published"], 2)
        self.assertEqual(adapters.calls["generate"], 2)
        self.assertEqual(adapters.calls["execute"], 2)
        self.assertEqual(adapters.calls["telemetry"], 1)

    def test_resume_never_repeats_paid_or_shopify(self):
        adapters = FakeAdapters(tanks=["2BT12"])
        self.drive(adapters, policy())
        first = dict(adapters.calls)
        self.drive(adapters, policy())  # restart
        self.assertEqual(adapters.calls["generate"], first["generate"])
        self.assertEqual(adapters.calls["execute"], first["execute"])

    def test_paid_generation_disabled_awaits_authorisation(self):
        adapters = FakeAdapters(tanks=["2BT12"])
        summary = self.drive(adapters, policy(paid=False))
        self.assertEqual(summary["status"], "AWAITING_AUTHORISATION")
        self.assertEqual(adapters.calls["generate"], 0)

    def test_policy_disabled_awaits_authorisation_before_write(self):
        adapters = FakeAdapters(tanks=["2BT12"])
        summary = self.drive(adapters, policy(enabled=False))
        self.assertEqual(summary["status"], "AWAITING_AUTHORISATION")
        self.assertEqual(adapters.calls["execute"], 0)

    def test_wrong_manifest_hash_awaits_authorisation(self):
        adapters = FakeAdapters(tanks=["2BT12"])
        summary = self.drive(adapters, policy(manifest="different" * 4))
        self.assertEqual(summary["status"], "AWAITING_AUTHORISATION")
        self.assertEqual(adapters.calls["execute"], 0)

    def test_qa_failure_quarantines_without_publishing(self):
        adapters = FakeAdapters(tanks=["2BT12", "3BT21"],
                                qa={"2BT12": {"outcome": "PASS"},
                                    "3BT21": {"outcome": "FAIL", "failed_assertions": ["same_identity"]}})
        summary = self.drive(adapters, policy())
        self.assertEqual(summary["published"], 1)
        self.assertEqual(summary["quarantined"], 1)
        self.assertEqual(adapters.calls["execute"], 1)

    def test_accepted_exception_publishes_but_is_not_a_plain_pass(self):
        adapters = FakeAdapters(tanks=["2BT12"],
                                qa={"2BT12": {"outcome": "FAIL", "failed_assertions": ["label"],
                                              "accepted_exception": {"accepted_by": "owner"}}})
        self.drive(adapters, policy())
        state = json.loads((self.batch_dir / "state" / "process.json").read_text())
        entry = next(e for e in state["fish"].values() if e["tank_id"] == "2BT12")
        self.assertEqual(entry["status"], bp.FISH_PASS_EXCEPTION)

    def test_uncertain_identification_quarantines(self):
        adapters = FakeAdapters(tanks=["2BT12"], uncertain={"2BT12"})
        summary = self.drive(adapters, policy())
        self.assertEqual(summary["quarantined"], 1)
        self.assertEqual(adapters.calls["generate"], 0)

    def test_duplicate_tank_ids_quarantine_all_clashes(self):
        adapters = FakeAdapters(tanks=["2BT12", "3BT21"], duplicates={"2BT12": "9BT99", "3BT21": "9BT99"})
        summary = self.drive(adapters, policy())
        self.assertEqual(summary["published"], 0)
        self.assertEqual(summary["quarantined"], 2)

    def test_unresolved_shopify_product_quarantines(self):
        adapters = FakeAdapters(tanks=["2BT12"], resolved=False)
        summary = self.drive(adapters, policy())
        self.assertEqual(summary["published"], 0)
        self.assertEqual(adapters.calls["execute"], 0)

    def test_failed_shopify_execute_quarantines(self):
        adapters = FakeAdapters(tanks=["2BT12"], execute_ok=False)
        summary = self.drive(adapters, policy())
        self.assertEqual(summary["published"], 0)
        self.assertEqual(summary["quarantined"], 1)

    def test_generation_uncertainty_remains_recoverable_and_not_quarantined(self):
        class Pending(RuntimeError):
            reconciliation_pending = True

        adapters = FakeAdapters(tanks=["2BT12"])

        def uncertain(entry, batch_dir):
            adapters.calls["generate"] += 1
            raise Pending("provider result unknown")

        adapters.generate = uncertain
        first = self.drive(adapters, policy())
        second = self.drive(adapters, policy())
        self.assertEqual(first["status"], "RECONCILIATION_PENDING")
        self.assertEqual(second["status"], "RECONCILIATION_PENDING")
        self.assertEqual(first["quarantined"], 0)
        state = json.loads((self.batch_dir / "state" / "process.json").read_text())
        entry = next(iter(state["fish"].values()))
        self.assertEqual(entry["status"], bp.FISH_RECONCILIATION_PENDING)
        self.assertEqual(entry["pending_kind"], "generation")

    def test_focused_label_retry_recovers_an_uncertain_identification(self):
        adapters = FakeAdapters(tanks=["2BT12"], uncertain={"2BT12"})
        retries = {"count": 0}

        def retry(entry, batch_dir):
            retries["count"] += 1
            return {"uncertain": False, "tank_id": "2BT12", "photo_date": "2026-10-09",
                    "proposed_title": "2BT12 - Blue Red Marble Halfmoon Male"}

        adapters.retry_identify = retry
        summary = self.drive(adapters, policy(), include=("retry_identify",))
        self.assertEqual(summary["status"], "COMPLETE")
        self.assertEqual(summary["published"], 1)
        self.assertEqual(adapters.calls["generate"], 1)
        self.assertEqual(retries["count"], 1)
        state = json.loads((self.batch_dir / "state" / "process.json").read_text())
        entry = next(iter(state["fish"].values()))
        self.assertEqual(entry["tank_id"], "2BT12")
        self.assertEqual(entry["notes"], ["focused label retry accepted"])

    def test_focused_label_retry_runs_once_and_never_repeats(self):
        adapters = FakeAdapters(tanks=["2BT12"], uncertain={"2BT12"})
        retries = {"count": 0}

        def retry(entry, batch_dir):
            retries["count"] += 1
            return {"uncertain": True, "tank_id": None, "photo_date": None}

        adapters.retry_identify = retry
        first = self.drive(adapters, policy(), include=("retry_identify",))
        second = self.drive(adapters, policy(), include=("retry_identify",))
        self.assertEqual(first["quarantined"], 1)
        self.assertEqual(second["quarantined"], 1)
        self.assertEqual(retries["count"], 1)
        self.assertEqual(adapters.calls["generate"], 0)

    def test_focused_label_retry_rechecks_duplicate_tank_ids(self):
        adapters = FakeAdapters(tanks=["2BT12", "3BT21"], uncertain={"3BT21"})

        def retry(entry, batch_dir):
            return {"uncertain": False, "tank_id": "2BT12", "photo_date": "2026-10-09",
                    "proposed_title": "2BT12 - Blue Red Marble Halfmoon Male"}

        adapters.retry_identify = retry
        summary = self.drive(adapters, policy(), include=("retry_identify",))
        self.assertEqual(summary["published"], 0)
        self.assertEqual(summary["quarantined"], 2)

    def test_focused_label_retry_failure_is_recorded_without_crashing(self):
        adapters = FakeAdapters(tanks=["2BT12"], uncertain={"2BT12"})

        def retry(entry, batch_dir):
            raise RuntimeError("label crop call failed")

        adapters.retry_identify = retry
        summary = self.drive(adapters, policy(), include=("retry_identify",))
        self.assertEqual(summary["quarantined"], 1)
        state = json.loads((self.batch_dir / "state" / "process.json").read_text())
        entry = next(iter(state["fish"].values()))
        self.assertEqual(entry["notes"], ["focused label retry failed"])
        self.assertIn("label crop call failed", entry["identify_error"])

    def test_automatic_eligibility_quarantines_ineligible_before_any_spend(self):
        adapters = AutomaticAdapters(
            tanks=["2BT12", "3BT21"],
            eligibility={"3BT21": {
                "eligible": False,
                "reason": ("shopify inventory baseline is 1; "
                           "automatic scope permits [0] to 1 only"),
            }})
        summary = self.drive(adapters, AutomaticPolicy(), include=("eligibility",))
        self.assertEqual(adapters.calls["generate"], 1)
        self.assertEqual(summary["quarantined"], 1)
        self.assertEqual(summary["published"], 1)
        self.assertEqual(adapters.calls["resolve"], 0)  # pre-resolved; no second read
        state = json.loads((self.batch_dir / "state" / "process.json").read_text())
        entries = {e["tank_id"]: e for e in state["fish"].values()}
        self.assertEqual(entries["3BT21"]["status"], bp.FISH_QUARANTINED)
        self.assertIn("pre-generation ineligible", " ".join(entries["3BT21"]["notes"]))
        self.assertIn("inventory baseline is 1", " ".join(entries["3BT21"]["notes"]))

    def test_automatic_runs_without_eligibility_adapter_are_unchanged(self):
        adapters = AutomaticAdapters(tanks=["2BT12"])
        summary = self.drive(adapters, AutomaticPolicy())
        self.assertEqual(summary["status"], "COMPLETE")
        self.assertEqual(adapters.calls["generate"], 1)
        self.assertEqual(adapters.calls["resolve"], 1)

    def test_supervised_runs_do_not_apply_the_automatic_eligibility_gate(self):
        adapters = AutomaticAdapters(
            tanks=["2BT12"],
            eligibility={"2BT12": {"eligible": False, "reason": "would quarantine"}})
        summary = self.drive(adapters, policy(), include=("eligibility",))
        self.assertEqual(summary["status"], "COMPLETE")
        self.assertEqual(adapters.calls["generate"], 1)

    def test_shopify_uncertainty_uses_only_read_only_reconciliation(self):
        adapters = FakeAdapters(tanks=["2BT12"])

        def uncertain(entry, state, batch_dir):
            adapters.calls["execute"] += 1
            return {"status": "PENDING_RECONCILIATION", "reason": "write result unknown"}

        adapters.execute = uncertain
        first = self.drive(adapters, policy())
        self.assertEqual(first["status"], "RECONCILIATION_PENDING")
        self.assertEqual(adapters.calls["execute"], 1)
        second = self.drive(adapters, policy())
        self.assertEqual(second["status"], "COMPLETE")
        self.assertEqual(adapters.calls["execute"], 1)
        self.assertEqual(adapters.calls["reconcile"], 1)


class PolicyTests(unittest.TestCase):
    def test_absent_policy_is_disabled(self):
        pol = policy_mod.StandingPolicy.load(Path(self._missing()))
        self.assertFalse(pol.enabled())
        self.assertFalse(pol.paid_generation_authorised())
        self.assertIsNone(pol.authorise("x"))

    def test_grant_binds_manifest_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "automation-policy.json"
            pol = policy_mod.StandingPolicy.load(path)
            pol.data["enabled"] = True
            policy_mod._atomic_write(path, pol.data)
            policy_mod.grant(path, MANIFEST_HASH, "owner-approval")
            loaded = policy_mod.StandingPolicy.load(path)
            self.assertIsNotNone(loaded.authorise(MANIFEST_HASH))
            self.assertIsNone(loaded.authorise("other"))

    def _missing(self):
        self.tmp = tempfile.TemporaryDirectory()
        return Path(self.tmp.name) / "nope.json"


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.now = 1_000_000.0

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, name, data=b"img", mtime=None, size=None):
        path = self.dir / name
        path.write_bytes(data)
        if mtime is not None:
            import os
            os.utime(path, (mtime, mtime))
        return path

    def test_settle_excludes_recent_transfers(self):
        self.add("new.png", mtime=self.now - 5)  # still settling
        self.assertEqual(watch.scan(self.dir, now=self.now, settle_seconds=60), [])

    def test_detects_stable_new_image(self):
        self.add("dji_export_photo_1.png", mtime=self.now - 3600)
        found = watch.scan(self.dir, now=self.now, settle_seconds=60)
        self.assertEqual([Path(f["path"]).name for f in found], ["dji_export_photo_1.png"])

    def test_excludes_generated_transient_and_non_image(self):
        self.add("2BT12.png", mtime=self.now - 3600)          # generated hero name pattern (labelled/clean excluded; plain is fine)
        self.add("2BT12-clean.png", mtime=self.now - 3600)     # generated
        self.add("2BT12-labelled.png", mtime=self.now - 3600)  # generated
        self.add(".DS_Store", mtime=self.now - 3600)
        self.add("notes.txt", mtime=self.now - 3600)
        self.add("upload.png.part", mtime=self.now - 3600)
        found = {Path(f["path"]).name for f in watch.scan(self.dir, now=self.now, settle_seconds=60)}
        self.assertNotIn("2BT12-clean.png", found)
        self.assertNotIn("2BT12-labelled.png", found)
        self.assertNotIn("notes.txt", found)
        self.assertNotIn("upload.png.part", found)

    def test_known_hash_excluded_prevents_duplicate_batches(self):
        path = self.add("dji_export_photo_2.png", mtime=self.now - 3600)
        digest = watch.sha256_file(path)
        self.assertEqual(watch.scan(self.dir, now=self.now, settle_seconds=60, known_hashes={digest}), [])

    def test_registry_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = watch.ProcessedRegistry(Path(tmp) / "processed.sqlite3")
            reg.record("abc", "batch-1")
            self.assertIn("abc", watch.ProcessedRegistry(Path(tmp) / "processed.sqlite3").hashes())


if __name__ == "__main__":
    unittest.main()
