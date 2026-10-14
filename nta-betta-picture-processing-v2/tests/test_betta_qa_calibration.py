"""Regression tests against genuine QA evidence (accepted and rejected cases).

The fixtures in ``tests/fixtures/qa_calibration`` are trimmed verbatim records
from real batches.  These tests pin two contracts:

* historical owner-accepted exceptions never auto-pass the deterministic
  pipeline (an explicit owner receipt is still required on supervised runs);
* the failure taxonomy reports the documented categories for genuine evidence.
"""

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parents[1] / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ad = _load("betta_adapters_cal_t", "betta_adapters.py")
bud = _load("betta_budget_cal_t", "betta_budget.py")
import betta_bau_adapters as strict_mod

FIXTURES = Path(__file__).parents[1] / "tests" / "fixtures" / "qa_calibration"


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def routing(provider="mock-router", model="mock-vision"):
    route = f"{provider}/{model}"
    return {
        "class": "STANDARD", "authority": "adaptive-model-router/v2.1",
        "requested_route": route, "eligible_routes": [route],
        "actual_provider": provider, "actual_model": model,
        "fallback_used": False, "execution_attested": True,
    }


class QACalibrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.batch = self.root / "batches" / "betta-cal"
        for name in ("evidence", "state", "manifest", "reports"):
            (self.batch / name).mkdir(parents=True)
        self.telemetry = self.root / "telemetry.sqlite3"
        self.budget = bud.GenerationBudget(
            self.batch / "state" / "gen-budget.json", batch_id="betta-cal")
        self.source = self.root / "source.png"
        self.hero = self.root / "hero.png"
        Image.new("RGB", (64, 64), (20, 20, 24)).save(self.source)
        Image.new("RGB", (128, 128), (10, 10, 12)).save(self.hero)
        sources = self.batch / "state" / "sources.json"
        sources.write_text(json.dumps({
            "schema": "nta-betta-bau-sources-v1", "dispatcher_owned": True,
            "batch_id": "betta-cal", "selected_at": now(),
            "selected_sources": [{"path": str(self.source), "sha256": sha(self.source),
                                  "size": self.source.stat().st_size}],
        }), encoding="utf-8")
        os.chmod(sources, 0o444)

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, name):
        return json.loads((FIXTURES / name).read_text())

    def run_qa(self, fixture):
        entry = {
            "tank_id": fixture["tank_id"], "photo_date": fixture["date"],
            "source_path": str(self.source), "source_sha256": sha(self.source),
            "hero_path": str(self.hero), "hero_sha256": sha(self.hero),
        }

        def qa_runner(_entry):
            return {
                "provider": "mock-router", "model": "mock-vision",
                "call_id": "qa-fixture", "timestamp": now(),
                "input_hashes": [sha(self.source), sha(self.hero), sha(self.source)],
                "routing": routing(), "usage": {},
                "output": {"assertions": fixture["assertions"],
                           "overall": fixture["overall"],
                           "reasons": fixture["reasons"]},
            }

        adapters = ad.make_adapters(
            batch_id="betta-cal", batch_dir=self.batch, intake_dir=self.root,
            telemetry_db=self.telemetry, policy=None, live_shopify=False,
            live_generation=False, runners={"qa": qa_runner}, budget=self.budget,
            selected_sources=[{"path": str(self.source), "sha256": sha(self.source),
                               "size": self.source.stat().st_size}])
        return adapters["qa"](entry, self.batch)

    def test_fixture_index_is_intact_and_documented(self):
        index = self.fixture("index.json")
        self.assertEqual(index["schema"], "nta-betta-qa-calibration-index-v1")
        self.assertGreaterEqual(len(index["cases"]), 6)
        for case in index["cases"]:
            record = self.fixture(case["file"])
            self.assertEqual(record["tank_id"], case["tank_id"])
            self.assertEqual(record["overall"], case["overall"])
            self.assertIn(record["calibrated_expectation"], {"PASS", "REJECT"})
            if record["overall"] == "FAIL":
                self.assertTrue(record["reasons"], "genuine reasons must be preserved")
            self.assertTrue(record["owner_decision"])

    def test_historical_exceptions_never_auto_pass(self):
        index = self.fixture("index.json")
        for case in index["cases"]:
            record = self.fixture(case["file"])
            with self.subTest(tank=record["tank_id"]):
                outcome = self.run_qa(record)
                if record["overall"] == "PASS":
                    self.assertEqual(outcome["outcome"], "PASS")
                else:
                    self.assertEqual(outcome["outcome"], "FAIL")
                    self.assertTrue(outcome["failed_assertions"])

    def test_failure_taxonomy_matches_genuine_evidence(self):
        outcome = self.run_qa(self.fixture("rejected_4BT14.json"))
        categories = outcome["categories"]
        self.assertIn("regional_colour", categories["identity"])
        self.assertIn("same_identity", categories["identity"])
        self.assertIn("tail_fins_pose", categories["anatomy"])

        outcome = self.run_qa(self.fixture("rejected_4BT15.json"))
        categories = outcome["categories"]
        self.assertIn("label", categories["identity"])
        self.assertIn("same_identity", categories["identity"])
        self.assertIn("body_anatomy", categories["anatomy"])

        outcome = self.run_qa(self.fixture("accepted_2BT14.json"))
        self.assertEqual(outcome["outcome"], "FAIL")  # strict pipeline until re-judged live
        self.assertIn("same_identity", outcome["categories"]["identity"])


if __name__ == "__main__":
    unittest.main()
