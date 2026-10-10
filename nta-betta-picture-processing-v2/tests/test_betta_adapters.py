"""Offline tests for the real batch-scoped adapters and integrated orchestrator."""

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bp = _load("betta_process_a", "betta_process.py")
ad = _load("betta_adapters_a", "betta_adapters.py")
policy_mod = _load("betta_policy_a", "betta_policy.py")
bl = _load("betta_batches_a", "betta_batches.py")
telemetry_mod = _load("betta_telemetry_a", "betta_telemetry.py")
bud = _load("betta_budget_a", "betta_budget.py")


class IntegratedAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.intake = self.root / "intake"
        self.intake.mkdir()
        self.batches = self.root / "batches"
        self.telemetry_db = self.root / "telemetry.sqlite3"
        entry = bl.create_batch(self.batches, label="integration")
        self.batch_dir = Path(entry["path"])
        self.batch_id = entry["batch_id"]
        # one incoming photograph, settled
        self.photo = self.intake / "dji_export_photo_new.png"
        self.photo.write_bytes(b"original-bytes")
        old = 1.0
        os.utime(self.photo, (old, old))

        self.calls = {"generate": 0, "execute": 0, "archive": 0}

        def fake_generate(argv):
            self.calls["generate"] += 1
            out = Path(argv[argv.index("--output") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"clean")

        runners = {
            "settle_seconds": 0,
            "catalogue": lambda files: {"provider": "mock", "model": "mock-vision",
                                        "output": {"tank_id": "2BT12", "photo_date": "2026-10-09"}},
            "generate": fake_generate,
            "render": lambda clean, final, tank, date: Path(final).write_bytes(b"final" + tank.encode()),
            "qa": lambda entry: {"provider": "mock", "model": "mock-vision", "overall": "PASS",
                                 "assertions": {"same_identity": "PASS", "label": "PASS"}},
            "resolve": lambda entry: {"status": "RESOLVED",
                                      "product": {"id": "gid://shopify/Product/1"}},
            "execute": lambda entry, manifest_path, sha: (self.calls.__setitem__("execute", self.calls["execute"] + 1)
                                                          or {"status": "VERIFIED", "receipt": "r-2BT12"}),
            "archive": lambda state, batch_dir: (self.calls.__setitem__("archive", self.calls["archive"] + 1)
                                                 or {"status": "COMPLETE"}),
        }
        self.runners = runners

    def tearDown(self):
        self.tmp.cleanup()

    def adapters(self, *, live_shopify=False, live_generation=False, exceptions=None, budget=None):
        return ad.make_adapters(
            batch_id=self.batch_id, batch_dir=self.batch_dir, intake_dir=self.intake,
            telemetry_db=self.telemetry_db, policy=None, live_shopify=live_shopify,
            live_generation=live_generation, owner_exceptions=exceptions, runners=self.runners,
            budget=budget)

    def budget(self, **limits):
        return bud.GenerationBudget(self.batch_dir / "state" / "gen-budget.json",
                                    batch_id=self.batch_id, limits=limits or None)

    def policy(self, manifest_sha=None, enabled=True, paid=True):
        data = policy_mod.default_policy()
        data["enabled"] = enabled
        data["paid_generation_authorised"] = paid
        if manifest_sha:
            data["authorisations"] = [{"manifest_sha256": manifest_sha, "receipt": "owner", "at": "t"}]
        return policy_mod.StandingPolicy(data)

    def drive(self, adapters, policy):
        return bp.process_batch(self.batch_dir, self.batch_id, adapters=adapters, policy=policy)

    def test_authorisation_gate_then_full_completion(self):
        # Phase 1: pays for generation + builds manifest, then waits for authorisation.
        first = self.drive(self.adapters(live_generation=True), self.policy())
        self.assertEqual(first["status"], "AWAITING_AUTHORISATION")
        self.assertEqual(self.calls["generate"], 1)
        self.assertEqual(self.calls["execute"], 0)
        state = json.loads((self.batch_dir / "state" / "process.json").read_text())
        manifest_sha = state["manifest_sha256"]

        # Phase 2: authorise the exact manifest and run live; completes without regenerating.
        second = self.drive(self.adapters(live_shopify=True, live_generation=True),
                          self.policy(manifest_sha=manifest_sha))
        self.assertEqual(second["status"], "COMPLETE")
        self.assertEqual(second["published"], 1)
        self.assertEqual(self.calls["generate"], 1)  # idempotent: no repeat paid generation
        self.assertEqual(self.calls["archive"], 1)

    def test_dry_run_does_not_write_and_pauses(self):
        first = self.drive(self.adapters(live_generation=True), self.policy())
        state = json.loads((self.batch_dir / "state" / "process.json").read_text())
        summary = self.drive(self.adapters(live_shopify=False, live_generation=True),
                           self.policy(manifest_sha=state["manifest_sha256"]))
        self.assertEqual(summary["status"], "AWAITING_LIVE")
        self.assertEqual(self.calls["execute"], 0)

    def test_resume_never_repeats_execute(self):
        self.drive(self.adapters(live_generation=True), self.policy())
        state = json.loads((self.batch_dir / "state" / "process.json").read_text())
        pol = self.policy(manifest_sha=state["manifest_sha256"])
        self.drive(self.adapters(live_shopify=True, live_generation=True), pol)
        self.assertEqual(self.calls["execute"], 1)
        self.drive(self.adapters(live_shopify=True, live_generation=True), pol)  # restart
        self.assertEqual(self.calls["execute"], 1)  # no duplicate Shopify write

    def test_qa_failure_quarantines(self):
        self.runners["qa"] = lambda entry: {"provider": "m", "model": "m", "overall": "FAIL",
                                            "assertions": {"same_identity": "FAIL"}}
        first = self.drive(self.adapters(live_generation=True), self.policy())
        self.assertEqual(first["quarantined"], 1)
        self.assertEqual(first["published"], 0)

    def test_owner_exception_publishes_as_exception(self):
        self.runners["qa"] = lambda entry: {"provider": "m", "model": "m", "overall": "FAIL",
                                            "assertions": {"label": "FAIL"}}
        first = self.drive(self.adapters(live_generation=True, exceptions={"2BT12": {"accepted_by": "owner"}}),
                         self.policy())
        state = json.loads((self.batch_dir / "state" / "process.json").read_text())
        entry = next(e for e in state["fish"].values() if e.get("tank_id") == "2BT12")
        self.assertEqual(entry["status"], bp.FISH_PASS_EXCEPTION)

    def test_generation_retries_once_within_budget(self):
        attempts = {"n": 0}

        def flaky(argv):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("simulated 429")
            out = Path(argv[argv.index("--output") + 1])
            out.write_bytes(b"clean")

        self.runners["generate"] = flaky
        b = self.budget()
        summary = self.drive(self.adapters(live_generation=True, budget=b), self.policy())
        self.assertEqual(attempts["n"], 2)  # one initial + one retry
        self.assertEqual(b.summary()["fish"]["2BT12"]["attempts"], 2)
        # budget still within per-fish cap (2 x 0.07 = 0.14)
        self.assertLessEqual(b.summary()["fish"]["2BT12"]["spent"], 0.14 + 1e-9)

    def test_generation_blocked_when_attempts_exhausted_quarantines(self):
        def always_fail(argv):
            raise RuntimeError("simulated provider failure")

        self.runners["generate"] = always_fail
        b = self.budget(max_attempts_per_fish=1)  # only one attempt allowed
        summary = self.drive(self.adapters(live_generation=True, budget=b), self.policy())
        self.assertEqual(summary["quarantined"], 1)
        self.assertEqual(summary["published"], 0)

    def test_telemetry_recorded_during_run_and_exported(self):
        first = self.drive(self.adapters(live_generation=True), self.policy())
        state = json.loads((self.batch_dir / "state" / "process.json").read_text())
        self.drive(self.adapters(live_shopify=True, live_generation=True),
                 self.policy(manifest_sha=state["manifest_sha256"]))
        con = telemetry_mod.connect(self.telemetry_db)
        rows = con.execute("SELECT stage, outcome FROM betta_call_telemetry WHERE batch_id=?",
                           (self.batch_id,)).fetchall()
        con.close()
        stages = {r[0] for r in rows}
        self.assertIn("intake", stages)
        self.assertIn("generate", stages)
        self.assertIn("qa", stages)
        self.assertTrue((self.batch_dir / "reports" / "betta-call-telemetry.csv").is_file())


if __name__ == "__main__":
    unittest.main()
