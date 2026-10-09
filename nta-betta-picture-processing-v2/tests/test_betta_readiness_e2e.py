"""Offline end-to-end readiness test for Betta V2.1 with synthetic fixtures.

Exercises: fresh batch -> intake -> identification -> image-processing interface
-> QA-ready heroes -> Shopify approval manifest -> verified dry-run -> archive,
plus the safety gates (paid generation off by default, historical batches do not
block, archives immutable, dry-run moves nothing). No paid generation, no Shopify
writes, and no real photographs are touched.
"""

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parents[1] / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bl = _load("betta_batches_e2e", "betta_batches.py")
li = _load("label_identity_e2e", "label_identity.py")
fh = _load("betta_finish_heroes_e2e", "betta_finish_heroes.py")
ar = _load("betta_archive_e2e", "betta_archive.py")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ReadinessEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.batches = self.root / "batches"
        self.archive_root = self.root / "Archived Bettas"

    def tearDown(self):
        self.tmp.cleanup()

    def _make_heroes(self, batch_dir, tanks):
        def fake_generate(source, clean):
            clean.parent.mkdir(parents=True, exist_ok=True)
            clean.write_bytes(b"clean:" + source.read_bytes())

        def fake_render(clean, final, tank, photo_date):
            final.write_bytes(clean.read_bytes() + b"|" + tank.encode())

        items = []
        for idx, tank in enumerate(tanks):
            tank_id = li.normalize_tank(tank.replace("BT", " BT "))
            photo_date = li.normalize_date("9/10/2026")
            source = batch_dir / "intake" / f"{tank_id}.png"
            source.write_bytes(b"photo-" + tank_id.encode())
            items.append({"tank_id": tank_id, "source_path": str(source),
                          "source_sha256": sha256(source), "photo_date": photo_date})
        (batch_dir / "evidence" / "betta-labels-reconciled.json").write_text(
            json.dumps(items), encoding="utf-8")
        summary = fh.finish_heroes(batch_dir, authorise_paid_generation=True,
                                   generate=fake_generate, render=fake_render)
        return items, summary

    def _archive_inputs(self, batch_dir, items):
        manifest_items = []
        report_items = []
        for seq, item in enumerate(items, start=1):
            hero = batch_dir / "evidence" / "heroes" / f"{item['tank_id']}.png"
            manifest_items.append({
                "tank_id": item["tank_id"],
                "original": {"path": item["source_path"], "sha256": sha256(Path(item["source_path"]))},
                "hero": {"path": str(hero), "sha256": sha256(hero)},
                "image_qa": {"path": str(batch_dir / "evidence" / f"{item['tank_id']}-qa.json"), "exception": None},
            })
            (batch_dir / "evidence" / f"{item['tank_id']}-qa.json").write_text("{}", encoding="utf-8")
            report_items.append({"tank_id": item["tank_id"], "status": ar.READBACK_PASS, "assertions": {}})
        manifest = self.root / "approved-manifest.json"
        manifest.write_text(json.dumps({"batch_id": "betta-20261010-120000-abc123",
                                        "items": manifest_items}), encoding="utf-8")
        report = self.root / "verify.json"
        report.write_text(json.dumps({"items": report_items}), encoding="utf-8")
        return manifest, report

    def test_full_offline_chain_and_gates(self):
        # Fresh isolated batch (new intake never reuses a prior batch).
        entry = bl.create_batch(self.batches, label="fresh-intake")
        batch_dir = Path(entry["path"])
        self.assertTrue(bl.NEW_BATCH_RE.fullmatch(entry["batch_id"]))

        items, summary = self._make_heroes(batch_dir, ["2BT12", "3BT21"])
        self.assertEqual(summary["completed"], 2)

        manifest, report = self._archive_inputs(batch_dir, items)
        plan = ar.build_plan(manifest_path=manifest, report_paths=[report], inventory_csv=None,
                             archive_root=self.archive_root, date="2026-10-10")
        self.assertFalse(plan["blocked"])
        self.assertEqual(plan["counts"]["verified"], 2)

        # Dry-run moves nothing.
        dry = ar.execute_plan(plan, apply=False)
        self.assertTrue(all(r["status"] == "PLANNED" for r in dry["results"]))
        self.assertFalse((self.archive_root / "2026-10-10").exists())

        # Approved execute archives and verifies.
        done = ar.execute_plan(plan, apply=True)
        self.assertEqual(done["batch_status"], "COMPLETE")
        for item in items:
            self.assertTrue(Path(item["source_path"]).exists() is False)  # source moved

        # Immutable / idempotent resume.
        again = ar.execute_plan(ar.build_plan(manifest_path=manifest, report_paths=[report],
                                              inventory_csv=None, archive_root=self.archive_root,
                                              date="2026-10-10"), apply=True)
        self.assertEqual(again["batch_status"], "COMPLETE")

    def test_paid_generation_is_off_by_default(self):
        entry = bl.create_batch(self.batches, label="no-paid")
        batch_dir = Path(entry["path"])
        source = batch_dir / "intake" / "9BT99.png"
        source.write_bytes(b"photo")
        item = {"tank_id": "9BT99", "source_path": str(source),
                "source_sha256": sha256(source), "photo_date": "2026-10-09"}
        result = fh.process_item(item, batch_dir / "evidence" / "heroes",
                                 authorise_paid_generation=False)
        self.assertEqual(result["status"], "PAID_GENERATION_NOT_AUTHORISED")

    def test_historical_batch_does_not_block_new_batch(self):
        hist = self.root / "hist.json"
        hist.write_text(json.dumps({"batch_id": "betta-20261010-000000-hist01"}), encoding="utf-8")
        bl.register_historical(self.batches, hist)
        fresh = bl.create_batch(self.batches, label="next")
        active_ids = [e["batch_id"] for e in bl.active_batches(self.batches)]
        self.assertEqual(active_ids, [fresh["batch_id"]])
        self.assertNotIn("betta-20261010-000000-hist01", active_ids)

    def test_archive_blocks_unverified_fish(self):
        entry = bl.create_batch(self.batches, label="blocked")
        batch_dir = Path(entry["path"])
        items, _ = self._make_heroes(batch_dir, ["2BT12"])
        manifest, report = self._archive_inputs(batch_dir, items)
        report.write_text(json.dumps({"items": [
            {"tank_id": "2BT12", "status": "FINAL_SHOPIFY_READBACK_FAIL", "assertions": {}}]}),
            encoding="utf-8")
        plan = ar.build_plan(manifest_path=manifest, report_paths=[report], inventory_csv=None,
                             archive_root=self.archive_root, date="2026-10-10")
        self.assertTrue(plan["blocked"])


if __name__ == "__main__":
    unittest.main()
