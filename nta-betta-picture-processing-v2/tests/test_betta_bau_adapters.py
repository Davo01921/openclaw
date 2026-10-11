"""Offline tests for strict dispatcher-selected production adapters."""

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parents[1] / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ad = _load("betta_adapters_strict_t", "betta_adapters.py")
bud = _load("betta_budget_strict_t", "betta_budget.py")
bsb = _load("betta_shopify_batch_strict_t", "betta_shopify_batch.py")
import betta_bau_adapters as strict_mod


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


class StrictAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.intake = self.root / "intake"
        self.intake.mkdir()
        self.source = self.intake / "fish.png"
        self.source.write_bytes(b"original-fish")
        os.utime(self.source, (1, 1))
        self.batch = self.root / "batches" / "betta-test-bau"
        for name in ("intake", "evidence", "manifest", "state", "reports", "receipts", "archive"):
            (self.batch / name).mkdir(parents=True)
        self.telemetry = self.root / "telemetry.sqlite3"
        self.selected = [{"path": str(self.source), "sha256": sha(self.source),
                          "size": self.source.stat().st_size}]
        self.budget = bud.GenerationBudget(
            self.batch / "state" / "gen-budget.json", batch_id="betta-test-bau")
        self.calls = {"generate": 0}
        self.runners = {
            "catalogue": self.catalogue,
            "generate": self.generate,
            "render": lambda clean, final, tank, date: Path(final).write_bytes(
                Path(clean).read_bytes() + b"|label|" + tank.encode()),
            "qa": self.qa,
            "resolve": lambda entry: {"status": "RESOLVED", "product": self.product()},
            "execute": lambda entry, path, digest: {"status": "VERIFIED", "receipt": {}},
            "archive": lambda state, batch_dir: {"status": "ARCHIVED"},
        }

    def tearDown(self):
        self.temp.cleanup()

    def catalogue(self, files):
        return {
            "provider": "mock-router", "model": "mock-vision", "call_id": "cat-1",
            "timestamp": now(), "input_hashes": [sha(files[0])],
            "output": {
                "tank_id": "2 BT 12", "photo_date": "2026-10-09",
                "fish_name": "Blue Red Marble", "tail_type": "Halfmoon", "sex": "Male",
                "one_fish_visible": True, "uncertainty_reasons": [],
                "confidence": {name: 0.99 for name in strict_mod.CATALOGUE_FIELDS},
            },
        }

    def generate(self, argv):
        self.calls["generate"] += 1
        source = Path(argv[argv.index("--source") + 1]).resolve()
        output = Path(argv[argv.index("--output") + 1]).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"clean-hero")
        return json.dumps({
            "provider": "xai", "model": strict_mod.GROK_MODEL, "timestamp": now(),
            "source_path": str(source), "source_sha256": sha(source),
            "output_path": str(output), "output_sha256": sha(output),
            "grokai_cost": 0.07, "grokai_cost_source": "nta_default_0.07",
            "tokens_input": 0, "tokens_output": 0,
        })

    def qa(self, entry):
        return {
            "provider": "mock-router", "model": "mock-vision", "call_id": "qa-1",
            "timestamp": now(),
            "input_hashes": [entry["source_sha256"], entry["hero_sha256"],
                             entry["source_sha256"]],
            "output": {"assertions": {name: "PASS" for name in strict_mod.QA_ASSERTIONS},
                       "overall": "PASS", "reasons": []},
        }

    @staticmethod
    def product():
        product_id = "gid://shopify/Product/101"
        variant_id = "gid://shopify/ProductVariant/201"
        inventory_id = "gid://shopify/InventoryItem/301"
        location_id = "gid://shopify/Location/401"
        raw = {
            "id": product_id, "title": "2BT12 - Old Betta Male", "status": "ACTIVE",
            "descriptionHtml": "<p>Protected</p>",
            "media": {"pageInfo": {"hasNextPage": False}, "nodes": [{
                "id": "gid://shopify/MediaImage/501", "mediaContentType": "IMAGE",
                "image": {"url": "https://example.test/old.png"},
            }]},
            "variants": {"pageInfo": {"hasNextPage": False}, "nodes": [{
                "id": variant_id, "price": "35.00", "inventoryQuantity": 0,
                "inventoryPolicy": "DENY", "inventoryItem": {
                    "id": inventory_id, "tracked": True,
                    "unitCost": {"amount": "7.15", "currencyCode": "AUD"},
                    "inventoryLevels": {"pageInfo": {"hasNextPage": False}, "nodes": [{
                        "location": {"id": location_id, "name": "NTA"},
                        "quantities": [{"name": "available", "quantity": 0},
                                       {"name": "on_hand", "quantity": 0},
                                       {"name": "committed", "quantity": 0}],
                    }]},
                },
            }]},
        }
        return {
            "id": product_id, "variant_id": variant_id, "inventory_item_id": inventory_id,
            "location_id": location_id, "raw_snapshot": raw,
            "before": {
                "title": raw["title"], "description": raw["descriptionHtml"],
                "price": "35.00", "cost": "7.15", "vendor": "NTA Imports",
                "product_type": "Domesticated Betta", "handle": "2bt12",
                "status": "ACTIVE", "inventory": 0, "inventory_policy": "DENY",
                "tracked": True, "arrival_date": "2026-08-01",
            },
        }

    def make(self, **overrides):
        args = {
            "batch_id": "betta-test-bau", "batch_dir": self.batch,
            "intake_dir": self.intake, "telemetry_db": self.telemetry,
            "policy": None, "live_shopify": True, "live_generation": True,
            "runners": self.runners, "budget": self.budget,
            "selected_sources": self.selected,
        }
        args.update(overrides)
        adapters = ad.make_adapters(**args)
        return adapters, adapters["intake"].__self__

    def prepared_entry(self):
        adapters, bundle = self.make()
        record = adapters["intake"](self.batch, {})["fish"][0]
        identity = adapters["identify"](record, self.batch)
        entry = {
            "source_path": record["path"], "source_sha256": record["sha256"],
            "date_entered": record["date_entered"], "status": "PENDING", **identity,
        }
        generated = adapters["generate"](entry, self.batch)
        entry.update(generated)
        adapters["finish"](entry, self.batch)
        result = adapters["qa"](entry, self.batch)
        self.assertEqual(result["outcome"], "PASS")
        entry["status"] = "VERIFIED"
        entry["product"] = self.product()
        return adapters, bundle, entry

    def test_selected_sources_choose_strict_adapter_and_intake_only_those_bytes(self):
        extra = self.intake / "unselected.png"
        extra.write_bytes(b"unselected")
        adapters, bundle = self.make()
        self.assertIsInstance(bundle, strict_mod.StrictBAUAdapters)
        result = adapters["intake"](self.batch, {})
        self.assertEqual(len(result["fish"]), 1)
        self.assertEqual(Path(result["fish"][0]["path"]).read_bytes(), b"original-fish")
        self.assertFalse((self.batch / "intake" / extra.name).exists())

    def test_catalogue_preserves_all_title_components_and_attestation(self):
        adapters, _ = self.make()
        record = adapters["intake"](self.batch, {})["fish"][0]
        result = adapters["identify"](record, self.batch)
        self.assertEqual(result["tank_id"], "2BT12")
        self.assertEqual(result["title"], "2BT12 - Blue Red Marble Halfmoon Male")
        receipt = Path(result["catalogue_evidence_path"])
        self.assertEqual(json.loads(receipt.read_text())["call_id"], "cat-1")

    def test_catalogue_rejects_low_confidence(self):
        original = self.runners["catalogue"]
        self.runners["catalogue"] = lambda files: {
            **original(files),
            "output": {**original(files)["output"],
                       "confidence": {name: (0.89 if name == "tank_id" else 0.99)
                                      for name in strict_mod.CATALOGUE_FIELDS}},
        }
        adapters, _ = self.make()
        record = adapters["intake"](self.batch, {})["fish"][0]
        with self.assertRaisesRegex(strict_mod.StrictAdapterError, "below 0.90"):
            adapters["identify"](record, self.batch)

    def test_generation_without_reliable_receipt_is_never_replayed(self):
        def uncertain(argv):
            self.calls["generate"] += 1
            output = Path(argv[argv.index("--output") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"possibly-billed-output")
            return "{}"

        self.runners["generate"] = uncertain
        adapters, _ = self.make()
        record = adapters["intake"](self.batch, {})["fish"][0]
        identity = adapters["identify"](record, self.batch)
        entry = {"source_path": record["path"], "source_sha256": record["sha256"], **identity}
        with self.assertRaisesRegex(strict_mod.StrictAdapterError, "will not replay"):
            adapters["generate"](entry, self.batch)
        with self.assertRaisesRegex(strict_mod.StrictAdapterError, "manual reconciliation"):
            adapters["generate"](entry, self.batch)
        self.assertEqual(self.calls["generate"], 1)

    def test_qa_requires_every_mandatory_assertion_and_never_accepts_exception(self):
        adapters, _bundle, entry = self.prepared_entry()
        self.runners["qa"] = lambda value: {
            **self.qa(value),
            "output": {"assertions": {"same_identity": "PASS"}, "overall": "PASS"},
            "accepted_exception": {"accepted_by": "owner"},
        }
        failed = adapters["qa"](entry, self.batch)
        self.assertEqual(failed["outcome"], "FAIL")
        self.assertIsNone(failed["accepted_exception"])

    def test_build_manifest_passes_real_manifest_bundle_validation(self):
        adapters, _bundle, entry = self.prepared_entry()
        built = adapters["build_manifest"]({"fish": {"source": entry}}, self.batch)
        path = Path(built["manifest_path"])
        loaded = bsb.ManifestBundle(path)
        self.assertEqual(set(loaded.contexts), {"2BT12"})
        self.assertEqual(built["manifest_sha256"], sha(path))
        self.assertTrue(loaded.raw["shopify_write_authorised"])
        self.assertIsNone(loaded.raw["items"][0]["image_qa"]["exception"])

    def test_telemetry_upserts_fish_and_exports_both_ledgers(self):
        adapters, _bundle, entry = self.prepared_entry()
        summary = adapters["telemetry"]({"fish": {"source": entry}}, self.batch)
        self.assertGreaterEqual(summary["call_rows"], 4)
        self.assertTrue(Path(summary["calls_csv"]).is_file())
        self.assertTrue(Path(summary["telemetry_csv"]).is_file())
        import sqlite3
        con = sqlite3.connect(self.telemetry)
        row = con.execute(
            "SELECT title,product_id FROM betta_processing_telemetry "
            "WHERE batch_id=? AND tank_number=?", ("betta-test-bau", "2BT12")
        ).fetchone()
        con.close()
        self.assertEqual(row, ("2BT12 - Blue Red Marble Halfmoon Male",
                               "gid://shopify/Product/101"))

    def test_budget_and_batch_limit_are_mandatory(self):
        with self.assertRaisesRegex(strict_mod.StrictAdapterError, "GenerationBudget"):
            self.make(budget=None)
        too_many = [dict(self.selected[0], sha256=f"{index:064x}") for index in range(21)]
        with self.assertRaisesRegex(strict_mod.StrictAdapterError, "production maximum"):
            self.make(selected_sources=too_many)


if __name__ == "__main__":
    unittest.main()
