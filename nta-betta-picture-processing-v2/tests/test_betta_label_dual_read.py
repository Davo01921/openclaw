"""Regression tests for the dual label read (incident repair 2026-10-15).

Covers the pinned ``label_identity.compare_reads`` contract, the focused
label-crop lineage, the strict ``visible_price`` parsing and an evidence test
over the recorded real-call outputs under
``docs/incident/label_recognition_evidence/``.

The evidence test verifies the recorded shapes, hash lineage and the
documented expectation only.  It never asserts a model reading beyond what was
truly recorded at evaluation time (and is skipped when the evidence is absent).
"""

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
EVIDENCE = ROOT / "docs" / "incident" / "label_recognition_evidence"
FIXTURE = ROOT / "tests" / "fixtures" / "incident_2bt23" / "incident-photo.png"
INCIDENT_PHOTO_SHA256 = "6e4a4f573f8cfc829218f798eeb5b45cd08803689d31d7db6fce4920cdca9ca9"
HEX64 = set("0123456789abcdef")


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


label_identity = _load("label_identity_dual_t", "label_identity.py")
prepare = _load("betta_prepare_dual_t", "betta_prepare.py")
vision = _load("vision_review_dual_t", "vision_review.py")


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def is_sha256(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in HEX64 for char in value))


class CompareReadsTests(unittest.TestCase):
    """Pinned comparator matrix: AGREE only on confident agreement."""

    @staticmethod
    def read(tank, date, *, confident=True, **extra):
        return {"tank_id": tank, "photo_date": date, "confident": confident, **extra}

    def test_agree_requires_both_confident_and_matching_tank_and_date(self):
        result = label_identity.compare_reads(
            self.read("2BT23", "2026-10-14"), self.read("2BT23", "2026-10-14"))
        self.assertEqual(result["status"], "AGREE")
        self.expected_agreed_values(result, "2BT23", "2026-10-14")

    def test_wrong_high_confidence_full_read_disagrees_and_never_picks_a_side(self):
        # The incident shape: the unverified full read asserted 5BT43 while the
        # focused label read saw 2BT23.  Both sides are confident: DISAGREE,
        # and the comparator must not choose either tank.
        result = label_identity.compare_reads(
            self.read("5BT43", "2026-10-14"), self.read("2BT23", "2026-10-14"))
        self.assertEqual(result["status"], "DISAGREE")
        self.assertIsNone(result["tank"])
        self.assertIsNone(result["date"])
        self.assertTrue(any("tank mismatch: full=5BT43 label-crop=2BT23" in reason
                            for reason in result["reasons"]))

    def test_date_disagreement_is_disagree(self):
        result = label_identity.compare_reads(
            self.read("2BT23", "2026-10-04"), self.read("2BT23", "2026-10-14"))
        self.assertEqual(result["status"], "DISAGREE")
        self.assertIsNone(result["tank"])
        self.assertIsNone(result["date"])
        self.assertTrue(any("date mismatch: full=2026-10-04 label-crop=2026-10-14"
                            in reason for reason in result["reasons"]))

    def test_tank_and_date_disagreement_records_both_reasons(self):
        result = label_identity.compare_reads(
            self.read("5BT43", "2026-10-09"), self.read("2BT23", "2026-10-14"))
        self.assertEqual(result["status"], "DISAGREE")
        joined = " ".join(result["reasons"])
        self.assertIn("tank mismatch", joined)
        self.assertIn("date mismatch", joined)

    def test_incomplete_when_either_read_is_not_confident(self):
        for full, crop in (
            (self.read("2BT23", "2026-10-14", confident=False),
             self.read("2BT23", "2026-10-14")),
            (self.read("2BT23", "2026-10-14"),
             self.read("2BT23", "2026-10-14", confident=False)),
            (self.read("2BT23", "2026-10-14", confident=False),
             self.read("2BT23", "2026-10-14", confident=False)),
            ({}, self.read("2BT23", "2026-10-14")),
            ({}, {}),
        ):
            result = label_identity.compare_reads(full, crop)
            self.assertEqual(result["status"], "INCOMPLETE")
            self.assertIsNone(result["tank"])
            self.assertIsNone(result["date"])
            self.assertTrue(any("not confident" in reason for reason in result["reasons"]))

    def test_equal_values_from_a_non_confident_read_never_become_agree(self):
        # No majority voting and no agreement-by-luck: a low-confidence read
        # that happens to match is still INCOMPLETE.
        result = label_identity.compare_reads(
            self.read("2BT23", "2026-10-14", confident=False),
            self.read("2BT23", "2026-10-14"))
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertIsNone(result["tank"])
        self.assertIsNone(result["date"])

    def test_missing_values_in_confident_reads_disagree(self):
        result = label_identity.compare_reads(
            self.read(None, "2026-10-14"), self.read("2BT23", "2026-10-14"))
        self.assertEqual(result["status"], "DISAGREE")
        self.assertTrue(any("tank is missing from the full read" in reason
                            for reason in result["reasons"]))
        result = label_identity.compare_reads(
            self.read("2BT23", None), self.read("2BT23", "2026-10-14"))
        self.assertEqual(result["status"], "DISAGREE")
        self.assertTrue(any("date is missing from the full read" in reason
                            for reason in result["reasons"]))

    def test_empty_tank_and_date_are_treated_as_missing(self):
        result = label_identity.compare_reads(
            self.read("", ""), self.read("", ""))
        self.assertEqual(result["status"], "DISAGREE")
        self.assertIsNone(result["tank"])
        self.assertIsNone(result["date"])

    def test_comparator_uses_only_tank_and_date_not_price(self):
        full = self.read("2BT23", "2026-10-14", visible_price="25")
        crop = self.read("2BT23", "2026-10-14", visible_price="35")
        result = label_identity.compare_reads(full, crop)
        self.assertEqual(result["status"], "AGREE")

    def test_never_guesses_values_for_any_non_agree_status(self):
        cases = (
            (self.read("5BT43", "2026-10-14"), self.read("2BT23", "2026-10-14")),
            (self.read("2BT23", "2026-10-04"), self.read("2BT23", "2026-10-14")),
            (self.read("5BT43", "2026-10-14", confident=False),
             self.read("2BT23", "2026-10-14")),
            (self.read(None, None), self.read("2BT23", "2026-10-14")),
            ({}, {}),
        )
        for full, crop in cases:
            result = label_identity.compare_reads(full, crop)
            self.assertIn(result["status"], {"DISAGREE", "INCOMPLETE"})
            self.assertIsNone(result["tank"])
            self.assertIsNone(result["date"])

    def test_result_shape_is_pinned(self):
        result = label_identity.compare_reads(
            self.read("2BT23", "2026-10-14"), self.read("2BT23", "2026-10-14"))
        self.assertEqual(
            set(result), {"status", "tank", "date", "reasons"})
        self.assertIsInstance(result["reasons"], list)
        self.assertTrue(all(isinstance(reason, str) for reason in result["reasons"]))

    def expected_agreed_values(self, result, tank, date):
        self.assertEqual(result["tank"], tank)
        self.assertEqual(result["date"], date)


class LabelCropLineageTests(unittest.TestCase):
    """The focused label crop must record exact, deterministic lineage."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def make_card_source(self, name="source.png"):
        image = Image.new("RGB", (300, 400), (8, 12, 16))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 299, 60), fill=(238, 236, 230))
        path = self.root / name
        image.save(path, format="PNG")
        return path

    def test_crop_records_hashes_and_is_a_deterministic_region_of_the_source(self):
        source = self.make_card_source()
        out1 = self.root / "crop-1.png"
        out2 = self.root / "crop-2.png"
        record = prepare.label_crop(source, out1)
        repeated = prepare.label_crop(source, out2)

        # Recorded lineage: source sha + output sha + rectangle + dimensions.
        self.assertEqual(record["source_sha256"], sha(source))
        self.assertEqual(record["output_sha256"], sha(out1))
        self.assertEqual(record["source_dimensions"], [300, 400])
        x0, y0, x1, y1 = record["rect_px"]
        self.assertEqual([x0, y0, x1], [0, 0, 300])
        self.assertEqual(record["output_dimensions"], [x1 - x0, y1 - y0])
        self.assertTrue(record["confident"])
        self.assertEqual(record["method"], "card-band")

        # The record references only the final crop path; the atomic write must
        # never leave (or persist) a `.part` staging artifact.
        self.assertEqual(record["output_path"], str(out1))
        self.assertEqual(repeated["output_path"], str(out2))
        self.assertNotIn(".part", record["output_path"])
        self.assertEqual(list(self.root.glob("*.part")), [])

        # The output bytes are exactly the source rectangle (no derived edits).
        with Image.open(source) as opened:
            expected = opened.convert("RGB").crop(tuple(record["rect_px"]))
        with Image.open(out1) as produced:
            self.assertEqual(produced.convert("RGB").tobytes(), expected.tobytes())

        # Running twice yields identical bytes and identical hashes.
        self.assertEqual(out1.read_bytes(), out2.read_bytes())
        self.assertEqual(record["output_sha256"], repeated["output_sha256"])
        self.assertEqual(record["rect_px"], repeated["rect_px"])

    def test_incident_fixture_produces_a_confident_full_width_crop(self):
        if not FIXTURE.is_file():
            self.skipTest("incident fixture not present")
        self.assertEqual(sha(FIXTURE), INCIDENT_PHOTO_SHA256)
        record = prepare.label_crop(FIXTURE, self.root / "incident-label.png")
        self.assertEqual(record["source_sha256"], INCIDENT_PHOTO_SHA256)
        self.assertEqual(record["source_dimensions"], [1512, 2688])
        self.assertTrue(record["confident"])
        self.assertEqual(record["method"], "card-band")
        x0, y0, x1, y1 = record["rect_px"]
        self.assertEqual([x0, y0, x1], [0, 0, 1512])
        # The documented card occupies roughly the top 15-16% of this photo:
        # the crop must contain it (with its safety pad) while staying well
        # inside the 35% search limit.
        self.assertGreaterEqual(y1, int(2688 * 0.15))
        self.assertLess(y1, int(round(2688 * prepare.LABEL_SEARCH_FRACTION)))


class VisiblePriceParsingTests(unittest.TestCase):
    """Strict visible_price parsing: digits/decimal only, never invented."""

    def test_valid_prices_canonicalise(self):
        self.assertEqual(label_identity.parse_visible_price("35"), "35")
        self.assertEqual(label_identity.parse_visible_price("$35"), "35")
        self.assertEqual(label_identity.parse_visible_price(" 35 "), "35")
        self.assertEqual(label_identity.parse_visible_price("35.00"), "35")
        self.assertEqual(label_identity.parse_visible_price("0.50"), "0.5")
        self.assertEqual(label_identity.parse_visible_price(35), "35")

    def test_absent_prices_are_none(self):
        for raw in (None, "", "   ", "$", "$ "):
            self.assertIsNone(label_identity.parse_visible_price(raw))

    def test_invalid_prices_are_none_and_never_invented(self):
        for raw in ("about 35", "35 dollars", "35.999", "3 5", "35,00",
                    "FREE", "thirty-five", "N/A", True, False, ["35"]):
            self.assertIsNone(label_identity.parse_visible_price(raw))

    def test_label_mode_output_normalisation_uses_strict_parsing(self):
        output = vision.normalize_label_output({"visible_price": "35.00"})
        self.assertEqual(output["visible_price"], "35")
        absent = vision.normalize_label_output({"tank_id": "2BT23"})
        self.assertIsNone(absent["visible_price"])
        invalid = vision.normalize_label_output({"visible_price": "roughly $35"})
        self.assertIsNone(invalid["visible_price"])


class LabelRecognitionEvidenceTests(unittest.TestCase):
    """Evidence test over the recorded real-call outputs (skipped when absent).

    Only assertions that hold for whatever was truly recorded: record shape,
    hash lineage between the crop file and the reads, and the documented
    expectation.  The model's specific reading is recorded, not asserted.
    """

    def load_json(self, name):
        path = EVIDENCE / name
        if not path.is_file():
            self.skipTest(f"evidence file not present: {path}")
        return json.loads(path.read_text())

    def assert_call_shape(self, record):
        self.assertIsInstance(record, dict)
        for field in ("provider", "model", "call_id", "timestamp"):
            self.assertTrue(record.get(field), f"missing {field}")
        self.assertNotEqual(record["provider"].casefold(), "unknown")
        self.assertNotEqual(record["model"].casefold(), "unknown")
        self.assertEqual(record["routing"]["execution_attested"], True)
        self.assertIsInstance(record["input_hashes"], list)
        self.assertTrue(record["input_hashes"])
        self.assertTrue(all(is_sha256(value) for value in record["input_hashes"]))
        self.assertIsInstance(record["output"], dict)

    def test_full_read_evidence_shape_binds_the_incident_photo(self):
        record = self.load_json("full-read.json")
        self.assert_call_shape(record)
        self.assertEqual(record["input_hashes"], [INCIDENT_PHOTO_SHA256])

    def test_label_read_evidence_shape_binds_the_recorded_crop(self):
        record = self.load_json("label-read.json")
        self.assert_call_shape(record)
        crop_path = EVIDENCE / "label-crop.png"
        if crop_path.is_file():
            self.assertEqual(record["input_hashes"], [sha(crop_path)])
        # The improved label contract always carries the parsed visible_price
        # key (a canonical digits string or None), whatever the model returned.
        self.assertIn("visible_price", record["output"])
        self.assertTrue(record["output"]["visible_price"] is None
                        or isinstance(record["output"]["visible_price"], str))
        self.assertIn("tank_id", record["output"])
        self.assertIn("photo_date", record["output"])

    def test_crop_lineage_matches_the_recorded_files(self):
        if not (EVIDENCE / "label-crop.json").is_file():
            self.skipTest("crop lineage evidence not present")
        record = self.load_json("label-crop.json")
        crop_path = EVIDENCE / "label-crop.png"
        self.assertTrue(crop_path.is_file())
        self.assertEqual(record["source_sha256"], INCIDENT_PHOTO_SHA256)
        self.assertEqual(record["output_sha256"], sha(crop_path))
        self.assertEqual(record["source_dimensions"], [1512, 2688])
        x0, y0, x1, y1 = record["rect_px"]
        self.assertEqual([x0, y0, x1], [0, 0, 1512])
        self.assertEqual(record["output_dimensions"], [x1 - x0, y1 - y0])

    def test_summary_documents_the_expected_reading(self):
        summary = EVIDENCE / "summary.md"
        if not summary.is_file():
            self.skipTest("evidence summary not present")
        text = summary.read_text()
        # The documented expectation (ground truth for the incident photo).
        for token in ("2BT23", "2026-10-14", "35", "Expected"):
            self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
