"""Offline tests for strict dispatcher-selected production adapters."""

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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


def routing(provider="mock-router", model="mock-vision"):
    route = f"{provider}/{model}"
    return {
        "class": "STANDARD", "authority": "adaptive-model-router/v2.1",
        "requested_route": route, "eligible_routes": [route],
        "actual_provider": provider, "actual_model": model,
        "fallback_used": False, "execution_attested": True,
    }


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
        sources = self.batch / "state" / "sources.json"
        sources.write_text(json.dumps({
            "schema": "nta-betta-bau-sources-v1", "dispatcher_owned": True,
            "batch_id": "betta-test-bau", "selected_at": now(),
            "selected_sources": self.selected,
        }), encoding="utf-8")
        os.chmod(sources, 0o444)
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
            "routing": routing(), "usage": {"tokens_input": 11, "tokens_output": 7},
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
            "routing": routing(), "usage": {"tokens_input": 13, "tokens_output": 5},
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

    def test_catalogue_low_confidence_is_a_truthful_uncertain_decision(self):
        original = self.runners["catalogue"]
        self.runners["catalogue"] = lambda files: {
            **original(files),
            "output": {**original(files)["output"],
                       "confidence": {name: (0.89 if name == "tank_id" else 0.99)
                                      for name in strict_mod.CATALOGUE_FIELDS}},
        }
        adapters, _ = self.make()
        record = adapters["intake"](self.batch, {})["fish"][0]
        result = adapters["identify"](record, self.batch)
        self.assertTrue(result["uncertain"])
        self.assertEqual(result["uncertain_reason"], "catalogue confidence below 0.90")
        receipt = json.loads(Path(result["catalogue_evidence_path"]).read_text())
        self.assertTrue(receipt["uncertain"])
        self.assertEqual(receipt["uncertain_reason"], "catalogue confidence below 0.90")

    def test_retry_identify_accepts_only_a_confident_bound_label_read(self):
        self.runners["label"] = lambda files: {
            "provider": "mock-router", "model": "mock-vision", "call_id": "label-1",
            "timestamp": now(), "input_hashes": [sha(files[0])],
            "routing": routing(), "usage": {"tokens_input": 5, "tokens_output": 3},
            "output": {"tank_id": "2 BT 12", "tank_confidence": 0.97,
                       "photo_date": "14/10/2026", "date_confidence": 0.95, "reasons": []},
        }
        adapters, _ = self.make()
        record = adapters["intake"](self.batch, {})["fish"][0]
        crop = (self.batch / "evidence" / "label-crops" /
                f"{record['sha256']}-label.png")
        crop.parent.mkdir(parents=True, exist_ok=True)
        crop.write_bytes(b"label-crop-fixture")
        decision = adapters["identify"](record, self.batch)
        entry = {"source_path": record["path"], "source_sha256": record["sha256"],
                 **decision}
        retried = adapters["retry_identify"](entry, self.batch)
        self.assertFalse(retried["uncertain"])
        self.assertEqual(retried["tank_id"], "2BT12")
        self.assertEqual(retried["photo_date"], "2026-10-14")
        self.assertEqual(retried["proposed_title"], "2BT12 - Blue Red Marble Halfmoon Male")
        receipt = json.loads(Path(retried["catalogue_evidence_path"]).read_text())
        self.assertFalse(receipt["uncertain"])
        self.assertEqual(receipt["input_hashes"], [sha(crop)])

    def test_retry_identify_stays_uncertain_on_low_confidence_label_read(self):
        self.runners["label"] = lambda files: {
            "provider": "mock-router", "model": "mock-vision", "call_id": "label-low",
            "timestamp": now(), "input_hashes": [sha(files[0])],
            "routing": routing(), "usage": {},
            "output": {"tank_id": "2 BT 12", "tank_confidence": 0.80,
                       "photo_date": "14/10/2026", "date_confidence": 0.95, "reasons": []},
        }
        adapters, _ = self.make()
        record = adapters["intake"](self.batch, {})["fish"][0]
        crop = (self.batch / "evidence" / "label-crops" /
                f"{record['sha256']}-label.png")
        crop.parent.mkdir(parents=True, exist_ok=True)
        crop.write_bytes(b"label-crop-fixture")
        decision = adapters["identify"](record, self.batch)
        entry = {"source_path": record["path"], "source_sha256": record["sha256"],
                 **decision}
        retried = adapters["retry_identify"](entry, self.batch)
        self.assertTrue(retried["uncertain"])
        self.assertIsNone(retried["proposed_title"])
        receipt = json.loads(Path(retried["catalogue_evidence_path"]).read_text())
        self.assertTrue(receipt["uncertain"])

    def test_retry_identify_never_calls_for_unsuitable_fish_components(self):
        calls = {"label": 0}
        self.runners["label"] = lambda files: (
            calls.__setitem__("label", calls["label"] + 1) or None)
        adapters, _ = self.make()
        record = adapters["intake"](self.batch, {})["fish"][0]
        unsuitable = {"source_path": record["path"], "source_sha256": record["sha256"],
                      "fish_name": "", "tail_type": "Halfmoon", "sex": "Male",
                      "notes": ["identification uncertain"]}
        retried = adapters["retry_identify"](unsuitable, self.batch)
        self.assertTrue(retried["uncertain"])
        self.assertEqual(calls["label"], 0)

    def test_catalogue_rejects_unattested_unknown_or_predating_evidence(self):
        original = self.runners["catalogue"]
        cases = [
            {"routing": {"execution_attested": False, "override": True}},
            {"provider": "unknown", "routing": routing("unknown", "mock-vision")},
            {"timestamp": "1970-01-01T00:00:00+00:00"},
            {"timestamp": "2026-10-11T00:00:00"},
            {"timestamp": "2099-01-01T00:00:00+00:00"},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                self.runners["catalogue"] = lambda files, changes=changes: {
                    **original(files), **changes,
                }
                adapters, _ = self.make()
                record = adapters["intake"](self.batch, {})["fish"][0]
                with self.assertRaises(strict_mod.StrictAdapterError):
                    adapters["identify"](record, self.batch)

    def test_catalogue_and_qa_reuse_bound_receipts_without_new_calls(self):
        counts = {"catalogue": 0, "qa": 0}
        original_catalogue, original_qa = self.catalogue, self.qa
        self.runners["catalogue"] = lambda files: (
            counts.__setitem__("catalogue", counts["catalogue"] + 1) or original_catalogue(files)
        )
        self.runners["qa"] = lambda entry: (
            counts.__setitem__("qa", counts["qa"] + 1) or original_qa(entry)
        )
        adapters, _bundle, entry = self.prepared_entry()
        record = {"path": entry["source_path"], "sha256": entry["source_sha256"]}
        adapters["identify"](record, self.batch)
        adapters["qa"](entry, self.batch)
        self.assertEqual(counts, {"catalogue": 1, "qa": 1})

        receipt = Path(entry["image_qa_path"])
        os.chmod(receipt, 0o644)
        changed = json.loads(receipt.read_text())
        changed["batch_id"] = "different-batch"
        receipt.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(strict_mod.StrictAdapterError, "batch/source identity"):
            adapters["qa"](entry, self.batch)

    def test_failed_vision_attempt_usage_is_recorded_as_retry(self):
        original = self.runners["catalogue"]
        self.runners["catalogue"] = lambda files: {
            **original(files),
            "attempts": [{
                "provider": "qwen", "model": "failed-vision",
                "error": "temporary provider failure",
                "usage": {"tokens_input": 3, "tokens_output": 2},
            }],
        }
        adapters, _bundle, entry = self.prepared_entry()
        adapters["telemetry"]({"fish": {"source": entry}}, self.batch)
        import sqlite3
        con = sqlite3.connect(self.telemetry)
        try:
            error_row = con.execute(
                "SELECT outcome,tokens_input,tokens_output FROM betta_call_telemetry "
                "WHERE batch_id=? AND tank_number=? AND stage='identify' AND outcome='ERROR'",
                ("betta-test-bau", "2BT12"),
            ).fetchone()
            retry_count = con.execute(
                "SELECT retry_count FROM betta_processing_telemetry "
                "WHERE batch_id=? AND tank_number=?",
                ("betta-test-bau", "2BT12"),
            ).fetchone()[0]
        finally:
            con.close()
        self.assertEqual(error_row, ("ERROR", 3, 2))
        self.assertEqual(retry_count, 1)

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
        with self.assertRaisesRegex(strict_mod.base.ReconciliationPending, "will not replay"):
            adapters["generate"](entry, self.batch)
        self.assertEqual(self.budget.summary()["batch_reserved"], 0.07)
        with self.assertRaisesRegex(strict_mod.base.ReconciliationPending, "manual reconciliation"):
            adapters["generate"](entry, self.batch)
        self.assertEqual(self.calls["generate"], 1)
        clean = self.batch / "evidence" / "heroes" / "2BT12-clean.png"
        receipt = {
            "provider": "xai", "model": strict_mod.GROK_MODEL, "timestamp": now(),
            "source_path": str(Path(entry["source_path"]).resolve()),
            "source_sha256": entry["source_sha256"],
            "output_path": str(clean.resolve()), "output_sha256": sha(clean),
            "grokai_cost": 0.07, "grokai_cost_source": "nta_default_0.07",
        }
        receipt_path = self.batch / "evidence" / "generation" / "2BT12.json"
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        recovered = adapters["generate"](entry, self.batch)
        self.assertEqual(recovered["hero_sha256"], sha(clean))
        self.assertEqual(self.calls["generate"], 1)
        self.assertEqual(self.budget.summary()["batch_reserved"], 0.0)

    def test_shopify_reconciliation_uses_read_only_runner(self):
        adapters, _bundle, entry = self.prepared_entry()
        built = adapters["build_manifest"]({"fish": {"source": entry}}, self.batch)
        calls = []
        self.runners["reconcile"] = lambda item, path, digest: (
            calls.append((item["tank_id"], str(path), digest)) or
            {"status": "READ_ONLY_VERIFIED", "receipt": {"verified": True}}
        )
        state = {"manifest_path": built["manifest_path"],
                 "manifest_sha256": built["manifest_sha256"]}
        result = adapters["reconcile"](entry, state, self.batch)
        self.assertEqual(result["status"], "READ_ONLY_VERIFIED")
        self.assertEqual(len(calls), 1)

    def test_qa_requires_every_mandatory_assertion_and_never_accepts_exception(self):
        adapters, _bundle, entry = self.prepared_entry()
        receipt = Path(entry["image_qa_path"])
        os.chmod(receipt, 0o644)
        receipt.unlink()
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
        entry["shopify_receipt"] = {"verified_at": now()}
        completed_at = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
        summary = adapters["telemetry"]({
            "fish": {"source": entry},
            "archive_receipt": {"completed_at": completed_at},
        }, self.batch)
        self.assertGreaterEqual(summary["call_rows"], 4)
        self.assertTrue(Path(summary["calls_csv"]).is_file())
        self.assertTrue(Path(summary["telemetry_csv"]).is_file())
        import sqlite3
        con = sqlite3.connect(self.telemetry)
        row = con.execute(
            "SELECT title,product_id,onboarding_seconds,archive_completed_at,end_to_archive_seconds "
            "FROM betta_processing_telemetry "
            "WHERE batch_id=? AND tank_number=?", ("betta-test-bau", "2BT12")
        ).fetchone()
        con.close()
        self.assertEqual(row[:2], ("2BT12 - Blue Red Marble Halfmoon Male",
                                   "gid://shopify/Product/101"))
        self.assertIsNotNone(row[2])
        self.assertIsNotNone(row[3])
        self.assertIsNotNone(row[4])
        with Path(summary["telemetry_csv"]).open() as handle:
            rows = list(__import__("csv").DictReader(handle))
        self.assertEqual({record["batch_id"] for record in rows}, {"betta-test-bau"})

    def test_reconcile_is_hash_bound_and_calls_only_readonly_runner(self):
        adapters, _bundle, entry = self.prepared_entry()
        built = adapters["build_manifest"]({"fish": {"source": entry}}, self.batch)
        observed = []
        self.runners["reconcile"] = lambda fish, path, digest: (
            observed.append((fish["tank_id"], str(path), digest)) or {"status": "VERIFIED"}
        )
        state = {"manifest_path": built["manifest_path"],
                 "manifest_sha256": built["manifest_sha256"]}
        self.assertEqual(adapters["reconcile"](entry, state, self.batch)["status"], "VERIFIED")
        self.assertEqual(len(observed), 1)

    def test_budget_and_batch_limit_are_mandatory(self):
        with self.assertRaisesRegex(strict_mod.StrictAdapterError, "GenerationBudget"):
            self.make(budget=None)
        too_many = [dict(self.selected[0], sha256=f"{index:064x}") for index in range(21)]
        with self.assertRaisesRegex(strict_mod.StrictAdapterError, "production maximum"):
            self.make(selected_sources=too_many)

    def test_eligibility_enforces_the_zero_deny_tracked_baseline(self):
        adapters, _ = self.make()
        verdict = adapters["eligibility"]({"tank_id": "2BT12"}, {}, self.batch)
        self.assertTrue(verdict["eligible"])
        self.assertEqual(verdict["product"]["before"]["inventory"], 0)

        product = self.product()
        cases = [
            ({**product["before"], "inventory": 1}, "inventory baseline is 1"),
            ({**product["before"], "inventory_policy": "CONTINUE"}, "policy is not DENY"),
            ({**product["before"], "tracked": False}, "not tracked"),
        ]
        for before, reason in cases:
            with self.subTest(reason=reason):
                self.runners["resolve"] = lambda entry, before=before: {
                    "status": "RESOLVED",
                    "product": {**self.product(), "before": before},
                }
                adapters, _ = self.make()
                verdict = adapters["eligibility"]({"tank_id": "2BT12"}, {}, self.batch)
                self.assertFalse(verdict["eligible"])
                self.assertIn(reason, verdict["reason"])

    def test_eligibility_retries_transient_errors_but_never_weakens_the_gate(self):
        attempts = {"count": 0}

        def flaky(entry):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise RuntimeError("transient bridge error")
            return {"status": "RESOLVED", "product": self.product()}

        self.runners["resolve"] = flaky
        self.runners["eligibility_retry_delay_seconds"] = 0
        adapters, _ = self.make()
        verdict = adapters["eligibility"]({"tank_id": "2BT12"}, {}, self.batch)
        self.assertTrue(verdict["eligible"])
        self.assertEqual(attempts["count"], 3)

        self.runners["resolve"] = lambda entry: {"status": "AMBIGUOUS"}
        adapters, _ = self.make()
        verdict = adapters["eligibility"]({"tank_id": "2BT12"}, {}, self.batch)
        self.assertFalse(verdict["eligible"])
        self.assertIn("not unique", verdict["reason"])

    def test_eligibility_uses_the_standing_policy_inventory_rule(self):
        class Policy:
            def inventory_rule(self):
                return {"allowed_from": [0], "require_deny": False,
                        "require_tracked": False}

        self.runners["resolve"] = lambda entry: {
            "status": "RESOLVED",
            "product": {**self.product(),
                        "before": {**self.product()["before"],
                                   "inventory_policy": "CONTINUE", "tracked": False}},
        }
        adapters, _ = self.make(policy=Policy())
        verdict = adapters["eligibility"]({"tank_id": "2BT12"}, {}, self.batch)
        self.assertTrue(verdict["eligible"])


if __name__ == "__main__":
    unittest.main()
