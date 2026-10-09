"""Offline tests for the batch-independent hero pipeline (no paid generation)."""

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "betta_finish_heroes.py"
spec = importlib.util.spec_from_file_location("betta_finish_heroes", SCRIPT)
fh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fh)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class HeroPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.batch = Path(self.tmp.name) / "betta-20261010-120000-abc123"
        (self.batch / "intake").mkdir(parents=True)
        (self.batch / "evidence").mkdir(parents=True)
        (self.batch / "reports").mkdir(parents=True)
        self.calls = {"generate": [], "render": []}

        def fake_generate(source, clean):
            self.calls["generate"].append((str(source), str(clean)))
            clean.parent.mkdir(parents=True, exist_ok=True)
            clean.write_bytes(b"clean:" + source.read_bytes())

        def fake_render(clean, final, tank, photo_date):
            self.calls["render"].append((tank, photo_date))
            final.write_bytes(clean.read_bytes() + b"|" + tank.encode() + b"|" + photo_date.encode())

        self.generate = fake_generate
        self.render = fake_render

    def tearDown(self):
        self.tmp.cleanup()

    def add_item(self, tank, photo_date="2026-10-09", data=b"source-bytes"):
        source = self.batch / "intake" / f"{tank}.png"
        source.write_bytes(data + tank.encode())
        return {"tank_id": tank, "source_path": str(source),
                "source_sha256": sha(source.read_bytes()), "photo_date": photo_date}

    def write_reconciled(self, items):
        (self.batch / "evidence" / "betta-labels-reconciled.json").write_text(
            json.dumps(items), encoding="utf-8")

    def test_paths_are_batch_relative(self):
        paths = fh.resolve_paths(self.batch)
        self.assertEqual(paths["hero_dir"], self.batch / "evidence" / "heroes")
        self.assertEqual(paths["reconciled"], self.batch / "evidence" / "betta-labels-reconciled.json")
        self.assertEqual(paths["results"], self.batch / "reports" / "betta-hero-batch-results.json")

    def test_paid_generation_blocked_without_authorisation(self):
        item = self.add_item("2BT12")
        result = fh.process_item(item, self.batch / "evidence" / "heroes",
                                 authorise_paid_generation=False,
                                 generate=self.generate, render=self.render)
        self.assertEqual(result["status"], "PAID_GENERATION_NOT_AUTHORISED")
        self.assertEqual(self.calls["generate"], [])
        self.assertFalse((self.batch / "evidence" / "heroes" / "2BT12-clean.png").exists())

    def test_authorised_generation_and_render(self):
        item = self.add_item("3BT21", photo_date="2026-08-21")
        result = fh.process_item(item, self.batch / "evidence" / "heroes",
                                 authorise_paid_generation=True,
                                 generate=self.generate, render=self.render)
        self.assertEqual(result["status"], "GENERATED_QA_PENDING")
        self.assertEqual(len(self.calls["generate"]), 1)
        self.assertEqual(self.calls["render"], [("3BT21", "2026-08-21")])
        self.assertTrue((self.batch / "evidence" / "heroes" / "3BT21.png").is_file())

    def test_existing_clean_is_reused(self):
        item = self.add_item("2BT13")
        hero_dir = self.batch / "evidence" / "heroes"
        hero_dir.mkdir(parents=True, exist_ok=True)
        (hero_dir / "2BT13-clean.png").write_bytes(b"existing-clean")
        result = fh.process_item(item, hero_dir, authorise_paid_generation=False,
                                 generate=self.generate, render=self.render)
        self.assertEqual(result["status"], "READY_QA_PENDING")
        self.assertEqual(self.calls["generate"], [])

    def test_source_hash_mismatch_fails_closed(self):
        item = self.add_item("3BT22")
        item["source_sha256"] = "0" * 64
        with self.assertRaises(RuntimeError):
            fh.process_item(item, self.batch / "evidence" / "heroes",
                            authorise_paid_generation=True,
                            generate=self.generate, render=self.render)

    def test_source_bytes_preserved(self):
        item = self.add_item("3BT33", data=b"precious-original")
        before = Path(item["source_path"]).read_bytes()
        fh.process_item(item, self.batch / "evidence" / "heroes",
                        authorise_paid_generation=True,
                        generate=self.generate, render=self.render)
        self.assertEqual(Path(item["source_path"]).read_bytes(), before)

    def test_finish_heroes_is_generic_across_batch(self):
        items = [self.add_item("1BT11", "2026-01-02"), self.add_item("2BT12", "2026-02-03"),
                 self.add_item("5BT55", "2026-03-04")]
        self.write_reconciled(items)
        summary = fh.finish_heroes(self.batch, authorise_paid_generation=True,
                                   generate=self.generate, render=self.render)
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["completed"], 3)
        self.assertTrue(Path(summary["results_path"]).is_file())
        self.assertEqual(len(self.calls["generate"]), 3)
        self.assertEqual(sorted(self.calls["render"]),
                         [("1BT11", "2026-01-02"), ("2BT12", "2026-02-03"), ("5BT55", "2026-03-04")])

    def test_missing_batch_dir_errors(self):
        with self.assertRaises(ValueError):
            fh.resolve_paths(Path(self.tmp.name) / "nope")


if __name__ == "__main__":
    unittest.main()
