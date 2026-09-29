import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "barcode_policy.py"
SPEC = importlib.util.spec_from_file_location("barcode_policy", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class BarcodePolicyTests(unittest.TestCase):
    def test_missing_barcode_is_deterministic(self):
        result = MODULE.plan_barcode(
            {
                "variant_id": "gid://shopify/ProductVariant/123456789",
                "current_shopify_barcode": None,
            }
        )
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["action"], "CREATE_INTERNAL")
        self.assertEqual(result["barcode"], "NTA-V-123456789")
        self.assertTrue(result["requires_shopify_write"])

    def test_existing_barcode_is_preserved(self):
        result = MODULE.plan_barcode(
            {
                "variant_id": "gid://shopify/ProductVariant/123456789",
                "current_shopify_barcode": "ABC-123",
            }
        )
        self.assertEqual(result["action"], "KEEP_EXISTING")
        self.assertEqual(result["barcode"], "ABC-123")
        self.assertFalse(result["requires_shopify_write"])

    def test_missing_live_barcode_evidence_requires_review(self):
        result = MODULE.plan_barcode(
            {"variant_id": "gid://shopify/ProductVariant/123456789"}
        )
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertIn("current_shopify_barcode", result["missing_or_invalid_fields"])

    def test_foreign_collision_requires_review(self):
        result = MODULE.collision_status(
            candidate_barcode="NTA-V-123456789",
            target_variant_id="gid://shopify/ProductVariant/123456789",
            matching_variant_ids=["gid://shopify/ProductVariant/2"],
        )
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertTrue(result["collision"])

    def test_same_variant_match_is_not_collision(self):
        result = MODULE.collision_status(
            candidate_barcode="NTA-V-123456789",
            target_variant_id="gid://shopify/ProductVariant/123456789",
            matching_variant_ids=["gid://shopify/ProductVariant/123456789"],
        )
        self.assertEqual(result["status"], "READY")
        self.assertFalse(result["collision"])

    def test_fresh_readback_must_match_exactly(self):
        self.assertEqual(
            MODULE.verification_status(
                expected_barcode="NTA-V-123456789",
                live_barcode="NTA-V-123456789",
            )["status"],
            "VERIFIED",
        )
        self.assertEqual(
            MODULE.verification_status(
                expected_barcode="NTA-V-123456789",
                live_barcode="NTA-V-999",
            )["status"],
            "FAILED",
        )


if __name__ == "__main__":
    unittest.main()
