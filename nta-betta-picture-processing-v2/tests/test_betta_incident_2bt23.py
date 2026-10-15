"""Incident regression suite — 2BT23 misidentified as 5BT43 (P1, 2026-10-15).

Independent adversarial QA (Agent 5) over the identity-firewall repair. The
fixtures are the genuine bytes of the incident photo and the archived
near-confusion 5BT43 photo (see ``tests/fixtures/incident_2bt23/README.md``).

Required-category map (module header):

1.  Correct original-image identification ............ Category01OriginalImageIdentification
2.  Correct cropped-label identification ............. Category02CroppedLabelIdentification
3.  Wrong high-confidence identification blocked ..... Category03WrongHighConfidenceIdentification
4.  Wrong photograph date blocked .................... Category04WrongPhotographDate
5.  Disagreement / INCOMPLETE handling ............... Category05DisagreementAndIncomplete
6.  Requested != detected tank at manifest load ...... Category06RequestedDetectedMismatch
7.  Prevention of wrong-product writes ............... Category07WrongProductWritePrevention
8.  Owner correction with exact source binding ....... Category08OwnerCorrection
9.  Correction reuse for another image/product ....... Category09CorrectionReuseRefusal
10. Duplicate image hashes / one identity ............ Category10DuplicateHashes
11. Source-hash attribution refusal .................. Category11SourceHashAttribution
12. Recorded model assertions vs image evidence ...... Category12RecordedModelEvidence
13. Resume after interrupted mutation ................ Category13InterruptedMutationResume
14. Independent Shopify read-back .................... Category14ShopifyReadBack
15. Autonomous quarantine of unresolved cases ........ Category15AutonomousQuarantine
16. Original camera file preservation ................ Category16OriginalPreservation
17. No unauthorised price/cost/vendor changes ........ Category17ProtectedFields
18. No duplicate Shopify mutations (idempotency) ..... Category18Idempotency
19. Repeat correction requests are immutable ......... Category19RepeatCorrections
20. Concurrent batches with similar numbers .......... Category20ConcurrentBatches

Every mocked vision output used below is a *fixture* for plumbing tests and is
never presented as OCR evidence; the only real model readings are the archived
verbatim records under ``docs/incident/incident_eval/`` (A5's real run) and
``docs/incident/label_recognition_evidence/`` (A2's real run), which this suite
reads but does not rewrite.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image  # noqa: F401  (fixture sanity checks)

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURES = ROOT / "tests" / "fixtures" / "incident_2bt23"
EVAL_DIR = ROOT / "docs" / "incident" / "incident_eval"
A2_EVIDENCE_DIR = ROOT / "docs" / "incident" / "label_recognition_evidence"

INCIDENT_PHOTO = FIXTURES / "incident-photo.png"
INCIDENT_PHOTO_SECOND = FIXTURES / "incident-photo-second-upload.png"
NEAR_CONFUSION_PHOTO = FIXTURES / "near-confusion-5bt43-original.png"
INCIDENT_SHA = "6e4a4f573f8cfc829218f798eeb5b45cd08803689d31d7db6fce4920cdca9ca9"
NEAR_CONFUSION_SHA = "6c1d0e92004f5170c23797e7da5aabb11d72daade97f418308fc679fd6a15ecc"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import betta_adapters  # noqa: E402
import betta_batches  # noqa: E402
import betta_budget  # noqa: E402
import betta_bau_adapters  # noqa: E402
import betta_policy  # noqa: E402
import betta_prepare  # noqa: E402
import betta_process  # noqa: E402
import betta_watch  # noqa: E402
import label_identity  # noqa: E402

try:  # tests-dir invocation (python -m unittest discover -s tests -t tests)
    from test_betta_shopify_batch import (
        FakeGateway,
        Fixture as ShopifyFixture,
    )
except ImportError:  # repo-root invocation (python -m unittest <path>.<module>)
    from .test_betta_shopify_batch import (  # type: ignore
        FakeGateway,
        Fixture as ShopifyFixture,
    )

bsb = sys.modules["betta_shopify_batch"] if "betta_shopify_batch" in sys.modules else None
if bsb is None:  # the import above loads it under its canonical name
    import betta_shopify_batch as bsb  # noqa: E402

corrections = bsb.corrections_module()


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def sha256(path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def routing() -> dict:
    return {
        "class": "STANDARD", "authority": "adaptive-model-router/v2.1",
        "requested_route": "mock-router/mock-vision",
        "eligible_routes": ["mock-router/mock-vision"],
        "actual_provider": "mock-router", "actual_model": "mock-vision",
        "fallback_used": False, "execution_attested": True,
    }


def mock_evidence(files, output, call_id) -> dict:
    return {
        "provider": "mock-router", "model": "mock-vision", "call_id": call_id,
        "timestamp": now_utc(), "input_hashes": [sha256(f) for f in files],
        "routing": routing(), "usage": {}, "output": output,
    }


def catalogue_output(tank, photo_date, tank_conf=0.98, date_conf=0.96,
                     fish_name="Pastel Pink", tail_type="Halfmoon",
                     sex="Male") -> dict:
    return {
        "tank_id": tank, "photo_date": photo_date, "tank_confidence": tank_conf,
        "date_confidence": date_conf, "one_fish_visible": True,
        "fish_name": fish_name, "tail_type": tail_type, "sex": sex,
        "sex_confidence": 0.0, "uncertainty_reasons": [],
    }


def label_output(tank, date_dmy, tank_conf=0.99, date_conf=0.96,
                 price="35") -> dict:
    return {
        "tank_id": tank, "tank_confidence": tank_conf,
        "photo_date": date_dmy, "date_confidence": date_conf,
        "visible_price": price, "reasons": [],
    }


def preflight_output(tank, photo_date, tank_conf=0.99, date_conf=0.93,
                     fish_conf=0.95) -> dict:
    return {
        "tank_id": tank, "photo_date": photo_date, "tank_confidence": tank_conf,
        "date_confidence": date_conf, "fish_confidence": fish_conf,
        "one_fish_visible": True, "needs_retake": False,
        "tank_bounds": [0.0, 0.0, 1.0, 1.0],
        "fish_bounds": [0.25, 0.15, 0.75, 0.85],
        "debris_boxes": [], "reason": "",
    }


def prepqa_output() -> dict:
    return {
        "overall": "PASS", "same_fish": True, "full_fins": True,
        "faithful_colours": True, "tank_only": True, "lighting_usable": True,
        "no_identity_alteration": True, "reason": "",
    }


def product_snapshot(tank: str, index: int) -> dict:
    """Mocked Shopify product snapshot shaped exactly like the uploader's."""
    product_id = f"gid://shopify/Product/{1000 + index}"
    variant_id = f"gid://shopify/ProductVariant/{2000 + index}"
    inventory_id = f"gid://shopify/InventoryItem/{3000 + index}"
    location_id = "gid://shopify/Location/401"
    raw = {
        "id": product_id, "title": f"{tank} - Old Betta Male", "status": "ACTIVE",
        "descriptionHtml": "<p>Protected</p>",
        "media": {"pageInfo": {"hasNextPage": False}, "nodes": [{
            "id": f"gid://shopify/MediaImage/{5000 + index}",
            "mediaContentType": "IMAGE",
            "image": {"url": "https://example.test/old.png"},
        }]},
        "variants": {"pageInfo": {"hasNextPage": False}, "nodes": [{
            "id": variant_id, "price": "25.00", "inventoryQuantity": 0,
            "inventoryPolicy": "DENY", "inventoryItem": {
                "id": inventory_id, "tracked": True,
                "unitCost": {"amount": "1.00", "currencyCode": "AUD"},
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
            "price": "25.00", "cost": "1.00", "vendor": "NTA Imports",
            "product_type": "Domesticated Betta", "handle": tank.lower(),
            "status": "ACTIVE", "inventory": 0, "inventory_policy": "DENY",
            "tracked": True, "arrival_date": "2026-08-01",
        },
    }


class StrictSandbox:
    """Hermetic strict-batch sandbox (no network, no real writes).

    ``vision`` maps a source sha256 to the mocked outputs for that photo:
    ``{"catalogue": {...}, "label": {...}, "preflight": {...}, "prepqa": {...}}``.
    Label-read mockery is keyed by the crop filename (``<source-sha>-label.png``),
    so every mocked reading still binds the input hash it claims to.
    """

    def __init__(self, root: Path, sources, vision, *, policy_mode="gated",
                 registry: Path = None, label="incident-sandbox"):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.intake = self.root / "intake"
        self.intake.mkdir(parents=True, exist_ok=True)
        self.vision = vision
        self.products = {
            reading.get("catalogue", {}).get("tank_id") or position: product_snapshot(
                reading.get("catalogue", {}).get("tank_id") or f"FISH{position}",
                position)
            for position, reading in enumerate(vision.values(), 1)
        }
        copied = []
        for source in sources:
            source = Path(source)
            destination = self.intake / source.name
            shutil.copy2(source, destination)
            copied.append(destination)
        self.selected = [{"path": str(path), "sha256": sha256(path),
                          "size": path.stat().st_size} for path in copied]
        batch = betta_batches.create_batch(self.root / "batches", label=label)
        self.batch_id = batch["batch_id"]
        self.batch_dir = Path(batch["path"])
        sources_path = self.batch_dir / "state" / "sources.json"
        sources_path.write_text(json.dumps({
            "schema": "nta-betta-bau-sources-v1", "dispatcher_owned": True,
            "batch_id": self.batch_id, "selected_at": now_utc(),
            "selected_sources": self.selected,
        }), encoding="utf-8")
        os.chmod(sources_path, 0o444)
        self.budget = betta_budget.GenerationBudget(
            self.batch_dir / "state" / "gen-budget.json", batch_id=self.batch_id)
        if policy_mode == "full":
            data = betta_policy.default_policy()
            data.update(enabled=True, automatic_batch_authorisation=True,
                        paid_generation_authorised=True)
        elif policy_mode == "gated":
            data = betta_policy.default_policy()
        else:
            raise ValueError(policy_mode)
        self.policy = betta_policy.StandingPolicy(data)
        self.registry_path = Path(registry) if registry else self.root / "registry.sqlite3"
        self.telemetry = self.root / f"telemetry-{self.batch_id}.sqlite3"
        self.calls = {"generate": 0, "execute": 0, "archive": 0, "resolve": [],
                      "preflight": 0}
        self.runners = self._make_runners()
        self.adapters = betta_adapters.make_adapters(
            batch_id=self.batch_id, batch_dir=self.batch_dir, intake_dir=self.intake,
            telemetry_db=self.telemetry, policy=self.policy,
            live_shopify=(policy_mode == "full"),
            live_generation=(policy_mode == "full"),
            runners=self.runners, processed_registry=self.registry_path,
            budget=self.budget, selected_sources=self.selected,
        )

    # -- mocked runners ---------------------------------------------------- #
    def _reading(self, source_sha: str, mode: str) -> dict:
        try:
            return self.vision[source_sha][mode]
        except KeyError as exc:
            raise AssertionError(
                f"no mocked {mode} output for {source_sha[:12]}…") from exc

    def _crop_source_sha(self, crop_path) -> str:
        name = Path(crop_path).name
        if "-label" not in name:
            raise AssertionError(f"unexpected label crop name: {name}")
        return name.split("-label", 1)[0]

    def _make_runners(self) -> dict:
        def catalogue(files):
            digest = sha256(files[0])
            return mock_evidence(files, self._reading(digest, "catalogue"), "mock-catalogue")

        def label(files):
            digest = self._crop_source_sha(files[0])
            return mock_evidence(files, self._reading(digest, "label"), "mock-label")

        def vision_preflight(files):
            digest = sha256(files[0])
            return mock_evidence(files, self._reading(digest, "preflight"),
                                 "mock-preflight")

        def vision_prepqa(files):
            digest = sha256(files[0])
            return mock_evidence(files, self._reading(digest, "prepqa"), "mock-prepqa")

        def qa(entry):
            working = entry.get("working_input_sha256") or entry["source_sha256"]
            output = {
                "assertions": {name: "PASS" for name in betta_bau_adapters.QA_ASSERTIONS},
                "overall": "PASS", "reasons": [],
            }
            return {
                "provider": "mock-router", "model": "mock-vision",
                "call_id": f"mock-qa-{entry['tank_id']}", "timestamp": now_utc(),
                "input_hashes": [working, entry["hero_sha256"], entry["source_sha256"]],
                "routing": routing(), "usage": {}, "output": output,
            }

        def generate(argv):
            self.calls["generate"] += 1
            source = Path(argv[argv.index("--source") + 1]).resolve()
            output = Path(argv[argv.index("--output") + 1]).resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"clean-hero")
            return json.dumps({
                "provider": "xai", "model": betta_bau_adapters.GROK_MODEL,
                "timestamp": now_utc(), "source_path": str(source),
                "source_sha256": sha256(source), "output_path": str(output),
                "output_sha256": sha256(output), "grokai_cost": 0.07,
                "grokai_cost_source": "nta_default_0.07",
                "tokens_input": 0, "tokens_output": 0,
            })

        def resolve(entry):
            self.calls["resolve"].append(entry["tank_id"])
            product = self.products.get(entry["tank_id"])
            if product is None:
                return {"status": "AMBIGUOUS"}
            return {"status": "RESOLVED", "product": product}

        def execute(entry, path, digest):
            self.calls["execute"] += 1
            assert (self.batch_dir / "state" / "authority.json").is_file()
            assert digest == sha256(path)
            return {"status": "VERIFIED",
                    "receipt": {"verified_at": now_utc(), "read_back": "PASS"}}

        def archive(state, directory):
            self.calls["archive"] += 1
            return {"status": "ARCHIVED", "batch_status": "COMPLETE"}

        return {
            "catalogue": catalogue, "label": label,
            "vision_preflight": vision_preflight, "vision_prepqa": vision_prepqa,
            "vision_retry_delay_seconds": 0,
            "qa": qa, "generate": generate,
            "render": lambda clean, final, tank, date: Path(final).write_bytes(
                Path(clean).read_bytes() + b"|label|" + tank.encode()),
            "resolve": resolve,
            "preflight": lambda **kwargs: {"status": "PREFLIGHT_PASS"},
            "execute": execute, "archive": archive,
        }

    def run(self) -> dict:
        return betta_process.process_batch(
            self.batch_dir, self.batch_id, adapters=self.adapters, policy=self.policy)

    def state(self) -> dict:
        return json.loads((self.batch_dir / "state" / "process.json").read_text())

    def entry(self) -> dict:
        return next(iter(self.state()["fish"].values()))

    def batch_files_matching(self, needle: str) -> list:
        found = []
        for path in sorted(self.batch_dir.rglob("*")):
            if not path.is_file():
                continue
            if needle in path.name:
                found.append(str(path))
                continue
            if path.suffix in {".json", ".md", ".txt", ".csv"}:
                try:
                    if needle in path.read_text(encoding="utf-8"):
                        found.append(str(path))
                except (OSError, UnicodeDecodeError):
                    continue
        return found


# --------------------------------------------------------------------------- #
# 1. Correct original-image identification (recorded real evidence only)
# --------------------------------------------------------------------------- #
class Category01OriginalImageIdentification(unittest.TestCase):
    """Deterministic assertions over recorded real values; never invented."""

    def load(self, name):
        path = EVAL_DIR / name
        if not path.is_file():
            self.skipTest(f"real-evaluation evidence missing: {path}")
        return json.loads(path.read_text())

    def test_1_fixture_is_byte_immutable_and_bound_to_recorded_shas(self):
        self.assertTrue(INCIDENT_PHOTO.is_file())
        self.assertEqual(sha256(INCIDENT_PHOTO), INCIDENT_SHA)
        summary = self.load("real-run-summary.json")
        self.assertEqual(summary["raw_source"]["sha256_before"], INCIDENT_SHA)
        self.assertEqual(summary["raw_source"]["sha256_after"], INCIDENT_SHA)
        self.assertIs(summary["raw_source"]["unchanged"], True)
        self.assertEqual(summary["fixture"]["sha256"], INCIDENT_SHA)
        self.assertEqual(summary["fixture"]["sha256_after_run"], INCIDENT_SHA)

    def test_1_recorded_real_full_read_identified_tank_2bt23(self):
        receipt = self.load("real-run-catalogue-receipt.json")
        self.assertEqual(receipt["input_hashes"], [INCIDENT_SHA])
        self.assertEqual(receipt["routing"]["execution_attested"], True)
        self.assertTrue(receipt["provider"])
        self.assertTrue(receipt["model"])
        output = receipt["output"]
        # The recorded value itself is asserted (it was genuinely recorded).
        self.assertEqual(label_identity.normalize_tank(output["tank_id"]), "2BT23")
        reading = betta_bau_adapters.StrictBAUAdapters._label_read_values(output)
        self.assertEqual(reading["tank_id"], "2BT23")
        # Recorded date is the model's (mis)read; the pipeline gate made it
        # non-confident, so no accepted identity ever used it.
        self.assertIs(reading["confident"], False)
        self.assertEqual(receipt["uncertain"], True)
        self.assertEqual(receipt["uncertain_reason"], "catalogue confidence below 0.90")

    def test_1_recorded_real_run_quarantined_instead_of_accepting_the_misread(self):
        summary = self.load("real-run-summary.json")
        result = summary["result"]
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["published"], 0)
        self.assertEqual(result["quarantined"], 1)
        self.assertIsNone(result["manifest_sha256"])
        state = self.load("real-run-process-state.json")
        entry = next(iter(state["fish"].values()))
        self.assertEqual(entry["tank_id"], "2BT23")
        self.assertEqual(entry["source_sha256"], INCIDENT_SHA)
        self.assertEqual(entry["status"], "QUARANTINED")
        self.assertEqual(state["executed"], [])
        self.assertEqual(entry["notes"], [
            "focused label read contradicts the catalogue read: "
            "catalogue date 2026-04-10 vs label date 2026-10-14",
        ])


# --------------------------------------------------------------------------- #
# 2. Correct cropped-label identification + deterministic crop lineage
# --------------------------------------------------------------------------- #
class Category02CroppedLabelIdentification(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def test_2_fresh_crop_reproduces_the_recorded_crop_bytes(self):
        record = betta_prepare.label_crop(INCIDENT_PHOTO, self.root / "label.png")
        self.assertEqual(record["source_sha256"], INCIDENT_SHA)
        self.assertEqual(record["source_dimensions"], [1512, 2688])
        self.assertEqual(record["rect_px"], [0, 0, 1512, 477])
        self.assertEqual(record["output_dimensions"], [1512, 477])
        self.assertTrue(record["confident"])
        self.assertEqual(
            record["output_sha256"],
            "b6cbc02721b2071d01fe7e16f48cea2b043842bec7478d45ac8b5f80f12107f1")
        # Two independent real evaluations (A2's and A5's) recorded the same
        # deterministic crop digest for the same source bytes.
        archived = EVAL_DIR / "real-run-label-crop.png"
        if archived.is_file():
            self.assertEqual(sha256(archived), record["output_sha256"])
        a2_crop = A2_EVIDENCE_DIR / "label-crop.png"
        if a2_crop.is_file():
            self.assertEqual(sha256(a2_crop), record["output_sha256"])

    def test_2_recorded_real_crop_read_is_confident_and_correct(self):
        receipt = EVAL_DIR / "real-run-label-retry-receipt.json"
        if not receipt.is_file():
            self.skipTest("real-run label-retry receipt missing")
        record = json.loads(receipt.read_text())
        crop = EVAL_DIR / "real-run-label-crop.png"
        self.assertTrue(crop.is_file())
        crop_sha = sha256(crop)
        self.assertEqual(record["input_hashes"], [crop_sha])
        self.assertEqual(record["crop_identity"]["sha256"], crop_sha)
        self.assertEqual(record["source_identity"]["sha256"], INCIDENT_SHA)
        reading = record["crop_reading"]
        # Recorded by the real focused call: correct tank, correct date, price.
        self.assertEqual(reading["tank_id"], "2BT23")
        self.assertEqual(reading["photo_date"], "2026-10-14")
        self.assertIs(reading["confident"], True)
        self.assertEqual(record["visible_price"], "35")

    def test_2_crop_is_a_deterministic_region_of_the_source(self):
        out1 = self.root / "crop-1.png"
        out2 = self.root / "crop-2.png"
        first = betta_prepare.label_crop(INCIDENT_PHOTO, out1)
        second = betta_prepare.label_crop(INCIDENT_PHOTO, out2)
        comparable = ("source_sha256", "rect_px", "output_sha256",
                      "output_dimensions", "confident", "method")
        self.assertEqual({key: first[key] for key in comparable},
                         {key: second[key] for key in comparable})
        self.assertEqual(out1.read_bytes(), out2.read_bytes())
        with Image.open(INCIDENT_PHOTO) as source:
            expected = source.convert("RGB").crop(tuple(first["rect_px"]))
        with Image.open(out1) as produced:
            self.assertEqual(produced.convert("RGB").tobytes(), expected.tobytes())


# --------------------------------------------------------------------------- #
# 3. Wrong high-confidence identification is quarantined, nothing else happens
# --------------------------------------------------------------------------- #
class Category03WrongHighConfidenceIdentification(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.vision = {
            INCIDENT_SHA: {
                "catalogue": catalogue_output("5BT43", "2026-10-14", 0.98, 0.97),
                "label": label_output("2BT23", "14/10/2026"),
                "preflight": preflight_output("2BT23", "2026-10-14"),
                "prepqa": prepqa_output(),
            }
        }

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, **kwargs):
        return StrictSandbox(self.root / "sandbox", [INCIDENT_PHOTO],
                             self.vision, **kwargs)

    def test_3_adapter_quarantines_the_wrong_high_confidence_full_read(self):
        sandbox = self.make()
        record = sandbox.adapters["intake"](sandbox.batch_dir, {})["fish"][0]
        self.assertEqual(record["sha256"], INCIDENT_SHA)
        decision = sandbox.adapters["identify"](record, sandbox.batch_dir)
        self.assertTrue(decision["quarantine"])
        self.assertEqual(
            decision["quarantine_reason"],
            "label read disagreement: full=5BT43, crop=2BT23")
        reads = decision["label_reads"]
        self.assertEqual(reads["status"], "DISAGREE")
        self.assertIsNone(label_identity.compare_reads(
            {**reads["full"], "confident": True},
            {**reads["crop"], "confident": True})["tank"])
        for side in ("full", "crop"):
            path = Path(reads[side]["receipt_path"])
            self.assertTrue(path.is_file())
            self.assertEqual(reads[side]["receipt_sha256"], sha256(path))
        self.assertEqual(reads["crop"]["crop_sha256"], sha256(
            Path(reads["crop"]["crop_path"])))
        # Both receipts bind the genuine incident source bytes.
        full_receipt = json.loads(Path(reads["full"]["receipt_path"]).read_text())
        self.assertEqual(full_receipt["source_identity"]["sha256"], INCIDENT_SHA)
        crop_receipt = json.loads(Path(reads["crop"]["receipt_path"]).read_text())
        self.assertEqual(crop_receipt["source_identity"]["sha256"], INCIDENT_SHA)
        self.assertEqual(crop_receipt["status"], "DISAGREE")

    def test_3_process_blocks_generation_manifest_and_any_5bt43_mutation(self):
        sandbox = self.make(policy_mode="gated")
        result = sandbox.run()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["published"], 0)
        self.assertEqual(result["quarantined"], 1)
        self.assertIsNone(result["manifest_sha256"])
        # The only paths that could write were never invoked.
        self.assertEqual(sandbox.calls["generate"], 0)
        self.assertEqual(sandbox.calls["execute"], 0)
        self.assertEqual(sandbox.calls["archive"], 0)
        self.assertEqual(sandbox.calls["resolve"], [])
        self.assertFalse((sandbox.batch_dir / "state" / "authority.json").exists())
        self.assertFalse((sandbox.batch_dir / "manifest" / "shopify-production.json").exists())
        state = sandbox.state()
        self.assertEqual(state["executed"], [])
        self.assertIsNone(state["manifest_sha256"])
        # No state record expresses a mutation intent for 5BT43: the string only
        # appears inside recorded disagreement evidence (label receipts / process
        # state), never in a manifest or a Shopify uploader state record.
        mentions = sandbox.batch_files_matching("5BT43")
        self.assertTrue(mentions, "the disagreement evidence should mention 5BT43")
        for path in mentions:
            parts = Path(path).parts
            self.assertNotIn("manifest", parts)
            self.assertNotIn("shopify", parts)
        entry = sandbox.entry()
        self.assertEqual(entry["status"], "QUARANTINED")
        self.assertEqual(entry["tank_id"], "5BT43")  # readable, never accepted
        self.assertTrue(entry["uncertain"])
        self.assertNotIn("shopify_receipt", entry)


# --------------------------------------------------------------------------- #
# 4. Wrong photograph date is quarantined
# --------------------------------------------------------------------------- #
class Category04WrongPhotographDate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.vision = {
            INCIDENT_SHA: {
                "catalogue": catalogue_output("2BT23", "2026-10-14", 0.99, 0.95),
                "label": label_output("2BT23", "9/10/2026"),
                "preflight": preflight_output("2BT23", "2026-10-14"),
                "prepqa": prepqa_output(),
            }
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_4_date_only_disagreement_quarantines_at_the_adapter(self):
        sandbox = StrictSandbox(self.root / "sandbox", [INCIDENT_PHOTO], self.vision)
        record = sandbox.adapters["intake"](sandbox.batch_dir, {})["fish"][0]
        decision = sandbox.adapters["identify"](record, sandbox.batch_dir)
        self.assertTrue(decision["quarantine"])
        self.assertEqual(
            decision["quarantine_reason"],
            "label read disagreement: full=2BT23, crop=2BT23; "
            "date full=2026-10-14, crop=2026-10-09")
        reads = decision["label_reads"]
        self.assertEqual(reads["status"], "DISAGREE")
        verdict = label_identity.compare_reads(reads["full"], reads["crop"])
        self.assertEqual(verdict["status"], "DISAGREE")
        self.assertIsNone(verdict["tank"])
        self.assertIsNone(verdict["date"])

    def test_4_process_never_publishes_a_wrong_date(self):
        sandbox = StrictSandbox(self.root / "sandbox2", [INCIDENT_PHOTO], self.vision)
        result = sandbox.run()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["quarantined"], 1)
        self.assertEqual(sandbox.calls["generate"], 0)
        self.assertEqual(sandbox.calls["execute"], 0)
        self.assertEqual(sandbox.calls["archive"], 0)
        self.assertFalse((sandbox.batch_dir / "state" / "authority.json").exists())
        entry = sandbox.entry()
        # The readable full read is retained for evidence only; nothing was
        # accepted and the contradiction is the recorded quarantine note.
        self.assertEqual(entry["photo_date"], "2026-10-14")
        self.assertEqual(entry["status"], "QUARANTINED")
        self.assertEqual(entry["notes"], [
            "label read disagreement: full=2BT23, crop=2BT23; "
            "date full=2026-10-14, crop=2026-10-09"])
        self.assertIsNone(result["manifest_sha256"])

    def test_4_nearby_dates_and_tanks_are_never_equated(self):
        self.assertNotEqual(label_identity.normalize_date("14/10/2026"),
                            label_identity.normalize_date("9/10/2026"))
        self.assertEqual(label_identity.normalize_date("14/10/2026"), "2026-10-14")
        self.assertEqual(label_identity.normalize_date("9/10/2026"), "2026-10-09")
        self.assertNotEqual(label_identity.normalize_tank("2BT23"),
                            label_identity.normalize_tank("5BT43"))
        verdict = label_identity.compare_reads(
            {"tank_id": "2BT23", "photo_date": "2026-10-14", "confident": True},
            {"tank_id": "2BT23", "photo_date": "2026-10-09", "confident": True})
        self.assertEqual(verdict["status"], "DISAGREE")
        self.assertIsNone(verdict["tank"])
        self.assertIsNone(verdict["date"])


# --------------------------------------------------------------------------- #
# 5. Disagreement / INCOMPLETE handling (mirrors the tested pipeline semantics)
# --------------------------------------------------------------------------- #
class Category05DisagreementAndIncomplete(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def sandbox(self, name, vision):
        return StrictSandbox(self.root / name, [INCIDENT_PHOTO], vision)

    def test_5_not_confident_crop_leaves_the_confident_full_read_in_force(self):
        sandbox = self.sandbox("incomplete-crop", {
            INCIDENT_SHA: {
                "catalogue": catalogue_output("2BT23", "2026-10-14", 0.98, 0.96),
                "label": label_output("2BT23", "14/10/2026", tank_conf=0.80),
                "preflight": preflight_output("2BT23", "2026-10-14"),
                "prepqa": prepqa_output(),
            }
        })
        record = sandbox.adapters["intake"](sandbox.batch_dir, {})["fish"][0]
        decision = sandbox.adapters["identify"](record, sandbox.batch_dir)
        self.assertFalse(decision["uncertain"])
        self.assertFalse(decision["quarantine"])
        self.assertEqual(decision["tank_id"], "2BT23")
        self.assertEqual(decision["photo_date"], "2026-10-14")
        self.assertEqual(decision["label_reads"]["status"], "INCOMPLETE")
        self.assertIs(decision["label_reads"]["crop"]["confident"], False)
        receipt = json.loads(
            Path(decision["label_reads"]["crop"]["receipt_path"]).read_text())
        self.assertEqual(receipt["status"], "INCOMPLETE")
        self.assertEqual(receipt["source_identity"]["sha256"], INCIDENT_SHA)

    def test_5_uncertain_full_read_recovers_via_agreeing_crop_read(self):
        sandbox = self.sandbox("retry-accept", {
            INCIDENT_SHA: {
                "catalogue": catalogue_output("2BT23", "2026-10-14", 0.88, 0.96),
                "label": label_output("2BT23", "14/10/2026"),
                "preflight": preflight_output("2BT23", "2026-10-14"),
                "prepqa": prepqa_output(),
            }
        })
        result = sandbox.run()
        entry = sandbox.entry()
        self.assertEqual(entry["tank_id"], "2BT23")
        self.assertEqual(entry["photo_date"], "2026-10-14")
        self.assertEqual(entry["label_reads"]["status"], "RETRY_ACCEPTED")
        self.assertIs(entry["uncertain"], False)
        # Documented accept behaviour: preparation proceeds, then the paid gate
        # stops the run before generation.
        self.assertEqual(result["status"], "AWAITING_AUTHORISATION")
        self.assertEqual(sandbox.calls["generate"], 0)

    def test_5_uncertain_full_read_with_contradicting_crop_stays_quarantined(self):
        sandbox = self.sandbox("retry-conflict", {
            INCIDENT_SHA: {
                "catalogue": catalogue_output("2BT23", "2026-04-10", 0.88, 0.96),
                "label": label_output("2BT23", "14/10/2026"),
                "preflight": preflight_output("2BT23", "2026-10-14"),
                "prepqa": prepqa_output(),
            }
        })
        result = sandbox.run()
        entry = sandbox.entry()
        self.assertEqual(entry["status"], "QUARANTINED")
        self.assertEqual(entry["label_reads"]["status"], "RETRY_CONFLICT")
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["published"], 0)
        self.assertEqual(sandbox.calls["generate"], 0)
        self.assertEqual(sandbox.calls["execute"], 0)
        self.assertEqual(sandbox.calls["archive"], 0)

    def test_5_comparator_matrix_is_pinned(self):
        read = lambda tank, date, confident=True: {
            "tank_id": tank, "photo_date": date, "confident": confident}

        def verdict(full, crop):
            return label_identity.compare_reads(full, crop)

        agreeing = verdict(read("2BT23", "2026-10-14"), read("2BT23", "2026-10-14"))
        self.assertEqual(agreeing["status"], "AGREE")
        self.assertEqual(agreeing["tank"], "2BT23")
        self.assertEqual(agreeing["date"], "2026-10-14")
        for full, crop in (
            (read("5BT43", "2026-10-14"), read("2BT23", "2026-10-14")),
            (read("2BT23", "2026-10-09"), read("2BT23", "2026-10-14")),
            (read("5BT43", "2026-10-09"), read("2BT23", "2026-10-14")),
            (read("2BT23", "2026-10-14", False), read("2BT23", "2026-10-14")),
            (read("2BT23", "2026-10-14"), read("2BT23", "2026-10-14", False)),
            (read("2BT23", "2026-10-14", False), read("2BT23", "2026-10-14", False)),
            ({}, read("2BT23", "2026-10-14")),
        ):
            result = verdict(full, crop)
            self.assertIn(result["status"], {"DISAGREE", "INCOMPLETE"})
            self.assertIsNone(result["tank"])
            self.assertIsNone(result["date"])
        # Not-confident on exactly one side is INCOMPLETE even if values match.
        self.assertEqual(verdict(read("2BT23", "2026-10-14", False),
                                 read("2BT23", "2026-10-14"))["status"], "INCOMPLETE")


# --------------------------------------------------------------------------- #
# 6. Owner-requested tank differs from model-detected tank
# --------------------------------------------------------------------------- #
def rebrand_fixture(fixture, mapping):
    """Rename fixture tanks (files, evidence, manifest) to incident numbers."""
    replacements = []
    for old, new in mapping.items():
        replacements.extend([(old, new), (old.lower(), new.lower())])
    for path in sorted(fixture.root.iterdir()):
        if path.is_file():
            name = path.name
            for old, new in replacements:
                name = name.replace(old, new)
            if name != path.name:
                path.rename(fixture.root / name)
    manifest = json.loads(fixture.manifest_path.read_text(encoding="utf-8"))
    for record in manifest["evidence"].values():
        path = Path(record["path"])
        text = path.read_text(encoding="utf-8")
        for old, new in replacements:
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")
        record["sha256"] = sha256(path)
    items_text = json.dumps(fixture.manifest_items, indent=2)
    for old, new in replacements:
        items_text = items_text.replace(old, new)
    manifest["items"] = json.loads(items_text)
    body = json.dumps(manifest, indent=2)
    for old, new in replacements:
        body = body.replace(old, new)
    fixture.manifest_path.write_text(body + "\n", encoding="utf-8")
    fixture.manifest_items = manifest["items"]
    fixture.tanks = list(mapping.values())
    fixture.qa_paths = {
        new: fixture.root / f"{new}-qa.json" for new in mapping.values()
    }
    return fixture


class Category06RequestedDetectedMismatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def mismatched_fixture(self, name="fixture"):
        fixture = rebrand_fixture(ShopifyFixture(self.root / name), {"1BT1": "2BT23"})
        fixture.manifest_items[0]["identity"]["detected_tank"] = "5BT43"
        fixture.rewrite_manifest()
        return fixture

    def test_6_detected_5bt43_requested_2bt23_refused_at_manifest_load(self):
        fixture = self.mismatched_fixture()
        with self.assertRaisesRegex(
                bsb.ManifestError, "without a correction record"):
            bsb.ManifestBundle(fixture.manifest_path)
        self.assertEqual(fixture.manifest_items[0]["identity"], {
            "source_sha256": fixture.manifest_items[0]["original"]["sha256"],
            "detected_tank": "5BT43",
            "requested_tank": "2BT23",
            "accepted_tank": "2BT23",
            "correction_sha256": None,
        })

    def test_6_execute_and_resume_both_refuse_before_any_state_exists(self):
        fixture = self.mismatched_fixture("cli")
        for command in ("execute", "resume"):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = bsb.main([
                    command,
                    "--manifest", str(fixture.manifest_path),
                    "--bridge", str(self.root / "missing-bridge.mjs"),
                ])
            self.assertEqual(code, 2, command)
            self.assertIn("without a correction record", stderr.getvalue())
        self.assertFalse((fixture.root / "state").exists())
        self.assertFalse((fixture.root / "reports").exists())


# --------------------------------------------------------------------------- #
# 7. Prevention of wrong-product writes
# --------------------------------------------------------------------------- #
class Category07WrongProductWritePrevention(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def test_7_blocked_manifest_never_constructs_a_mutation_path(self):
        fixture = rebrand_fixture(ShopifyFixture(self.root / "fixture"), {"1BT1": "2BT23"})
        fixture.manifest_items[0]["identity"]["detected_tank"] = "5BT43"
        fixture.rewrite_manifest()

        class MutationProbe:
            calls = 0

            def __getattr__(self, name):
                MutationProbe.calls += 1
                raise AssertionError(f"mutation path invoked: {name}")

        probe = MutationProbe()
        with self.assertRaises(bsb.ManifestError):
            bundle = bsb.ManifestBundle(fixture.manifest_path)
            bsb.BatchUploader(bundle, probe, bsb.StateStore(bundle))
        self.assertEqual(MutationProbe.calls, 0)
        self.assertFalse((fixture.root / "state").exists(), "no mutation intent recorded")

    def test_7_process_level_wrong_read_cannot_intend_or_perform_a_5bt43_write(self):
        sandbox = StrictSandbox(self.root / "sandbox", [INCIDENT_PHOTO], {
            INCIDENT_SHA: {
                "catalogue": catalogue_output("5BT43", "2026-10-09", 0.99, 0.98),
                "label": label_output("2BT23", "14/10/2026"),
                "preflight": preflight_output("2BT23", "2026-10-14"),
                "prepqa": prepqa_output(),
            }
        })
        result = sandbox.run()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(sandbox.calls["generate"], 0)
        self.assertEqual(sandbox.calls["execute"], 0)
        self.assertEqual(sandbox.calls["resolve"], [])
        state = sandbox.state()
        self.assertEqual(state["executed"], [])
        self.assertNotIn("manifest", state)
        self.assertIsNone(state["manifest_sha256"])
        shop_state = sandbox.batch_dir / "state" / "shopify"
        self.assertFalse(shop_state.exists())
        # Every 5BT43 mention lives in quarantine evidence, never in a manifest
        # or a Shopify state record.
        mentions = sandbox.batch_files_matching("5BT43")
        self.assertTrue(mentions)
        for path in mentions:
            parts = Path(path).parts
            self.assertNotIn("manifest", parts)
            self.assertNotIn("shopify", parts)


# --------------------------------------------------------------------------- #
# 8. Owner correction with exact source binding
# --------------------------------------------------------------------------- #
class Category08OwnerCorrection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def corrected_fixture(self, name="fixture"):
        fixture = rebrand_fixture(
            ShopifyFixture(self.root / name, authorised=True), {"1BT1": "2BT23"})
        path, record = fixture.install_correction(
            "2BT23", original_model_tank="5BT43")
        return fixture, path, record

    def test_8_valid_correction_allows_the_manifest(self):
        fixture, path, record = self.corrected_fixture()
        bundle = bsb.ManifestBundle(fixture.manifest_path)
        identity = bundle.contexts["2BT23"].raw["identity"]
        self.assertEqual(identity["detected_tank"], "5BT43")
        self.assertEqual(identity["requested_tank"], "2BT23")
        self.assertEqual(identity["accepted_tank"], "2BT23")
        self.assertEqual(identity["correction_sha256"], record["correction_sha256"])

    def test_8_correction_record_is_immutable_with_full_audit_fields(self):
        _, path, record = self.corrected_fixture()
        mode = os.stat(path).st_mode & 0o777
        self.assertEqual(mode, 0o444)
        core = {key: value for key, value in record.items()
                if key != "correction_sha256"}
        self.assertEqual(corrections.json_sha256(core), record["correction_sha256"])
        self.assertEqual(record["schema"], "nta-betta-owner-correction-v1")
        self.assertEqual(record["source_sha256"],
                         sha256(Path(json.loads(
                             (path.parent.parent / "manifest.json").read_text()
                         )["items"][0]["original"]["path"])))
        self.assertEqual(record["original_model_tank"], "5BT43")
        self.assertEqual(record["corrected_tank"], "2BT23")
        self.assertTrue(record["product_id"].startswith("gid://shopify/Product/"))
        self.assertEqual(sorted(corrections.scope_fields(record["operation"])),
                         sorted(bsb.IDENTITY_OPERATION_FIELDS))
        self.assertEqual(record["operator"], "owner")
        self.assertTrue(record["reason"])
        self.assertTrue(record["evidence_reference"])
        self.assertTrue(record["created_at"])

    def test_8_mocked_execute_succeeds_for_the_corrected_item(self):
        fixture, _, _ = self.corrected_fixture("execute")
        bundle = bsb.ManifestBundle(fixture.manifest_path)
        contexts = bundle.select()
        gateway = FakeGateway(contexts)
        state = bsb.StateStore(bundle)
        uploader = bsb.BatchUploader(
            bundle, gateway, state, sleep=lambda _: None,
            upload=lambda target, asset: None, poll_attempts=5, poll_interval=0)
        report = uploader.execute(contexts)
        self.assertEqual(report["verified_count"], 1)
        self.assertEqual(report["blocked_count"], 0)
        self.assertEqual(state.item("2BT23")["stage"], "VERIFIED")
        receipt = Path(state.item("2BT23")["final_receipt"])
        self.assertEqual(json.loads(receipt.read_text())["status"],
                         "FINAL_SHOPIFY_READBACK_PASS")


# --------------------------------------------------------------------------- #
# 9. Correction reuse for another image or product is refused
# --------------------------------------------------------------------------- #
class Category09CorrectionReuseRefusal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def valid_record(self):
        fixture = rebrand_fixture(
            ShopifyFixture(self.root / "fixture", count=2), {"1BT1": "2BT23",
                                                             "1BT2": "5BT43"})
        item = next(value for value in fixture.manifest_items
                    if value["tank_id"] == "2BT23")
        path = corrections.record(
            source_sha256=item["original"]["sha256"],
            original_model_tank="5BT43", corrected_tank="2BT23",
            product_id=item["product_id"], variant_id=item["variant_id"],
            operation={"fields": list(bsb.IDENTITY_OPERATION_FIELDS),
                       "mode": "owner-directed"},
            reason="owner corrected the vision tank reading",
            evidence_reference="incident-2026-10-15-photo",
            operator="owner", directory=fixture.root / "corrections",
            created_at="2026-10-15T00:00:00+00:00",
        )
        return fixture, path, json.loads(path.read_text())

    def test_9_reuse_for_another_image_product_or_tank_is_invalid(self):
        fixture, path, record = self.valid_record()
        item = next(value for value in fixture.manifest_items
                    if value["tank_id"] == "2BT23")
        baseline = corrections.validate_correction(
            path, source_sha256=item["original"]["sha256"],
            requested_tank="2BT23", accepted_tank="2BT23",
            product_id=item["product_id"],
            operation_fields=list(bsb.IDENTITY_OPERATION_FIELDS))
        self.assertEqual(baseline, {"valid": True, "reason": "ok"})
        # Another image (the archived 5BT43 photo) must fail.
        verdict = corrections.validate_correction(
            path, source_sha256=NEAR_CONFUSION_SHA,
            requested_tank="2BT23", accepted_tank="2BT23",
            product_id=item["product_id"],
            operation_fields=list(bsb.IDENTITY_OPERATION_FIELDS))
        self.assertEqual(verdict, {"valid": False, "reason": "source_sha256_mismatch"})
        # Another product must fail.
        other = next(value for value in fixture.manifest_items
                     if value["tank_id"] == "5BT43")
        verdict = corrections.validate_correction(
            path, source_sha256=item["original"]["sha256"],
            requested_tank="2BT23", accepted_tank="2BT23",
            product_id=other["product_id"],
            operation_fields=list(bsb.IDENTITY_OPERATION_FIELDS))
        self.assertEqual(verdict, {"valid": False, "reason": "product_id_mismatch"})
        # Another requested tank must fail.
        verdict = corrections.validate_correction(
            path, source_sha256=item["original"]["sha256"],
            requested_tank="5BT43", accepted_tank="2BT23",
            product_id=item["product_id"],
            operation_fields=list(bsb.IDENTITY_OPERATION_FIELDS))
        self.assertEqual(verdict, {"valid": False, "reason": "requested_tank_mismatch"})

    def test_9_manifest_binding_the_record_to_another_item_is_refused(self):
        fixture, path, record = self.valid_record()
        other = next(value for value in fixture.manifest_items
                     if value["tank_id"] == "5BT43")
        other["identity"]["correction_sha256"] = record["correction_sha256"]
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(bsb.ManifestError, "source_sha256_mismatch"):
            bsb.ManifestBundle(fixture.manifest_path)


# --------------------------------------------------------------------------- #
# 10. Duplicate image hashes (the two byte-identical uploads)
# --------------------------------------------------------------------------- #
class Category10DuplicateHashes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def test_10_the_two_uploads_are_byte_identical(self):
        self.assertEqual(sha256(INCIDENT_PHOTO), INCIDENT_SHA)
        self.assertEqual(sha256(INCIDENT_PHOTO_SECOND), INCIDENT_SHA)
        self.assertEqual(INCIDENT_PHOTO.read_bytes(), INCIDENT_PHOTO_SECOND.read_bytes())

    def test_10_processed_registry_dedupes_the_repeat_upload(self):
        registry = betta_watch.ProcessedRegistry(self.root / "processed.sqlite3")
        registry.record(INCIDENT_SHA, "batch-1")
        registry.record(INCIDENT_SHA, "batch-2")  # byte-identical repeat upload
        con = sqlite3.connect(self.root / "processed.sqlite3")
        try:
            rows = con.execute(
                "SELECT source_sha256, batch_id FROM processed").fetchall()
        finally:
            con.close()
        self.assertEqual(rows, [(INCIDENT_SHA, "batch-1")])
        self.assertEqual(registry.hashes(), {INCIDENT_SHA})

    def test_10_stable_intake_scan_excludes_the_already_processed_hash(self):
        intake = self.root / "intake"
        intake.mkdir()
        copy = intake / "second-copy.png"
        shutil.copy2(INCIDENT_PHOTO_SECOND, copy)
        os.utime(copy, (1, 1))
        found = betta_watch.scan(intake, now=100.0, settle_seconds=20.0)
        self.assertEqual([value["sha256"] for value in found], [INCIDENT_SHA])
        again = betta_watch.scan(intake, now=100.0, settle_seconds=20.0,
                                 known_hashes={INCIDENT_SHA})
        self.assertEqual(again, [])

    def test_10_strict_intake_refuses_duplicate_selected_content(self):
        intake = self.root / "intake"
        intake.mkdir()
        first = intake / "incident-photo.png"
        second = intake / "incident-photo-second-upload.png"
        shutil.copy2(INCIDENT_PHOTO, first)
        shutil.copy2(INCIDENT_PHOTO_SECOND, second)
        selected = [{"path": str(path), "sha256": sha256(path),
                     "size": path.stat().st_size} for path in (first, second)]
        batch = betta_batches.create_batch(self.root / "batches", label="dupes")
        sources = Path(batch["path"]) / "state" / "sources.json"
        sources.write_text(json.dumps({
            "schema": "nta-betta-bau-sources-v1", "dispatcher_owned": True,
            "batch_id": batch["batch_id"], "selected_at": now_utc(),
            "selected_sources": selected,
        }), encoding="utf-8")
        os.chmod(sources, 0o444)
        budget = betta_budget.GenerationBudget(
            Path(batch["path"]) / "state" / "gen-budget.json",
            batch_id=batch["batch_id"])
        adapters = betta_adapters.make_adapters(
            batch_id=batch["batch_id"], batch_dir=Path(batch["path"]),
            intake_dir=intake, telemetry_db=self.root / "telemetry.sqlite3",
            policy=betta_policy.StandingPolicy(), live_shopify=False,
            live_generation=False, runners={}, budget=budget,
            selected_sources=selected)
        with self.assertRaisesRegex(
                betta_bau_adapters.StrictAdapterError, "duplicated"):
            adapters["intake"](Path(batch["path"]), {})

    def test_10_identity_block_binds_this_source_sha_exactly_once(self):
        sandbox = StrictSandbox(self.root / "sandbox", [INCIDENT_PHOTO], {
            INCIDENT_SHA: {
                "catalogue": catalogue_output("2BT23", "2026-10-14"),
                "label": label_output("2BT23", "14/10/2026"),
                "preflight": preflight_output("2BT23", "2026-10-14"),
                "prepqa": prepqa_output(),
            }
        }, policy_mode="full")
        result = sandbox.run()
        self.assertEqual(result["status"], "COMPLETE")
        manifest = json.loads(
            (sandbox.batch_dir / "manifest" / "shopify-production.json").read_text())
        self.assertEqual(len(manifest["items"]), 1)
        item = manifest["items"][0]
        self.assertEqual(item["identity"]["source_sha256"], INCIDENT_SHA)
        self.assertEqual(item["original"]["sha256"], INCIDENT_SHA)
        self.assertEqual(item["identity"]["detected_tank"], "2BT23")
        self.assertEqual(item["identity"]["requested_tank"], "2BT23")
        self.assertEqual(item["identity"]["accepted_tank"], "2BT23")
        state = sandbox.state()
        self.assertEqual(len(state["fish"]), 1)
        # One source hash, one identity, one execution.
        self.assertEqual(state["executed"], list(state["fish"].keys()))
        con = sqlite3.connect(sandbox.registry_path)
        try:
            rows = con.execute(
                "SELECT source_sha256, batch_id FROM processed").fetchall()
        finally:
            con.close()
        self.assertEqual(rows, [(INCIDENT_SHA, sandbox.batch_id)])


# --------------------------------------------------------------------------- #
# 11. Incorrect attribution of a source hash is refused
# --------------------------------------------------------------------------- #
class Category11SourceHashAttribution(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.vision = {
            INCIDENT_SHA: {
                "catalogue": catalogue_output("2BT23", "2026-10-14"),
                "label": label_output("2BT23", "14/10/2026"),
                "preflight": preflight_output("2BT23", "2026-10-14"),
                "prepqa": prepqa_output(),
            }
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_11_identity_source_sha_must_match_the_camera_original(self):
        fixture = rebrand_fixture(
            ShopifyFixture(self.root / "fixture"), {"1BT1": "2BT23"})
        fixture.manifest_items[0]["identity"]["source_sha256"] = "a" * 64
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(
                bsb.ManifestError, "identity source hash differs"):
            bsb.ManifestBundle(fixture.manifest_path)

    def tamper(self, fixture, path, mutate):
        os.chmod(path, 0o644)
        record = json.loads(Path(path).read_text())
        mutate(record)
        Path(path).write_text(json.dumps(record), encoding="utf-8")

    def test_11_catalogue_receipt_with_wrong_source_lineage_is_refused(self):
        sandbox = StrictSandbox(self.root / "sandbox", [INCIDENT_PHOTO], self.vision)
        record = sandbox.adapters["intake"](sandbox.batch_dir, {})["fish"][0]
        decision = sandbox.adapters["identify"](record, sandbox.batch_dir)
        receipt_path = decision["catalogue_evidence_path"]
        self.tamper(sandbox, receipt_path,
                    lambda value: value["source_identity"].update(
                        sha256="b" * 64))
        with self.assertRaisesRegex(
                betta_bau_adapters.StrictAdapterError,
                "call receipt does not bind this batch/source identity"):
            sandbox.adapters["identify"](record, sandbox.batch_dir)

    def test_11_label_receipt_with_wrong_source_lineage_is_refused(self):
        sandbox = StrictSandbox(self.root / "sandbox2", [INCIDENT_PHOTO], self.vision)
        record = sandbox.adapters["intake"](sandbox.batch_dir, {})["fish"][0]
        decision = sandbox.adapters["identify"](record, sandbox.batch_dir)
        receipt_path = decision["label_reads"]["crop"]["receipt_path"]
        self.tamper(sandbox, receipt_path,
                    lambda value: value["source_identity"].update(
                        sha256="c" * 64))
        with self.assertRaisesRegex(
                betta_bau_adapters.StrictAdapterError,
                "label corroboration receipt does not bind this batch/source"):
            sandbox.adapters["identify"](record, sandbox.batch_dir)


# --------------------------------------------------------------------------- #
# 12. Model assertions contradicting the actual image evidence (recorded only)
# --------------------------------------------------------------------------- #
class Category12RecordedModelEvidence(unittest.TestCase):
    """Uses A2's RECORDED real outputs; no confidence is invented."""

    def recorded(self):
        full_path = A2_EVIDENCE_DIR / "full-read.json"
        crop_path = A2_EVIDENCE_DIR / "label-read.json"
        if not (full_path.is_file() and crop_path.is_file()):
            self.skipTest("A2 recorded outputs not present")
        full = json.loads(full_path.read_text())
        crop = json.loads(crop_path.read_text())
        self.assertEqual(full["input_hashes"], [INCIDENT_SHA])
        return full, crop

    def gated(self, record):
        return betta_bau_adapters.StrictBAUAdapters._label_read_values(record["output"])

    def test_12_recorded_wrong_date_cannot_pass_the_confidence_gate(self):
        full, crop = self.recorded()
        full_reading = self.gated(full)
        # The recorded full read: correct tank, WRONG date at 0.76 confidence.
        self.assertEqual(full_reading["tank_id"], "2BT23")
        self.assertEqual(full_reading["photo_date"], "2026-04-10")
        self.assertLess(full["output"]["date_confidence"], 0.90)
        self.assertIs(full_reading["confident"], False)
        crop_reading = self.gated(crop)
        self.assertEqual(crop_reading["tank_id"], "2BT23")
        self.assertEqual(crop_reading["photo_date"], "2026-10-14")
        self.assertIs(crop_reading["confident"], True)

    def test_12_comparator_never_emits_agree_for_the_recorded_pair(self):
        full, crop = self.recorded()
        gated = label_identity.compare_reads(self.gated(full), self.gated(crop))
        self.assertEqual(gated["status"], "INCOMPLETE")
        self.assertIsNone(gated["tank"])
        self.assertIsNone(gated["date"])
        # Even if the low-confidence date were forced through, the comparator
        # must DISAGREE on the recorded date values - never AGREE.
        forced = dict(self.gated(full), confident=True)
        verdict = label_identity.compare_reads(forced, self.gated(crop))
        self.assertEqual(verdict["status"], "DISAGREE")
        self.assertIsNone(verdict["tank"])
        self.assertIsNone(verdict["date"])
        self.assertTrue(any("date mismatch" in reason for reason in verdict["reasons"]))
        self.assertNotEqual(full["output"]["photo_date"],
                            crop["output"]["photo_date"])

    def test_12_real_run_reached_the_same_class_of_result(self):
        receipt = EVAL_DIR / "real-run-catalogue-receipt.json"
        if not receipt.is_file():
            self.skipTest("A5 real-run receipt missing")
        recorded = json.loads(receipt.read_text())
        reading = self.gated(recorded)
        self.assertEqual(reading["tank_id"], "2BT23")
        self.assertIs(reading["confident"], False)
        self.assertLess(recorded["output"]["date_confidence"], 0.90)
        self.assertNotEqual(reading["photo_date"], "2026-10-14")


# --------------------------------------------------------------------------- #
# 13. Recovery after an interrupted mutation (uploader resume)
# --------------------------------------------------------------------------- #
class Category13InterruptedMutationResume(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def interrupted(self):
        fixture = rebrand_fixture(
            ShopifyFixture(self.root / "fixture", authorised=True), {"1BT1": "2BT23"})
        bundle = bsb.ManifestBundle(fixture.manifest_path)
        contexts = bundle.select()
        gateway = FakeGateway(contexts)
        gateway.uncertain_operation = "betta_batch_update_details"
        gateway.uncertain_applies = True  # bridge applied it; transport died
        state = bsb.StateStore(bundle)
        uploader = bsb.BatchUploader(
            bundle, gateway, state, sleep=lambda _: None,
            upload=lambda target, asset: None, poll_attempts=5, poll_interval=0)
        return fixture, bundle, contexts, gateway, state, uploader

    def test_13_resume_completes_exactly_once_after_mid_sequence_death(self):
        fixture, bundle, contexts, gateway, state, uploader = self.interrupted()
        report = uploader.execute(contexts)
        item = report["items"][0]
        self.assertEqual(item["status"], "PENDING_RECONCILIATION")
        pending = state.item("2BT23")["pending_mutation"]
        self.assertIsInstance(pending, dict)
        self.assertEqual(pending["operation"], "betta_batch_update_details")
        self.assertEqual(pending["status"], "UNCERTAIN")
        writes_before_resume = list(gateway.writes)
        self.assertIn("betta_batch_update_details",
                      [operation for operation, _ in writes_before_resume])

        resumed = uploader.resume(contexts, live_enabled=True)
        self.assertEqual(resumed["mode"], "RECONCILE_ONLY")
        self.assertIs(resumed["shopify_writes_performed"], False)
        self.assertEqual(resumed["items"][0]["status"], "RECONCILED_APPLIED")
        self.assertEqual(gateway.writes, writes_before_resume)  # no replay

        finished = uploader.resume(contexts, live_enabled=True)
        self.assertEqual(finished["command"], "execute")
        self.assertEqual(finished["verified_count"], 1)
        self.assertEqual(state.item("2BT23")["stage"], "VERIFIED")
        operations = [operation for operation, _ in gateway.writes]
        self.assertEqual(operations.count("betta_batch_update_details"), 1)
        self.assertEqual(operations.count("betta_batch_set_inventory"), 1)
        self.assertEqual(len(operations), len(set(operations)))
        journal = state.item("2BT23")["mutation_history"]
        details = [entry for entry in journal
                   if entry["operation"] == "betta_batch_update_details"]
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["status"], "RECONCILED_APPLIED")
        self.assertEqual(details[0]["summary"], {"fresh_readback": True})

    def test_13_identity_gate_remains_active_during_resume(self):
        fixture, bundle, contexts, gateway, state, uploader = self.interrupted()
        uploader.execute(contexts)
        pending_before = state.item("2BT23")["pending_mutation"]
        self.assertEqual(pending_before["operation"], "betta_batch_update_details")
        gateway.live[contexts[0].product_id]["price"] = "99.00"
        with self.assertRaisesRegex(bsb.BatchError, "protected price changed"):
            uploader.resume(contexts, live_enabled=True)
        pending_after = state.item("2BT23")["pending_mutation"]
        self.assertEqual(pending_after["intent_id"], pending_before["intent_id"])
        self.assertEqual(pending_after["status"], "UNCERTAIN")


# --------------------------------------------------------------------------- #
# 14. Independent Shopify read-back
# --------------------------------------------------------------------------- #
class Category14ShopifyReadBack(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def test_14_verify_reports_a_fresh_readback_with_full_evidence(self):
        fixture = rebrand_fixture(
            ShopifyFixture(self.root / "fixture", authorised=True), {"1BT1": "2BT23"})
        bundle = bsb.ManifestBundle(fixture.manifest_path)
        contexts = bundle.select()
        gateway = FakeGateway(contexts)
        state = bsb.StateStore(bundle)
        uploader = bsb.BatchUploader(
            bundle, gateway, state, sleep=lambda _: None,
            upload=lambda target, asset: None, poll_attempts=5, poll_interval=0)
        written = uploader.execute(contexts)
        self.assertEqual(written["verified_count"], 1)
        reads_after_write = gateway.reads
        report = uploader.verify(contexts)
        self.assertEqual(report["command"], "verify")
        self.assertEqual(report["mode"], "READ_ONLY")
        self.assertEqual(report["manifest_sha256"], bundle.sha256)
        item = report["items"][0]
        self.assertEqual(item["status"], "FINAL_SHOPIFY_READBACK_PASS")
        self.assertGreater(gateway.reads, reads_after_write)  # fresh read
        assertions = item["assertions"]
        self.assertTrue(assertions)
        for name, value in assertions.items():
            self.assertEqual(set(value), {"status", "expected", "actual"}, name)
            self.assertEqual(value["status"], "PASS", name)
        self.assertEqual(assertions["fresh_source"]["actual"], "FRESH_SHOPIFY_READ")
        for field in ("price", "cost", "vendor"):
            self.assertEqual(assertions[field]["status"], "PASS")
        self.assertEqual(assertions["price"]["expected"], "35.00")
        self.assertEqual(assertions["cost"]["expected"], "7.15")
        self.assertEqual(assertions["vendor"]["expected"], "NTA Imports")
        receipt = json.loads(Path(state.item("2BT23")["final_receipt"]).read_text())
        self.assertEqual(receipt["status"], "FINAL_SHOPIFY_READBACK_PASS")


# --------------------------------------------------------------------------- #
# 15. Autonomous quarantine of unresolved cases
# --------------------------------------------------------------------------- #
class Category15AutonomousQuarantine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def test_15_disagreement_is_partial_with_one_terminal_summary(self):
        sandbox = StrictSandbox(self.root / "sandbox", [INCIDENT_PHOTO], {
            INCIDENT_SHA: {
                "catalogue": catalogue_output("5BT43", "2026-10-09", 0.99, 0.98),
                "label": label_output("2BT23", "14/10/2026"),
                "preflight": preflight_output("2BT23", "2026-10-14"),
                "prepqa": prepqa_output(),
            }
        }, policy_mode="full")
        result = sandbox.run()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["quarantined"], 1)
        self.assertEqual(result["published"], 0)
        self.assertEqual(sandbox.calls["execute"], 0)
        self.assertEqual(sandbox.calls["archive"], 0)
        self.assertFalse((sandbox.batch_dir / "state" / "authority.json").exists())
        self.assertFalse(
            (sandbox.batch_dir / "manifest" / "shopify-production.json").exists())
        state = sandbox.state()
        self.assertEqual(state["status"], "PARTIAL")
        self.assertEqual(state["stage"], "SHOPIFY_RESOLVED")
        events = [item for item in state["log"]
                  if item.get("event") == "label_read_disagreement"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["tank_id"], "5BT43")
        # A second run is inert and returns the single persisted terminal result.
        frozen = dict(result)
        second = sandbox.run()
        self.assertEqual(second, frozen)
        self.assertEqual(sandbox.calls["execute"], 0)
        self.assertEqual(sandbox.calls["archive"], 0)

    def test_15_incomplete_identity_is_quarantined_not_published(self):
        sandbox = StrictSandbox(self.root / "sandbox2", [INCIDENT_PHOTO], {
            INCIDENT_SHA: {
                "catalogue": catalogue_output("2BT23", "2026-10-14", 0.70, 0.60,
                                              fish_name=""),
                "label": label_output("2BT23", "14/10/2026", tank_conf=0.50),
                "preflight": preflight_output("2BT23", "2026-10-14"),
                "prepqa": prepqa_output(),
            }
        }, policy_mode="full")
        result = sandbox.run()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["quarantined"], 1)
        self.assertEqual(result["published"], 0)
        self.assertEqual(sandbox.calls["execute"], 0)
        self.assertEqual(sandbox.calls["archive"], 0)
        self.assertFalse((sandbox.batch_dir / "state" / "authority.json").exists())


# --------------------------------------------------------------------------- #
# 16. Preservation of the original camera file
# --------------------------------------------------------------------------- #
class Category16OriginalPreservation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def test_16_real_eval_preserved_the_raw_and_used_a_distinct_working_file(self):
        summary_path = EVAL_DIR / "probe-prep-summary.json"
        if not summary_path.is_file():
            self.skipTest("preparation probe evidence missing")
        summary = json.loads(summary_path.read_text())
        raw = summary["raw_source"]
        self.assertEqual(raw["sha256_before"], INCIDENT_SHA)
        self.assertEqual(raw["sha256_after"], INCIDENT_SHA)
        self.assertIs(raw["unchanged"], True)
        entry = summary["entry"]
        self.assertNotEqual(entry["working_input_path"], raw["path"])
        self.assertNotEqual(entry["working_input_path"], summary["raw_source"]["path"])
        self.assertEqual(entry["working_sha256_recomputed"], entry["working_input_sha256"])
        # The probe's model rejected the prepared image, so the fallback copy is
        # byte-identical to the raw; the file is distinct and the raw is intact.
        self.assertEqual(entry["prep_status"], "FALLBACK_RAW")
        self.assertEqual(entry["working_input_sha256"], INCIDENT_SHA)
        working = Path(entry["working_input_path"])
        if working.is_file():  # the scratch root persists for this session
            self.assertEqual(sha256(working), INCIDENT_SHA)
        self.assertEqual(sha256(INCIDENT_PHOTO), INCIDENT_SHA)

    def test_16_hermetic_manifest_binds_the_raw_original_and_a_derived_working_file(self):
        sandbox = StrictSandbox(self.root / "sandbox", [INCIDENT_PHOTO], {
            INCIDENT_SHA: {
                "catalogue": catalogue_output("2BT23", "2026-10-14"),
                "label": label_output("2BT23", "14/10/2026"),
                "preflight": preflight_output("2BT23", "2026-10-14"),
                "prepqa": prepqa_output(),
            }
        }, policy_mode="full")
        result = sandbox.run()
        self.assertEqual(result["status"], "COMPLETE")
        manifest = json.loads(
            (sandbox.batch_dir / "manifest" / "shopify-production.json").read_text())
        item = manifest["items"][0]
        self.assertEqual(item["original"]["sha256"], INCIDENT_SHA)
        self.assertEqual(item["identity"]["source_sha256"], INCIDENT_SHA)
        source_entry = sandbox.entry()
        self.assertEqual(source_entry["source_sha256"], INCIDENT_SHA)
        # The working image is a distinct prepared derivative, never the original
        # file replaced in place; the original on disk is byte-unchanged.
        self.assertNotEqual(item["working"]["sha256"], INCIDENT_SHA)
        self.assertNotEqual(Path(item["working"]["path"]),
                            Path(item["original"]["path"]))
        self.assertEqual(sha256(Path(item["working"]["path"])),
                         item["working"]["sha256"])
        self.assertEqual(sha256(Path(item["original"]["path"])), INCIDENT_SHA)
        self.assertEqual(sha256(INCIDENT_PHOTO), INCIDENT_SHA)


# --------------------------------------------------------------------------- #
# 17. No unauthorised price/cost/vendor changes
# --------------------------------------------------------------------------- #
class Category17ProtectedFields(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def test_17_protected_mechanics_cover_price_cost_vendor(self):
        for field in ("price", "cost", "vendor"):
            self.assertIn(field, bsb.PROTECTED_FIELDS)
        for field in ("retail_price", "cost", "vendor"):
            self.assertIn(field, betta_policy.DEFAULT_PROTECTED_FIELDS)
        self.assertEqual(tuple(bsb.IDENTITY_OPERATION_FIELDS),
                         ("title", "arrival_date", "inventory", "media"))
        for field in ("price", "cost", "vendor"):
            self.assertNotIn(field, bsb.IDENTITY_OPERATION_FIELDS)

    def test_17_merch_scope_only_correction_cannot_authorise_betta_operations(self):
        fixture = rebrand_fixture(
            ShopifyFixture(self.root / "fixture"), {"1BT1": "2BT23"})
        item = fixture.manifest_items[0]
        product_id = item["product_id"]
        variant_id = item["variant_id"]
        path = corrections.record(
            source_sha256=item["original"]["sha256"],
            original_model_tank="5BT43", corrected_tank="2BT23",
            product_id=product_id, variant_id=variant_id,
            operation={"fields": ["price", "cost", "vendor"],
                       "mode": "owner-directed"},
            reason="owner asked for a merch-only correction",
            evidence_reference="incident-2026-10-15-photo",
            operator="owner", directory=fixture.root / "corrections",
            created_at="2026-10-15T00:00:00+00:00",
        )
        record = json.loads(path.read_text())
        # Direct validation: the merch-only scope does not cover the Betta
        # operation fields the uploader would perform.
        verdict = corrections.validate_correction(
            path, source_sha256=item["original"]["sha256"],
            requested_tank="2BT23", accepted_tank="2BT23",
            product_id=product_id,
            operation_fields=list(bsb.IDENTITY_OPERATION_FIELDS))
        self.assertEqual(verdict, {"valid": False,
                                   "reason": "operation_scope_mismatch"})
        item["identity"].update({
            "detected_tank": "5BT43",
            "correction_sha256": record["correction_sha256"],
        })
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(
                bsb.ManifestError, "operation_scope_mismatch"):
            bsb.ManifestBundle(fixture.manifest_path)

    def test_17_external_price_change_blocks_even_a_corrected_item(self):
        fixture = rebrand_fixture(
            ShopifyFixture(self.root / "fixture", authorised=True), {"1BT1": "2BT23"})
        fixture.install_correction("2BT23", original_model_tank="5BT43")
        bundle = bsb.ManifestBundle(fixture.manifest_path)
        contexts = bundle.select()
        gateway = FakeGateway(contexts)
        # Fred's cross-contaminated values (5BT43's NTA Imports / 25.00 / 1.00)
        # appear on the 2BT23 product: the protected-field gate must stop this.
        live = gateway.live[contexts[0].product_id]
        live["price"] = "25.00"
        live["cost"] = "1.00"
        live["vendor"] = "NTA Imports"
        state = bsb.StateStore(bundle)
        uploader = bsb.BatchUploader(
            bundle, gateway, state, sleep=lambda _: None,
            upload=lambda target, asset: None, poll_attempts=5, poll_interval=0)
        report = uploader.dry_run(contexts)
        self.assertEqual(report["blocked_count"], 1)
        self.assertIn("protected", report["items"][0]["error"])
        self.assertEqual(gateway.writes, [])
        report = uploader.execute(contexts)
        self.assertEqual(report["blocked_count"], 1)
        self.assertEqual(gateway.writes, [])


# --------------------------------------------------------------------------- #
# 18. No duplicate Shopify mutations (resume/idempotency)
# --------------------------------------------------------------------------- #
class Category18Idempotency(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def sandbox(self, name):
        return StrictSandbox(self.root / name, [INCIDENT_PHOTO], {
            INCIDENT_SHA: {
                "catalogue": catalogue_output("2BT23", "2026-10-14"),
                "label": label_output("2BT23", "14/10/2026"),
                "preflight": preflight_output("2BT23", "2026-10-14"),
                "prepqa": prepqa_output(),
            }
        }, policy_mode="full")

    def test_18_process_restart_never_repeats_a_mutation(self):
        sandbox = self.sandbox("sandbox")
        first = sandbox.run()
        self.assertEqual(first["status"], "COMPLETE")
        self.assertEqual(sandbox.calls["execute"], 1)
        self.assertEqual(sandbox.calls["generate"], 1)
        frozen = dict(first)
        second = sandbox.run()
        self.assertEqual(second, frozen)
        self.assertEqual(sandbox.calls["execute"], 1)
        self.assertEqual(sandbox.calls["generate"], 1)

    def test_18_exactly_one_mutation_per_identity_source(self):
        sandbox = self.sandbox("sandbox2")
        result = sandbox.run()
        self.assertEqual(result["status"], "COMPLETE")
        manifest = json.loads(
            (sandbox.batch_dir / "manifest" / "shopify-production.json").read_text())
        item = manifest["items"][0]
        executions = [entry for entry in [sandbox.entry()]
                      if entry.get("shopify_receipt")]
        self.assertEqual(len(executions), 1)
        self.assertEqual(sandbox.calls["execute"], 1)
        # The mocked execute runner always receives this exact manifest digest
        # and the item identity binds one source hash.
        self.assertEqual(item["identity"]["source_sha256"], INCIDENT_SHA)
        self.assertEqual(item["original"]["sha256"], INCIDENT_SHA)
        self.assertEqual(sandbox.calls["resolve"], ["2BT23"])


# --------------------------------------------------------------------------- #
# 19. Repeat correction requests are immutable
# --------------------------------------------------------------------------- #
class Category19RepeatCorrections(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def kwargs(self):
        return {
            "source_sha256": INCIDENT_SHA,
            "original_model_tank": "5BT43",
            "corrected_tank": "2BT23",
            "product_id": "gid://shopify/Product/7255867588817",
            "variant_id": "gid://shopify/ProductVariant/41571765453009",
            "operation": {"fields": list(bsb.IDENTITY_OPERATION_FIELDS),
                          "mode": "owner-directed"},
            "reason": "owner corrected the vision tank reading",
            "evidence_reference": "incident-2026-10-15-photo",
            "operator": "owner",
            "directory": self.root / "corrections",
            "created_at": "2026-10-15T00:00:00+00:00",
        }

    def test_19_identical_repeat_write_is_refused_and_file_is_unchanged(self):
        path = corrections.record(**self.kwargs())
        before_bytes = path.read_bytes()
        before_stat = os.stat(path)
        with self.assertRaisesRegex(
                corrections.CorrectionError, "already exists and is immutable"):
            corrections.record(**self.kwargs())
        self.assertEqual(path.read_bytes(), before_bytes)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o444)
        self.assertEqual(os.stat(path).st_mode & 0o777,
                         before_stat.st_mode & 0o777)

    def test_19_repeated_validation_is_stable_and_equal(self):
        path = corrections.record(**self.kwargs())
        args = {
            "source_sha256": INCIDENT_SHA, "requested_tank": "2BT23",
            "accepted_tank": "2BT23",
            "product_id": "gid://shopify/Product/7255867588817",
            "operation_fields": list(bsb.IDENTITY_OPERATION_FIELDS),
        }
        first = corrections.validate_correction(path, **args)
        second = corrections.validate_correction(path, **args)
        self.assertEqual(first, {"valid": True, "reason": "ok"})
        self.assertEqual(first, second)

    def test_19_tampered_repeat_is_refused(self):
        path = corrections.record(**self.kwargs())
        os.chmod(path, 0o644)
        record = json.loads(path.read_text())
        record["corrected_tank"] = "5BT43"
        path.write_text(json.dumps(record), encoding="utf-8")
        verdict = corrections.validate_correction(
            path, source_sha256=INCIDENT_SHA, requested_tank="2BT23",
            accepted_tank="2BT23",
            product_id="gid://shopify/Product/7255867588817",
            operation_fields=list(bsb.IDENTITY_OPERATION_FIELDS))
        self.assertEqual(verdict["valid"], False)
        self.assertEqual(verdict["reason"], "self_hash_mismatch")


# --------------------------------------------------------------------------- #
# 20. Concurrent batches with similar handwritten numbers
# --------------------------------------------------------------------------- #
class Category20ConcurrentBatches(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.registry = self.root / "shared-registry.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def run_batch(self, name, source, tank, date_iso, date_dmy):
        sandbox = StrictSandbox(self.root / name, [source], {
            sha256(source): {
                "catalogue": catalogue_output(tank, date_iso),
                "label": label_output(tank, date_dmy),
                "preflight": preflight_output(tank, date_iso),
                "prepqa": prepqa_output(),
            }
        }, policy_mode="full", registry=self.registry, label=name)
        result = sandbox.run()
        return sandbox, result

    def test_20_shared_registry_keeps_both_identities_distinct_and_bound(self):
        # Mocked vision keyed by input hash; values mirror each card's visible
        # contents (2BT23 / 14/10/2026 and 5BT43 / 9/10/2026). Plumbing only.
        incident, incident_result = self.run_batch(
            "batch-2bt23", INCIDENT_PHOTO, "2BT23", "2026-10-14", "14/10/2026")
        confusion, confusion_result = self.run_batch(
            "batch-5bt43", NEAR_CONFUSION_PHOTO, "5BT43", "2026-10-09", "9/10/2026")
        self.assertEqual(incident_result["status"], "COMPLETE")
        self.assertEqual(confusion_result["status"], "COMPLETE")

        incident_entry = incident.entry()
        confusion_entry = confusion.entry()
        self.assertEqual(incident_entry["source_sha256"], INCIDENT_SHA)
        self.assertEqual(confusion_entry["source_sha256"], NEAR_CONFUSION_SHA)
        self.assertEqual(incident_entry["tank_id"], "2BT23")
        self.assertEqual(confusion_entry["tank_id"], "5BT43")
        self.assertEqual(incident_entry["photo_date"], "2026-10-14")
        self.assertEqual(confusion_entry["photo_date"], "2026-10-09")

        incident_manifest = json.loads(
            (incident.batch_dir / "manifest" / "shopify-production.json").read_text())
        confusion_manifest = json.loads(
            (confusion.batch_dir / "manifest" / "shopify-production.json").read_text())
        incident_item = incident_manifest["items"][0]
        confusion_item = confusion_manifest["items"][0]
        self.assertEqual(incident_item["identity"]["source_sha256"], INCIDENT_SHA)
        self.assertEqual(incident_item["identity"]["accepted_tank"], "2BT23")
        self.assertEqual(confusion_item["identity"]["source_sha256"],
                         NEAR_CONFUSION_SHA)
        self.assertEqual(confusion_item["identity"]["accepted_tank"], "5BT43")
        self.assertEqual(incident_manifest["batch_id"], incident.batch_id)
        self.assertEqual(confusion_manifest["batch_id"], confusion.batch_id)
        self.assertNotEqual(incident_manifest["batch_id"],
                            confusion_manifest["batch_id"])

        # Neither identity leaks into the other batch's receipts/manifest/state.
        self.assertEqual(
            [path for path in incident.batch_files_matching("5BT43")
             if "label" not in Path(path).name], [])
        self.assertEqual(
            [path for path in confusion.batch_files_matching("2BT23")
             if "label" not in Path(path).name], [])

        con = sqlite3.connect(self.registry)
        try:
            rows = dict(con.execute(
                "SELECT source_sha256, batch_id FROM processed").fetchall())
        finally:
            con.close()
        self.assertEqual(rows, {
            INCIDENT_SHA: incident.batch_id,
            NEAR_CONFUSION_SHA: confusion.batch_id,
        })
        self.assertNotEqual(INCIDENT_SHA, NEAR_CONFUSION_SHA)

    def test_20_nearby_numbers_are_distinct_under_normalisation_and_comparison(self):
        self.assertEqual(label_identity.normalize_tank("2 BT 23"), "2BT23")
        self.assertEqual(label_identity.normalize_tank("5 BT 43"), "5BT43")
        self.assertNotEqual(label_identity.normalize_tank("2BT23"),
                            label_identity.normalize_tank("5BT43"))
        self.assertNotEqual(label_identity.normalize_date("14/10/2026"),
                            label_identity.normalize_date("9/10/2026"))
        self.assertEqual(label_identity.normalize_date("14/10/2026"), "2026-10-14")
        self.assertEqual(label_identity.normalize_date("9/10/2026"), "2026-10-09")
        for full, crop in (
            ({"tank_id": "2BT23", "photo_date": "2026-10-14", "confident": True},
             {"tank_id": "5BT43", "photo_date": "2026-10-09", "confident": True}),
            ({"tank_id": "5BT43", "photo_date": "2026-10-14", "confident": True},
             {"tank_id": "2BT23", "photo_date": "2026-10-14", "confident": True}),
        ):
            verdict = label_identity.compare_reads(full, crop)
            self.assertEqual(verdict["status"], "DISAGREE")
            self.assertIsNone(verdict["tank"])
            self.assertIsNone(verdict["date"])


if __name__ == "__main__":
    unittest.main()
