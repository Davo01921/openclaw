import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "scripts"

POLICY_SPEC = importlib.util.spec_from_file_location(
    "barcode_policy", SCRIPTS / "barcode_policy.py"
)
POLICY = importlib.util.module_from_spec(POLICY_SPEC)
assert POLICY_SPEC.loader is not None
POLICY_SPEC.loader.exec_module(POLICY)
sys.modules["barcode_policy"] = POLICY

ADAPTER_SPEC = importlib.util.spec_from_file_location(
    "shopify_adapter", SCRIPTS / "shopify_adapter.py"
)
ADAPTER = importlib.util.module_from_spec(ADAPTER_SPEC)
assert ADAPTER_SPEC.loader is not None
ADAPTER_SPEC.loader.exec_module(ADAPTER)


class FakeShopify:
    def __init__(self, *, barcode=None, collision=False, mismatch=False):
        self.barcode = barcode
        self.collision = collision
        self.mismatch = mismatch
        self.calls = []

    def __call__(self, document, variables):
        self.calls.append((document, variables))

        if "ReadVariantBarcode" in document:
            return {
                "data": {
                    "productVariant": {
                        "id": variables["id"],
                        "legacyResourceId": "123",
                        "barcode": self.barcode,
                        "product": {"id": "gid://shopify/Product/9"},
                    }
                }
            }

        if "FindBarcodeCollision" in document:
            if self.collision:
                ids = ["gid://shopify/ProductVariant/999"]
            elif self.barcode:
                ids = ["gid://shopify/ProductVariant/123"]
            else:
                ids = []
            return {
                "data": {
                    "productVariants": {
                        "nodes": [
                            {
                                "id": variant_id,
                                "barcode": self.barcode,
                                "product": {"id": "gid://shopify/Product/9"},
                            }
                            for variant_id in ids
                        ]
                    }
                }
            }

        if "WriteVariantBarcode" in document:
            if self.mismatch:
                self.barcode = "WRONG"
            else:
                self.barcode = variables["variants"][0]["barcode"]
            return {
                "data": {
                    "productVariantsBulkUpdate": {
                        "productVariants": [
                            {
                                "id": variables["variants"][0]["id"],
                                "barcode": self.barcode,
                            }
                        ],
                        "userErrors": [],
                    }
                }
            }

        raise AssertionError("unexpected GraphQL document")


class ShopifyBarcodeGatewayTests(unittest.TestCase):
    VARIANT_ID = "gid://shopify/ProductVariant/123"

    def test_missing_barcode_writes_then_freshly_verifies(self):
        fake = FakeShopify()
        gateway = ADAPTER.ShopifyBarcodeGateway(fake, execution_enabled=True)
        result = gateway.ensure_verified_barcode(variant_id=self.VARIANT_ID)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["barcode"], "NTA-V-123")
        self.assertTrue(result["write_performed"])
        self.assertEqual(fake.barcode, "NTA-V-123")
        self.assertEqual(sum("ReadVariantBarcode" in call[0] for call in fake.calls), 2)
        self.assertEqual(sum("FindBarcodeCollision" in call[0] for call in fake.calls), 2)
        self.assertEqual(sum("WriteVariantBarcode" in call[0] for call in fake.calls), 1)

    def test_existing_barcode_is_never_overwritten(self):
        fake = FakeShopify(barcode="SUPPLIER-123")
        gateway = ADAPTER.ShopifyBarcodeGateway(fake, execution_enabled=True)
        result = gateway.ensure_verified_barcode(variant_id=self.VARIANT_ID)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["barcode"], "SUPPLIER-123")
        self.assertFalse(result["write_performed"])
        self.assertFalse(any("WriteVariantBarcode" in call[0] for call in fake.calls))

    def test_dry_run_proposes_but_never_writes(self):
        fake = FakeShopify()
        gateway = ADAPTER.ShopifyBarcodeGateway(fake, execution_enabled=False)
        result = gateway.ensure_verified_barcode(
            variant_id=self.VARIANT_ID,
            mode="dry_run",
        )
        self.assertEqual(result["status"], "PROPOSED")
        self.assertEqual(result["barcode"], "NTA-V-123")
        self.assertFalse(result["write_performed"])
        self.assertFalse(any("WriteVariantBarcode" in call[0] for call in fake.calls))

    def test_collision_blocks_before_write(self):
        fake = FakeShopify(collision=True)
        gateway = ADAPTER.ShopifyBarcodeGateway(fake, execution_enabled=True)
        result = gateway.ensure_verified_barcode(variant_id=self.VARIANT_ID)
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertFalse(result["write_performed"])
        self.assertFalse(any("WriteVariantBarcode" in call[0] for call in fake.calls))

    def test_readback_mismatch_fails_and_blocks_print_contract(self):
        fake = FakeShopify(mismatch=True)
        gateway = ADAPTER.ShopifyBarcodeGateway(fake, execution_enabled=True)
        result = gateway.ensure_verified_barcode(variant_id=self.VARIANT_ID)
        self.assertEqual(result["status"], "FAILED")
        self.assertTrue(result["write_performed"])
        self.assertEqual(result["live_barcode"], "WRONG")


if __name__ == "__main__":
    unittest.main()
