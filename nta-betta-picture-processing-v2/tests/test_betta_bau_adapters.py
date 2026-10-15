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


def _reference_compare_reads(full, crop):
    """Deterministic implementation of the pinned label_identity.compare_reads
    contract, installed only while A2's own helper is absent."""
    if not (full.get("confident") and crop.get("confident")):
        return {"status": "INCOMPLETE", "tank": None, "date": None,
                "reasons": ["unconfident read"]}
    if (full.get("tank_id") == crop.get("tank_id")
            and full.get("photo_date") == crop.get("photo_date")):
        return {"status": "AGREE", "tank": full.get("tank_id"),
                "date": full.get("photo_date"), "reasons": []}
    return {"status": "DISAGREE", "tank": None, "date": None,
            "reasons": ["confident readings differ"]}


class StrictAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.intake = self.root / "intake"
        self.intake.mkdir()
        self.source = self.intake / "fish.png"
        from PIL import Image
        Image.new("RGB", (48, 64), (20, 30, 40)).save(self.source, format="PNG")
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
        if not callable(getattr(strict_mod.label_mod, "compare_reads", None)):
            # A2 lands the real comparator in parallel; until then every test in
            # this module runs against the pinned-contract reference so the dual
            # read wiring is exercised deterministically.
            strict_mod.label_mod.compare_reads = _reference_compare_reads
        self.runners = {
            "catalogue": self.catalogue,
            "label": self.label,
            "generate": self.generate,
            "render": lambda clean, final, tank, date: Path(final).write_bytes(
                Path(clean).read_bytes() + b"|label|" + tank.encode()),
            "qa": self.qa,
            "resolve": lambda entry: {"status": "RESOLVED", "product": self.product()},
            "execute": lambda entry, path, digest: {"status": "VERIFIED", "receipt": {}},
            "archive": lambda state, batch_dir: {"status": "ARCHIVED"},
        }

    def use_reference_comparator(self):
        """Force the pinned-contract reference comparator for one test."""
        original = getattr(strict_mod.label_mod, "compare_reads", None)
        strict_mod.label_mod.compare_reads = _reference_compare_reads
        self.addCleanup(self._restore_comparator, original)

    @staticmethod
    def _restore_comparator(original):
        if original is None:
            if hasattr(strict_mod.label_mod, "compare_reads"):
                del strict_mod.label_mod.compare_reads
        else:
            strict_mod.label_mod.compare_reads = original

    def remove_comparator(self):
        """Simulate A2's comparator not existing yet (must degrade safely)."""
        original = getattr(strict_mod.label_mod, "compare_reads", None)
        if hasattr(strict_mod.label_mod, "compare_reads"):
            del strict_mod.label_mod.compare_reads
        self.addCleanup(self._restore_comparator, original)

    def remove_prepare_label_crop(self):
        """Simulate A2's crop helper being unavailable (in-file fallback path)."""
        original = getattr(strict_mod.prepare_mod, "label_crop", None)
        if hasattr(strict_mod.prepare_mod, "label_crop"):
            del strict_mod.prepare_mod.label_crop
        self.addCleanup(self._restore_prepare_label_crop, original)

    @staticmethod
    def _restore_prepare_label_crop(original):
        if original is None:
            if hasattr(strict_mod.prepare_mod, "label_crop"):
                del strict_mod.prepare_mod.label_crop
        else:
            strict_mod.prepare_mod.label_crop = original

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

    def label(self, files):
        """Default focused label-crop read: agrees with the catalogue fixture."""
        return {
            "provider": "mock-router", "model": "mock-vision", "call_id": "label-1",
            "timestamp": now(), "input_hashes": [sha(files[0])],
            "routing": routing(), "usage": {"tokens_input": 5, "tokens_output": 3},
            "output": {"tank_id": "2 BT 12", "tank_confidence": 0.97,
                       "photo_date": "9/10/2026", "date_confidence": 0.96,
                       "visible_price": "$35", "reasons": []},
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
        working = entry.get("working_input_sha256") or entry["source_sha256"]
        return {
            "provider": "mock-router", "model": "mock-vision", "call_id": "qa-1",
            "timestamp": now(),
            "routing": routing(), "usage": {"tokens_input": 13, "tokens_output": 5},
            "input_hashes": [working, entry["hero_sha256"],
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
        self.assertEqual(Path(result["fish"][0]["path"]).read_bytes(), self.source.read_bytes())
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
                       "photo_date": "9/10/2026", "date_confidence": 0.95, "reasons": []},
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
        self.assertEqual(retried["photo_date"], "2026-10-09")
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

    # -- dual label reads (full photo + focused crop) ---------------------- #
    def test_dual_read_agreement_accepts_and_records_both_receipts(self):
        self.use_reference_comparator()
        adapters, _ = self.make()
        record = adapters["intake"](self.batch, {})["fish"][0]
        result = adapters["identify"](record, self.batch)
        self.assertFalse(result["uncertain"])
        self.assertFalse(result["quarantine"])
        self.assertEqual(result["tank_id"], "2BT12")
        self.assertEqual(result["photo_date"], "2026-10-09")
        self.assertEqual(result["label_price_visible"], "35")
        reads = result["label_reads"]
        self.assertEqual(reads["status"], "AGREE")
        self.assertEqual(reads["full"]["tank_id"], "2BT12")
        self.assertEqual(reads["full"]["receipt_path"], result["catalogue_evidence_path"])
        self.assertEqual(reads["crop"]["tank_id"], "2BT12")
        self.assertEqual(reads["crop"]["photo_date"], "2026-10-09")
        for side in ("full", "crop"):
            path = Path(reads[side]["receipt_path"])
            self.assertTrue(path.is_file())
            self.assertEqual(reads[side]["receipt_sha256"], sha(path))
        receipt = json.loads(Path(reads["crop"]["receipt_path"]).read_text())
        self.assertEqual(receipt["schema"], "nta-betta-label-corroboration-v1")
        self.assertEqual(receipt["status"], "AGREE")
        self.assertEqual(receipt["batch_id"], "betta-test-bau")
        self.assertEqual(receipt["input_hashes"], [reads["crop"]["crop_sha256"]])
        self.assertEqual(receipt["visible_price"], "35")
        self.assertEqual(receipt["full_read"]["tank_id"], "2BT12")
        self.assertFalse(os.stat(reads["crop"]["receipt_path"]).st_mode & 0o222)
        expected_helper = ("betta_prepare.label_crop"
                           if callable(getattr(strict_mod.prepare_mod, "label_crop", None))
                           else "in_file_top_band")
        self.assertEqual(receipt["crop_identity"]["helper"], expected_helper)
        if expected_helper == "betta_prepare.label_crop":
            detection = receipt["crop_identity"]["detection"]
            self.assertEqual(detection["source_sha256"], record["sha256"])
            self.assertEqual(detection["output_sha256"], reads["crop"]["crop_sha256"])
            # The helper commits onto the final crop path itself: the recorded
            # detection must never name a staging ".part" sibling.
            self.assertEqual(detection["output_path"], receipt["crop_identity"]["path"])
            self.assertNotIn(".part", detection["output_path"])
            self.assertNotIn(".part", receipt["crop_identity"]["path"])

    def test_dual_read_uses_the_real_compare_reads_when_present(self):
        """End-to-end wiring against A2's pinned comparator (skipped until it lands)."""
        real = getattr(strict_mod.label_mod, "compare_reads", None)
        if not callable(real):
            self.skipTest("label_identity.compare_reads has not landed yet")
        self.addCleanup(self._restore_comparator, real)
        strict_mod.label_mod.compare_reads = real
        self.runners["label"] = lambda files: {
            "provider": "mock-router", "model": "mock-vision", "call_id": "label-real",
            "timestamp": now(), "input_hashes": [sha(files[0])],
            "routing": routing(), "usage": {},
            "output": {"tank_id": "5 BT 43", "tank_confidence": 0.98,
                       "photo_date": "9/10/2026", "date_confidence": 0.97, "reasons": []},
        }
        adapters, _ = self.make()
        record = adapters["intake"](self.batch, {})["fish"][0]
        result = adapters["identify"](record, self.batch)
        self.assertTrue(result["quarantine"])
        self.assertEqual(result["quarantine_reason"],
                         "label read disagreement: full=2BT12, crop=5BT43")
        self.assertEqual(result["label_reads"]["status"], "DISAGREE")

    def test_dual_read_is_reused_without_a_second_label_call(self):
        self.use_reference_comparator()
        counts = {"label": 0}
        original = self.label
        self.runners["label"] = lambda files: (
            counts.__setitem__("label", counts["label"] + 1) or original(files))
        adapters, _ = self.make()
        record = adapters["intake"](self.batch, {})["fish"][0]
        first = adapters["identify"](record, self.batch)
        second = adapters["identify"](record, self.batch)
        self.assertEqual(counts["label"], 1)
        self.assertEqual(first["label_reads"]["crop"]["receipt_sha256"],
                         second["label_reads"]["crop"]["receipt_sha256"])
        self.assertEqual(second["label_reads"]["status"], "AGREE")

    def test_dual_read_tank_disagreement_quarantines_with_both_readings(self):
        self.use_reference_comparator()
        self.runners["label"] = lambda files: {
            "provider": "mock-router", "model": "mock-vision", "call_id": "label-x",
            "timestamp": now(), "input_hashes": [sha(files[0])],
            "routing": routing(), "usage": {},
            "output": {"tank_id": "5 BT 43", "tank_confidence": 0.98,
                       "photo_date": "9/10/2026", "date_confidence": 0.97, "reasons": []},
        }
        adapters, _ = self.make()
        record = adapters["intake"](self.batch, {})["fish"][0]
        result = adapters["identify"](record, self.batch)
        # The secondary read never redirects identity: the full read is retained
        # for evidence but the fish is hard-quarantined.
        self.assertEqual(result["tank_id"], "2BT12")
        self.assertTrue(result["uncertain"])
        self.assertTrue(result["quarantine"])
        self.assertEqual(result["quarantine_reason"],
                         "label read disagreement: full=2BT12, crop=5BT43")
        reads = result["label_reads"]
        self.assertEqual(reads["status"], "DISAGREE")
        self.assertEqual(reads["full"]["tank_id"], "2BT12")
        self.assertEqual(reads["crop"]["tank_id"], "5BT43")
        for side in ("full", "crop"):
            path = Path(reads[side]["receipt_path"])
            self.assertTrue(path.is_file())
            self.assertEqual(reads[side]["receipt_sha256"], sha(path))
        crop_receipt = json.loads(Path(reads["crop"]["receipt_path"]).read_text())
        self.assertEqual(crop_receipt["status"], "DISAGREE")
        self.assertEqual(crop_receipt["full_read"]["tank_id"], "2BT12")
        self.assertEqual(crop_receipt["crop_reading"]["tank_id"], "5BT43")
        self.assertEqual(crop_receipt["visible_price"], None)
        import sqlite3
        con = sqlite3.connect(self.telemetry)
        try:
            row = con.execute(
                "SELECT outcome FROM betta_call_telemetry WHERE batch_id=? AND tank_number=? "
                "AND stage='identify_label_corroboration'",
                ("betta-test-bau", "2BT12"),
            ).fetchone()
        finally:
            con.close()
        self.assertEqual(row, ("DISAGREE",))

    def test_dual_read_date_only_disagreement_quarantines(self):
        self.use_reference_comparator()
        self.runners["label"] = lambda files: {
            "provider": "mock-router", "model": "mock-vision", "call_id": "label-y",
            "timestamp": now(), "input_hashes": [sha(files[0])],
            "routing": routing(), "usage": {},
            "output": {"tank_id": "2 BT 12", "tank_confidence": 0.98,
                       "photo_date": "14/10/2026", "date_confidence": 0.97, "reasons": []},
        }
        adapters, _ = self.make()
        record = adapters["intake"](self.batch, {})["fish"][0]
        result = adapters["identify"](record, self.batch)
        self.assertTrue(result["quarantine"])
        self.assertEqual(
            result["quarantine_reason"],
            "label read disagreement: full=2BT12, crop=2BT12; "
            "date full=2026-10-09, crop=2026-10-14")
        self.assertEqual(result["label_reads"]["status"], "DISAGREE")

    def test_dual_read_uncertain_crop_leaves_the_confident_full_read_in_force(self):
        self.use_reference_comparator()
        self.runners["label"] = lambda files: {
            "provider": "mock-router", "model": "mock-vision", "call_id": "label-low",
            "timestamp": now(), "input_hashes": [sha(files[0])],
            "routing": routing(), "usage": {},
            "output": {"tank_id": "2 BT 12", "tank_confidence": 0.80,
                       "photo_date": "9/10/2026", "date_confidence": 0.95, "reasons": []},
        }
        adapters, _ = self.make()
        record = adapters["intake"](self.batch, {})["fish"][0]
        result = adapters["identify"](record, self.batch)
        self.assertFalse(result["uncertain"])
        self.assertFalse(result["quarantine"])
        self.assertEqual(result["tank_id"], "2BT12")
        self.assertEqual(result["label_reads"]["status"], "INCOMPLETE")
        self.assertFalse(result["label_reads"]["crop"]["confident"])
        receipt = json.loads(
            Path(result["label_reads"]["crop"]["receipt_path"]).read_text())
        self.assertEqual(receipt["status"], "INCOMPLETE")

    def test_dual_read_transport_failure_retries_then_falls_back(self):
        self.use_reference_comparator()
        calls = {"label": 0}

        def failing(files):
            calls["label"] += 1
            raise RuntimeError("provider unreachable")

        self.runners["label"] = failing
        self.runners["vision_retry_delay_seconds"] = 0
        adapters, _ = self.make()
        record = adapters["intake"](self.batch, {})["fish"][0]
        result = adapters["identify"](record, self.batch)
        self.assertEqual(calls["label"], 2)  # bounded retry inside _vision_call
        # Documented fallback: the corroborating read could not run, so the
        # already-validated confident full read remains the acceptance
        # authority; the failure itself is recorded truthfully, never hidden.
        self.assertFalse(result["uncertain"])
        self.assertFalse(result["quarantine"])
        self.assertEqual(result["tank_id"], "2BT12")
        self.assertEqual(result["label_reads"]["status"], "UNAVAILABLE")
        self.assertTrue(any("label corroboration read failed" in reason
                            for reason in result["label_reads"]["reasons"]))

    def test_dual_read_missing_comparator_degrades_to_incomplete(self):
        # A2's comparator is not landed in this worktree yet: absence must be
        # INCOMPLETE, never a fabricated verdict in either direction.
        self.remove_comparator()
        self.runners["label"] = lambda files: {
            "provider": "mock-router", "model": "mock-vision", "call_id": "label-z",
            "timestamp": now(), "input_hashes": [sha(files[0])],
            "routing": routing(), "usage": {},
            "output": {"tank_id": "5 BT 43", "tank_confidence": 0.98,
                       "photo_date": "9/10/2026", "date_confidence": 0.97, "reasons": []},
        }
        adapters, _ = self.make()
        record = adapters["intake"](self.batch, {})["fish"][0]
        result = adapters["identify"](record, self.batch)
        self.assertEqual(result["label_reads"]["status"], "INCOMPLETE")
        self.assertTrue(any("compare_reads is unavailable" in reason
                            for reason in result["label_reads"]["reasons"]))
        self.assertFalse(result["quarantine"])
        receipt = json.loads(
            Path(result["label_reads"]["crop"]["receipt_path"]).read_text())
        self.assertEqual(receipt["status"], "INCOMPLETE")

    def test_retry_identify_refuses_a_contradicting_confident_crop_read(self):
        original = self.runners["catalogue"]
        self.runners["catalogue"] = lambda files: {
            **original(files),
            "output": {**original(files)["output"],
                       "confidence": {name: (0.88 if name == "photo_date" else 0.99)
                                      for name in strict_mod.CATALOGUE_FIELDS}},
        }
        self.runners["label"] = lambda files: {
            "provider": "mock-router", "model": "mock-vision", "call_id": "label-c",
            "timestamp": now(), "input_hashes": [sha(files[0])],
            "routing": routing(), "usage": {},
            "output": {"tank_id": "5 BT 43", "tank_confidence": 0.98,
                       "photo_date": "9/10/2026", "date_confidence": 0.97, "reasons": []},
        }
        adapters, _ = self.make()
        record = adapters["intake"](self.batch, {})["fish"][0]
        decision = adapters["identify"](record, self.batch)
        self.assertTrue(decision["uncertain"])  # below-gate catalogue date
        self.assertFalse(decision["quarantine"])  # no dual compare: full read unsure
        self.assertEqual(decision["catalogue_confidences"],
                         {"tank_id": 0.99, "photo_date": None})
        entry = {"source_path": record["path"], "source_sha256": record["sha256"],
                 **decision}
        retried = adapters["retry_identify"](entry, self.batch)
        # The confident catalogue tank (gate passed) still vetoes the
        # contradicting confident label read, even though the date is below gate.
        self.assertTrue(retried["uncertain"])
        self.assertIsNone(retried["tank_id"])
        self.assertIn("contradicts the catalogue read", retried["reason"])
        self.assertEqual(retried["label_reads"]["status"], "RETRY_CONFLICT")
        receipt = json.loads(Path(retried["catalogue_evidence_path"]).read_text())
        self.assertTrue(receipt["uncertain"])
        self.assertEqual(receipt["contradiction"], "catalogue tank 2BT12 vs label tank 5BT43")
        self.assertEqual(receipt["catalogue_reading"]["gate_passed"],
                         {"tank_id": True, "photo_date": False})
        self.assertEqual(receipt["catalogue_reading"]["confidences"],
                         {"tank_id": 0.99, "photo_date": None})
        self.assertEqual(receipt["catalogue_reading"]["disposition"], "REFUSED")
        self.assertIn("confident catalogue field contradiction",
                      receipt["catalogue_reading"]["disposition_reason"])
        import sqlite3
        con = sqlite3.connect(self.telemetry)
        try:
            row = con.execute(
                "SELECT tank_number,outcome FROM betta_call_telemetry WHERE batch_id=? "
                "AND stage='identify_label_retry'",
                ("betta-test-bau",),
            ).fetchone()
        finally:
            con.close()
        self.assertEqual(row, ("5BT43", "CONFLICT"))

    def test_retry_identify_recovers_an_uncertain_read_with_an_agreeing_crop(self):
        original = self.runners["catalogue"]
        self.runners["catalogue"] = lambda files: {
            **original(files),
            "output": {**original(files)["output"],
                       "confidence": {name: (0.88 if name == "tank_id" else 0.99)
                                      for name in strict_mod.CATALOGUE_FIELDS}},
        }
        adapters, _ = self.make()
        record = adapters["intake"](self.batch, {})["fish"][0]
        decision = adapters["identify"](record, self.batch)
        self.assertTrue(decision["uncertain"])
        entry = {"source_path": record["path"], "source_sha256": record["sha256"],
                 **decision}
        retried = adapters["retry_identify"](entry, self.batch)
        self.assertFalse(retried["uncertain"])
        self.assertEqual(retried["tank_id"], "2BT12")
        self.assertEqual(retried["photo_date"], "2026-10-09")
        self.assertEqual(retried["label_reads"]["status"], "RETRY_ACCEPTED")
        receipt = json.loads(Path(retried["catalogue_evidence_path"]).read_text())
        self.assertFalse(receipt["uncertain"])
        self.assertIsNone(receipt["contradiction"])
        self.assertEqual(receipt["visible_price"], "35")
        self.assertEqual(receipt["catalogue_reading"]["gate_passed"],
                         {"tank_id": False, "photo_date": True})
        self.assertEqual(receipt["catalogue_reading"]["disposition"], "ACCEPTED")
        self.assertIn("tank below gate",
                      receipt["catalogue_reading"]["disposition_reason"])

    def test_retry_accepts_a_confident_crop_over_a_below_gate_catalogue_date(self):
        # Real evaluation shape: the catalogue tank is confident, the catalogue
        # date is below gate (discarded, that is why the fish is in retry) and
        # differs from the focused read.  The focused read must establish it.
        original = self.runners["catalogue"]
        self.runners["catalogue"] = lambda files: {
            **original(files),
            "output": {**original(files)["output"], "photo_date": "2026-04-10",
                       "confidence": {name: (0.88 if name == "photo_date" else 0.99)
                                      for name in strict_mod.CATALOGUE_FIELDS}},
        }
        self.runners["label"] = lambda files: {
            "provider": "mock-router", "model": "mock-vision", "call_id": "label-real-shape",
            "timestamp": now(), "input_hashes": [sha(files[0])],
            "routing": routing(), "usage": {},
            "output": {"tank_id": "2 BT 12", "tank_confidence": 0.99,
                       "photo_date": "14/10/2026", "date_confidence": 0.95, "reasons": []},
        }
        adapters, _ = self.make()
        record = adapters["intake"](self.batch, {})["fish"][0]
        decision = adapters["identify"](record, self.batch)
        self.assertTrue(decision["uncertain"])
        self.assertFalse(decision["quarantine"])
        self.assertEqual(decision["photo_date"], "2026-04-10")
        self.assertEqual(decision["catalogue_confidences"],
                         {"tank_id": 0.99, "photo_date": None})
        catalogue_receipt = json.loads(Path(decision["catalogue_evidence_path"]).read_text())
        self.assertEqual(catalogue_receipt["catalogue_confidence_gates"],
                         {"tank_id": "PASS", "photo_date": "BELOW_GATE"})
        self.assertEqual(catalogue_receipt["catalogue_confidence_raw"]["photo_date"], 0.88)
        entry = {"source_path": record["path"], "source_sha256": record["sha256"],
                 **decision}
        retried = adapters["retry_identify"](entry, self.batch)
        self.assertFalse(retried["uncertain"])
        self.assertEqual(retried["tank_id"], "2BT12")
        self.assertEqual(retried["photo_date"], "2026-10-14")
        self.assertIsNone(retried["reason"])
        self.assertEqual(retried["label_reads"]["status"], "RETRY_ACCEPTED")
        receipt = json.loads(Path(retried["catalogue_evidence_path"]).read_text())
        self.assertIsNone(receipt["contradiction"])
        self.assertFalse(receipt["uncertain"])
        self.assertEqual(receipt["catalogue_reading"]["gate_passed"],
                         {"tank_id": True, "photo_date": False})
        self.assertEqual(receipt["catalogue_reading"]["confidences"],
                         {"tank_id": 0.99, "photo_date": None})
        self.assertEqual(receipt["catalogue_reading"]["disposition"], "ACCEPTED")
        self.assertIn("date below gate",
                      receipt["catalogue_reading"]["disposition_reason"])
        if callable(getattr(strict_mod.prepare_mod, "label_crop", None)):
            crop_identity = receipt["crop_identity"]
            self.assertEqual(crop_identity["helper"], "betta_prepare.label_crop")
            detection = crop_identity["detection"]
            self.assertEqual(detection["output_path"], crop_identity["path"])
            self.assertNotIn(".part", detection["output_path"])
            self.assertNotIn(".part", crop_identity["path"])
            self.assertEqual(detection["source_sha256"], record["sha256"])
            self.assertEqual(detection["output_sha256"], crop_identity["sha256"])

    def test_label_crop_falls_back_to_the_in_file_top_band(self):
        # With A2's helper unavailable the in-file top-band crop must still be
        # produced, recorded with its own provenance and no helper detection.
        self.remove_prepare_label_crop()
        original = self.runners["catalogue"]
        self.runners["catalogue"] = lambda files: {
            **original(files),
            "output": {**original(files)["output"],
                       "confidence": {name: (0.88 if name == "tank_id" else 0.99)
                                      for name in strict_mod.CATALOGUE_FIELDS}},
        }
        adapters, _ = self.make()
        record = adapters["intake"](self.batch, {})["fish"][0]
        decision = adapters["identify"](record, self.batch)
        self.assertTrue(decision["uncertain"])
        entry = {"source_path": record["path"], "source_sha256": record["sha256"],
                 **decision}
        retried = adapters["retry_identify"](entry, self.batch)
        self.assertFalse(retried["uncertain"])
        self.assertEqual(retried["tank_id"], "2BT12")
        receipt = json.loads(Path(retried["catalogue_evidence_path"]).read_text())
        crop_identity = receipt["crop_identity"]
        self.assertEqual(crop_identity["helper"], "in_file_top_band")
        self.assertIsNone(crop_identity["detection"])
        self.assertNotIn(".part", crop_identity["path"])
        crop_path = Path(crop_identity["path"])
        self.assertTrue(crop_path.is_file())
        self.assertEqual(crop_identity["sha256"], sha(crop_path))
        from PIL import Image as _Image
        with _Image.open(crop_path) as image:
            # The fixture source is 48x64; the top-band fallback keeps full width
            # and the 30% band height.
            self.assertEqual(image.size, (48, 19))

    def test_retry_refuses_a_confident_catalogue_date_contradiction(self):
        # Per-field independence: the below-gate tank cannot veto, but a
        # gate-passed date that contradicts the focused read still refuses.
        original = self.runners["catalogue"]
        self.runners["catalogue"] = lambda files: {
            **original(files),
            "output": {**original(files)["output"],
                       "confidence": {name: (0.88 if name == "tank_id" else 0.99)
                                      for name in strict_mod.CATALOGUE_FIELDS}},
        }
        self.runners["label"] = lambda files: {
            "provider": "mock-router", "model": "mock-vision", "call_id": "label-date-c",
            "timestamp": now(), "input_hashes": [sha(files[0])],
            "routing": routing(), "usage": {},
            "output": {"tank_id": "2 BT 12", "tank_confidence": 0.98,
                       "photo_date": "14/10/2026", "date_confidence": 0.97, "reasons": []},
        }
        adapters, _ = self.make()
        record = adapters["intake"](self.batch, {})["fish"][0]
        decision = adapters["identify"](record, self.batch)
        self.assertTrue(decision["uncertain"])
        entry = {"source_path": record["path"], "source_sha256": record["sha256"],
                 **decision}
        retried = adapters["retry_identify"](entry, self.batch)
        self.assertTrue(retried["uncertain"])
        self.assertIsNone(retried["tank_id"])
        self.assertIn("catalogue date 2026-10-09 vs label date 2026-10-14",
                      retried["reason"])
        self.assertEqual(retried["label_reads"]["status"], "RETRY_CONFLICT")
        receipt = json.loads(Path(retried["catalogue_evidence_path"]).read_text())
        self.assertEqual(receipt["contradiction"],
                         "catalogue date 2026-10-09 vs label date 2026-10-14")
        self.assertEqual(receipt["catalogue_reading"]["gate_passed"],
                         {"tank_id": False, "photo_date": True})
        self.assertEqual(receipt["catalogue_reading"]["disposition"], "REFUSED")

    def test_retry_accepts_when_the_catalogue_tank_is_below_gate(self):
        # A below-gate catalogue tank value (even one that differs) cannot veto
        # the confident focused read; the focused read establishes the tank.
        original = self.runners["catalogue"]
        self.runners["catalogue"] = lambda files: {
            **original(files),
            "output": {**original(files)["output"], "tank_id": "5 BT 43",
                       "confidence": {name: (0.85 if name == "tank_id" else 0.99)
                                      for name in strict_mod.CATALOGUE_FIELDS}},
        }
        adapters, _ = self.make()
        record = adapters["intake"](self.batch, {})["fish"][0]
        decision = adapters["identify"](record, self.batch)
        self.assertTrue(decision["uncertain"])
        self.assertEqual(decision["tank_id"], "5BT43")  # retained as evidence, gate failed
        self.assertEqual(decision["catalogue_confidences"],
                         {"tank_id": None, "photo_date": 0.99})
        entry = {"source_path": record["path"], "source_sha256": record["sha256"],
                 **decision}
        retried = adapters["retry_identify"](entry, self.batch)
        self.assertFalse(retried["uncertain"])
        self.assertEqual(retried["tank_id"], "2BT12")
        self.assertEqual(retried["photo_date"], "2026-10-09")
        self.assertEqual(retried["label_reads"]["status"], "RETRY_ACCEPTED")
        receipt = json.loads(Path(retried["catalogue_evidence_path"]).read_text())
        self.assertIsNone(receipt["contradiction"])
        self.assertEqual(receipt["catalogue_reading"]["gate_passed"],
                         {"tank_id": False, "photo_date": True})
        self.assertEqual(receipt["catalogue_reading"]["disposition"], "ACCEPTED")

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

    def test_qa_failure_receipt_preserves_reasons_and_categories(self):
        adapters, _bundle, entry = self.prepared_entry()
        receipt = Path(entry["image_qa_path"])
        os.chmod(receipt, 0o644)
        receipt.unlink()
        reasons = ["The hero introduces blue markings the source visibly refutes.",
                   "Regional colour direction is contradicted."]
        self.runners["qa"] = lambda value: {
            **self.qa(value),
            "call_id": "qa-fail-1",
            "output": {**self.qa(value)["output"],
                       "assertions": {**{name: "PASS" for name in strict_mod.QA_ASSERTIONS},
                                      "same_identity": "FAIL", "regional_colour": "FAIL"},
                       "overall": "FAIL", "reasons": reasons},
        }
        failed = adapters["qa"](entry, self.batch)
        self.assertEqual(failed["outcome"], "FAIL")
        self.assertEqual(failed["reasons"], reasons)
        self.assertIn("same_identity", failed["categories"]["identity"])
        self.assertIn("regional_colour", failed["categories"]["identity"])
        failure_receipt = json.loads(Path(failed["failure_receipt_path"]).read_text())
        self.assertEqual(failure_receipt["output"]["reasons"], reasons)
        self.assertEqual(failure_receipt["failed_assertions"],
                         ["regional_colour", "same_identity"])

    def test_qa_subprocess_transport_failures_are_retried(self):
        adapters, _bundle, entry = self.prepared_entry()
        receipt = Path(entry["image_qa_path"])
        os.chmod(receipt, 0o644)
        receipt.unlink()
        self.runners.pop("qa")  # force the attested subprocess path
        self.runners["vision_retry_delay_seconds"] = 0
        # The deterministic subprocess path requires a real 2048 hero image.
        from PIL import Image as _Image
        hero = Path(entry["hero_path"])
        _Image.new("RGB", (2048, 2048), (8, 8, 10)).save(hero)
        entry["hero_sha256"] = sha(hero)
        adapters, _ = self.make()
        attempts = {"count": 0}
        original = strict_mod.base._subprocess_runner

        def flaky(argv):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise strict_mod.base.AdapterError("command failed (2): connection error")
            return json.dumps(self.qa(entry))

        strict_mod.base._subprocess_runner = flaky
        try:
            result = adapters["qa"](entry, self.batch)
        finally:
            strict_mod.base._subprocess_runner = original
        self.assertEqual(result["outcome"], "PASS")
        self.assertEqual(attempts["count"], 2)

    def test_build_manifest_passes_real_manifest_bundle_validation(self):
        adapters, _bundle, entry = self.prepared_entry()
        built = adapters["build_manifest"]({"fish": {"source": entry}}, self.batch)
        path = Path(built["manifest_path"])
        loaded = bsb.ManifestBundle(path)
        self.assertEqual(set(loaded.contexts), {"2BT12"})
        self.assertEqual(built["manifest_sha256"], sha(path))
        self.assertTrue(loaded.raw["shopify_write_authorised"])
        self.assertIsNone(loaded.raw["items"][0]["image_qa"]["exception"])

    def test_build_manifest_populates_the_pinned_identity_block(self):
        adapters, _bundle, entry = self.prepared_entry()
        built = adapters["build_manifest"]({"fish": {"source": entry}}, self.batch)
        item = built["manifest"]["items"][0]
        self.assertEqual(item["identity"], {
            "source_sha256": entry["source_sha256"],
            "detected_tank": "2BT12", "requested_tank": "2BT12",
            "accepted_tank": "2BT12", "correction_sha256": None,
        })
        loaded = bsb.ManifestBundle(Path(built["manifest_path"]))
        self.assertEqual(loaded.raw["items"][0]["identity"]["accepted_tank"], "2BT12")

    def test_build_manifest_refuses_a_quarantined_label_disagreement(self):
        adapters, _bundle, entry = self.prepared_entry()
        entry["label_reads"] = {"status": "DISAGREE"}
        with self.assertRaisesRegex(strict_mod.StrictAdapterError,
                                    "must never reach a manifest"):
            adapters["build_manifest"]({"fish": {"source": entry}}, self.batch)

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
