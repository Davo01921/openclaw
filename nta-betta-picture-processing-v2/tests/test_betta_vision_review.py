"""Offline tests for the calibrated vision-review contracts and taxonomy."""

import importlib.util
import sys
import unittest
from pathlib import Path


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parents[1] / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


vision = _load("vision_review_t", "vision_review.py")


class VisionReviewTests(unittest.TestCase):
    def test_failure_taxonomy_groups_real_assertions(self):
        categorised = vision.categorise_assertions({
            "same_identity": "FAIL", "scale_markings": "FAIL",
            "body_anatomy": "FAIL", "complete_framing": "FAIL",
            "regional_colour": "PASS", "label": "PASS",
            "tail_fins_pose": "PASS", "realistic_texture": "PASS",
            "hero_composition": "PASS", "reference_integrity": "PASS",
        })
        self.assertEqual(categorised["identity"], ["same_identity", "scale_markings"])
        self.assertEqual(categorised["anatomy"], ["body_anatomy"])
        self.assertEqual(categorised["presentation"], ["complete_framing"])
        self.assertEqual(vision.categorise_assertions({})["identity"], [])

    def test_calibrated_qa_prompt_covers_allowances_and_rejections(self):
        rendered = vision.QA_PROMPT_TEMPLATE.format(tank="2BT14", date="14/10/2026")
        self.assertIn("2BT14", rendered)
        self.assertIn("14/10/2026", rendered)
        self.assertNotIn("{{", rendered)
        self.assertNotIn("}}", rendered)
        lowered = rendered.lower()
        # Presentation allowances are calibrated in, not silently dropped.
        self.assertIn("display posture", lowered)
        self.assertIn("more saturated rendering of the same hues", lowered)
        self.assertIn("tonal rendering differences", lowered)
        # The mission's hard rejections remain explicit.
        for clause in ("different colour family", "extra or missing fins",
                       "label mismatch", "different pattern class"):
            self.assertIn(clause, lowered)

    def test_all_review_modes_have_prompts(self):
        self.assertIn("APE", vision.PREFLIGHT_PROMPT)
        self.assertIn("one_fish_visible", vision.CATALOGUE_PROMPT)
        self.assertIn("same_fish", vision.PREP_QA_PROMPT)
        self.assertIn("full_fins", vision.PREP_QA_PROMPT)
        self.assertIn("no_identity_alteration", vision.PREP_QA_PROMPT)
        self.assertIn("BT", vision.LABEL_PROMPT)

    def test_label_prompt_requests_strict_visible_price(self):
        prompt = vision.LABEL_PROMPT
        self.assertIn("\"visible_price\"", prompt)
        self.assertIn("digits only", prompt)
        self.assertIn("empty string", prompt)
        self.assertIn("Never invent a price", prompt)
        # The existing tank/date guidance is preserved.
        self.assertIn("2BT14", prompt)
        self.assertIn("APE16", prompt)
        self.assertIn("day/month/year", prompt)
        self.assertIn("never infer from adjacent tanks", prompt.lower())

    def test_label_output_contract_canonicalises_visible_price(self):
        output = vision.normalize_label_output({
            "tank_id": "2 BT 23", "tank_confidence": 0.95,
            "photo_date": "14/10/2026", "date_confidence": 0.95,
            "visible_price": "$35.00", "reasons": [],
        })
        self.assertEqual(output["visible_price"], "35")
        self.assertEqual(output["tank_id"], "2 BT 23")  # caller normalises tank/date
        absent = vision.normalize_label_output({"tank_id": "", "visible_price": ""})
        self.assertIsNone(absent["visible_price"])
        self.assertIn("visible_price", absent)
        invalid = vision.normalize_label_output({"visible_price": "about 35"})
        self.assertIsNone(invalid["visible_price"])
        with self.assertRaises(ValueError):
            vision.normalize_label_output(["not", "an", "object"])


if __name__ == "__main__":
    unittest.main()
