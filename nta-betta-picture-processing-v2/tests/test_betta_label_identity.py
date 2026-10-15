"""Offline tests for deterministic Betta label identity/date resolution."""

import importlib.util
import unittest
from decimal import Decimal
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "label_identity.py"
spec = importlib.util.spec_from_file_location("label_identity", SCRIPT)
li = importlib.util.module_from_spec(spec)
spec.loader.exec_module(li)


class LabelIdentityTests(unittest.TestCase):
    def test_normalize_tank(self):
        self.assertEqual(li.normalize_tank("2 BT 14"), "2BT14")
        self.assertEqual(li.normalize_tank("3bt21"), "3BT21")
        self.assertEqual(li.normalize_tank("APE16"), "APE16")
        self.assertEqual(li.normalize_tank("ape 16"), "APE16")
        for bad in ("BT14", "3BT", "3 BT X", "APE", ""):
            with self.assertRaises(ValueError):
                li.normalize_tank(bad)

    def test_normalize_tank_variants(self):
        # Handwritten spacing/case/separator variants normalise deterministically.
        self.assertEqual(li.normalize_tank("2 BT 23"), "2BT23")
        self.assertEqual(li.normalize_tank("2BT23"), "2BT23")
        self.assertEqual(li.normalize_tank(" 2bt23 "), "2BT23")
        self.assertEqual(li.normalize_tank("2-BT-23"), "2BT23")
        self.assertEqual(li.normalize_tank("APE 16"), "APE16")
        self.assertEqual(li.normalize_tank("ape16"), "APE16")
        for bad in ("2BT23A", "A2BT23", "2 BT", "SBT23", "APE 1X", "2/23"):
            with self.assertRaises(ValueError):
                li.normalize_tank(bad)

    def test_normalize_date(self):
        self.assertEqual(li.normalize_date("21/8/2026"), "2026-08-21")
        for bad in ("2026-08-21", "21/8/26", "32/8/2026"):
            with self.assertRaises(ValueError):
                li.normalize_date(bad)

    def test_normalize_date_handwritten_au_variants(self):
        self.assertEqual(li.normalize_date("14/10/2026"), "2026-10-14")
        self.assertEqual(li.normalize_date("4/10/2026"), "2026-10-04")
        # A written space before the year is safely parseable AU handwriting.
        self.assertEqual(li.normalize_date("14/10 2026"), "2026-10-14")
        self.assertEqual(li.normalize_date("14/10  2026"), "2026-10-14")
        # Incomplete or ambiguous dates are never guessed.
        for bad in ("14/10", "14 10 2026", "14/10/26",
                    "14.10.2026", "40/10/2026", "14/13/2026"):
            with self.assertRaises(ValueError):
                li.normalize_date(bad)

    def test_normalize_price(self):
        self.assertEqual(li.normalize_price("$35.00"), Decimal("35.00"))
        with self.assertRaises(ValueError):
            li.normalize_price("35.999")

    def test_validate_label(self):
        result = li.validate_label("2 BT 12", "9/10/2026", "$35.00")
        self.assertEqual(result["tank_id"], "2BT12")
        self.assertEqual(result["photo_date"], "2026-10-09")
        self.assertEqual(result["reference_price"], "35.00")
        self.assertEqual(result["status"], "FORMAT_VALID")

    def test_resolve_photo_date_clear_year(self):
        result = li.resolve_photo_date("9/10/2026", year_evidence="clear")
        self.assertEqual(result["photo_date"], "2026-10-09")
        self.assertEqual(result["year_source"], "physical_card")
        self.assertEqual(result["status"], "ACCEPTED")

    def test_resolve_photo_date_ambiguous_requires_trusted_reference(self):
        with self.assertRaises(ValueError):
            li.resolve_photo_date("9/10", year_evidence="ambiguous")
        with self.assertRaises(ValueError):
            li.resolve_photo_date("9/10", year_evidence="ambiguous",
                                  reference_date="2026-10-08", reference_source="filesystem_mtime")
        result = li.resolve_photo_date("9/10", year_evidence="ambiguous",
                                       reference_date="2026-10-08", reference_source="verified_intake")
        self.assertEqual(result["photo_date"], "2026-10-09")
        self.assertEqual(result["year_source"], "verified_intake")

    def test_year_discrepancy_is_flagged_not_accepted(self):
        result = li.resolve_photo_date("9/10/2025", year_evidence="clear",
                                       reference_date="2026-10-08", reference_source="verified_intake")
        self.assertEqual(result["status"], "REVIEW_YEAR_DISCREPANCY")

    def test_invalid_year_evidence(self):
        with self.assertRaises(ValueError):
            li.resolve_photo_date("9/10/2026", year_evidence="guess")


if __name__ == "__main__":
    unittest.main()
