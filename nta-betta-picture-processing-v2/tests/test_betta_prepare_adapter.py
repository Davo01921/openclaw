"""Offline tests for the strict BAU preparation adapter ladder."""

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parents[1] / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ad = _load("betta_adapters_prep_t", "betta_adapters.py")
bud = _load("betta_budget_prep_t", "betta_budget.py")
import betta_bau_adapters as strict_mod


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


def make_frame(path: Path):
    image = Image.new("RGB", (240, 320), (14, 20, 26))
    draw = ImageDraw.Draw(image)
    draw.ellipse((60, 120, 180, 220), fill=(140, 30, 35))
    draw.rectangle((215, 58, 219, 62), fill=(210, 208, 205))
    image.save(path, format="PNG")


class PreparationAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.intake = self.root / "intake"
        self.intake.mkdir()
        self.source = self.intake / "fish.png"
        make_frame(self.source)
        os.utime(self.source, (1, 1))
        self.batch = self.root / "batches" / "betta-test-bau"
        for name in ("intake", "evidence", "manifest", "state", "reports", "receipts", "archive"):
            (self.batch / name).mkdir(parents=True)
        self.telemetry = self.root / "telemetry.sqlite3"
        self.selected = [{"path": str(self.source), "sha256": sha(self.source),
                          "size": self.source.stat().st_size}]
        sources = self.batch / "state" / "sources.json"
        sources.write_text(json.dumps({
            "schema": "nta-betta-bau-sources-v1", "dispatcher_owned": True,
            "batch_id": "betta-test-bau", "selected_at": now(),
            "selected_sources": self.selected,
        }), encoding="utf-8")
        os.chmod(sources, 0o444)
        self.budget = bud.GenerationBudget(
            self.batch / "state" / "gen-budget.json", batch_id="betta-test-bau")
        self.calls = {"preflight": 0, "prepqa": 0}
        self.preflight_output = {
            "tank_id": "2 BT 12", "photo_date": "2026-10-14",
            "tank_confidence": 0.96, "date_confidence": 0.95,
            "fish_confidence": 0.95, "one_fish_visible": True,
            "needs_retake": False,
            "tank_bounds": [0.05, 0.02, 0.98, 0.97],
            "fish_bounds": [0.25, 0.36, 0.75, 0.72],
            "debris_boxes": [],
        }
        self.prepqa_output = {
            "overall": "PASS", "same_fish": True, "full_fins": True,
            "faithful_colours": True, "tank_only": True, "lighting_usable": True,
            "no_identity_alteration": True, "reason": "",
        }
        self.runners = {
            "vision_retry_delay_seconds": 0,
            "vision_preflight": self.vision_preflight,
            "vision_prepqa": self.vision_prepqa,
        }

    def tearDown(self):
        self.temp.cleanup()

    def vision_preflight(self, files):
        self.calls["preflight"] += 1
        return {
            "provider": "mock-router", "model": "mock-vision", "call_id": "pf-1",
            "timestamp": now(), "input_hashes": [sha(files[0])],
            "routing": routing(), "usage": {},
            "output": dict(self.preflight_output),
        }

    def vision_prepqa(self, files):
        self.calls["prepqa"] += 1
        return {
            "provider": "mock-router", "model": "mock-vision", "call_id": "pq-1",
            "timestamp": now(), "input_hashes": [sha(files[0]), sha(files[1])],
            "routing": routing(), "usage": {},
            "output": dict(self.prepqa_output),
        }

    def entry(self):
        return {"tank_id": "2BT12", "photo_date": "2026-10-14",
                "source_path": str(self.source), "source_sha256": sha(self.source)}

    def adapters(self):
        return ad.make_adapters(
            batch_id=self.batch.name, batch_dir=self.batch, intake_dir=self.intake,
            telemetry_db=self.telemetry, policy=None, live_shopify=False,
            live_generation=False, runners=self.runners, budget=self.budget,
            selected_sources=self.selected)

    def test_full_preparation_is_verified_receipted_and_reused(self):
        adapters = self.adapters()
        before = sha(self.source)
        verdict = adapters["prepare"](self.entry(), self.batch)
        self.assertEqual(verdict["status"], "PREPARED")
        self.assertEqual(verdict["level"], "FULL")
        working = Path(verdict["working_path"])
        self.assertTrue(working.is_file())
        self.assertEqual(verdict["working_sha256"], sha(working))
        self.assertEqual(sha(self.source), before)  # raw untouched
        receipt = json.loads(Path(verdict["receipt_path"]).read_text())
        self.assertEqual(receipt["status"], "PREPARED")
        self.assertEqual(receipt["identity_cross_check"]["status"], "AGREES")
        self.assertEqual(receipt["accepted"]["prep_qa"]["output"]["overall"], "PASS")
        self.assertEqual(self.calls, {"preflight": 1, "prepqa": 1})

        reused = adapters["prepare"](self.entry(), self.batch)
        self.assertEqual(reused["status"], "PREPARED")
        self.assertEqual(reused["working_sha256"], verdict["working_sha256"])
        self.assertEqual(self.calls, {"preflight": 1, "prepqa": 1})  # no new calls

    def test_rejected_full_attempt_falls_back_to_conservative_l1(self):
        calls = {"n": 0}

        def prepqa(files):
            self.calls["prepqa"] += 1
            calls["n"] += 1
            if calls["n"] == 1:
                output = {**self.prepqa_output, "overall": "FAIL", "full_fins": False,
                          "reason": "fin tips clipped"}
            else:
                output = dict(self.prepqa_output)
            return {
                "provider": "mock-router", "model": "mock-vision", "call_id": "pq-x",
                "timestamp": now(), "input_hashes": [sha(files[0]), sha(files[1])],
                "routing": routing(), "usage": {}, "output": output,
            }

        self.runners["vision_prepqa"] = prepqa
        adapters = self.adapters()
        verdict = adapters["prepare"](self.entry(), self.batch)
        self.assertEqual(verdict["status"], "PREPARED")
        self.assertEqual(verdict["level"], "L1")
        receipt = json.loads(Path(verdict["receipt_path"]).read_text())
        self.assertEqual(receipt["attempts"][0]["prep_qa"], "FAIL")
        self.assertIn("clipped", receipt["attempts"][0]["reason"])
        self.assertIsNone(receipt["accepted"]["operations"]["crop"])
        self.assertTrue((self.batch / "evidence" / "working" /
                         "2BT12-working-full.png").is_file())

    def test_repeated_rejection_falls_back_to_the_untouched_raw_copy(self):
        self.prepqa_output = {**self.prepqa_output, "overall": "FAIL",
                              "same_fish": False, "reason": "different fish"}
        adapters = self.adapters()
        verdict = adapters["prepare"](self.entry(), self.batch)
        self.assertEqual(verdict["status"], "FALLBACK_RAW")
        working = Path(verdict["working_path"])
        self.assertEqual(working.read_bytes(), self.source.read_bytes())
        receipt = json.loads(Path(verdict["receipt_path"]).read_text())
        self.assertEqual(len(receipt["attempts"]), 2)
        self.assertTrue(all(item.get("prep_qa") == "FAIL"
                            for item in receipt["attempts"]))
        self.assertTrue(receipt["working_identity"]["raw_copy"])

    def test_confident_label_conflict_blocks_instead_of_guessing(self):
        self.preflight_output = {**self.preflight_output, "tank_id": "9BT99",
                                 "tank_confidence": 0.97}
        adapters = self.adapters()
        verdict = adapters["prepare"](self.entry(), self.batch)
        self.assertEqual(verdict["status"], "BLOCKED")
        self.assertIn("tank read conflict", verdict["reason"])
        receipt = json.loads(Path(verdict["receipt_path"]).read_text())
        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertFalse((self.batch / "evidence" / "working" / "2BT12-working.png").exists())

    def test_date_conflict_blocks_and_unreadable_label_does_not(self):
        self.preflight_output = {**self.preflight_output, "photo_date": "2026-10-15",
                                 "date_confidence": 0.97}
        adapters = self.adapters()
        verdict = adapters["prepare"](self.entry(), self.batch)
        self.assertEqual(verdict["status"], "BLOCKED")
        self.assertIn("date read conflict", verdict["reason"])

        self.setUp_neutral_unreadable()
        adapters = self.adapters()
        verdict = adapters["prepare"](self.entry(), self.batch)
        self.assertEqual(verdict["status"], "PREPARED")
        receipt = json.loads(Path(verdict["receipt_path"]).read_text())
        self.assertEqual(receipt["identity_cross_check"]["status"], "UNAVAILABLE")

    def setUp_neutral_unreadable(self):
        # A fresh batch directory so receipts do not collide.
        self.batch = self.root / "batches" / "betta-test-bau-unreadable"
        for name in ("intake", "evidence", "manifest", "state", "reports", "receipts", "archive"):
            (self.batch / name).mkdir(parents=True)
        sources = self.batch / "state" / "sources.json"
        sources.write_text(json.dumps({
            "schema": "nta-betta-bau-sources-v1", "dispatcher_owned": True,
            "batch_id": "betta-test-bau-unreadable", "selected_at": now(),
            "selected_sources": self.selected,
        }), encoding="utf-8")
        os.chmod(sources, 0o444)
        self.budget = bud.GenerationBudget(
            self.batch / "state" / "gen-budget.json", batch_id="betta-test-bau-unreadable")
        self.preflight_output = {
            "tank_id": "", "photo_date": "", "tank_confidence": 0.0,
            "date_confidence": 0.0, "fish_confidence": 0.0, "one_fish_visible": True,
            "needs_retake": False, "tank_bounds": None, "fish_bounds": None,
            "debris_boxes": [],
        }

    def test_unusable_bounds_use_the_conservative_level(self):
        self.preflight_output = {**self.preflight_output, "tank_confidence": 0.5,
                                 "fish_confidence": 0.5}
        adapters = self.adapters()
        verdict = adapters["prepare"](self.entry(), self.batch)
        self.assertEqual(verdict["status"], "PREPARED")
        self.assertEqual(verdict["level"], "L1")
        receipt = json.loads(Path(verdict["receipt_path"]).read_text())
        self.assertIsNone(receipt["accepted"]["operations"]["crop"])

    def test_unavailable_prepared_qa_is_recorded_and_deterministic_gates_decide(self):
        def failing_prepqa(_files):
            raise RuntimeError("vision service down")

        self.runners["vision_prepqa"] = failing_prepqa
        adapters = self.adapters()
        verdict = adapters["prepare"](self.entry(), self.batch)
        self.assertEqual(verdict["status"], "PREPARED")
        receipt = json.loads(Path(verdict["receipt_path"]).read_text())
        self.assertIsNone(receipt["accepted"]["prep_qa"])
        self.assertIn("UNAVAILABLE", receipt["attempts"][0]["prep_qa"])

    def test_changed_source_raises_and_never_writes_a_receipt(self):
        entry = self.entry()
        self.source.write_bytes(self.source.read_bytes() + b"drift")
        adapters = self.adapters()
        with self.assertRaisesRegex(strict_mod.StrictAdapterError, "source changed"):
            adapters["prepare"](entry, self.batch)


if __name__ == "__main__":
    unittest.main()
