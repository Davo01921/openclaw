from __future__ import annotations

from typing import Any, Callable

from barcode_policy import collision_status, plan_barcode, verification_status


class ShopifyBarcodeError(RuntimeError):
    pass


class ShopifyBarcodeGateway:
    """Concrete Shopify Admin GraphQL adapter for the NTA barcode workflow.

    The authenticated GraphQL transport is injected by the caller. No token,
    store URL, model call, printer call, or retry loop is embedded here.
    """

    READ = """query ReadVariantBarcode($id: ID!) {
      productVariant(id: $id) {
        id
        legacyResourceId
        barcode
        product { id }
      }
    }"""

    FIND = """query FindBarcodeCollision($query: String!) {
      productVariants(first: 5, query: $query) {
        nodes { id barcode product { id } }
      }
    }"""

    WRITE = """mutation WriteVariantBarcode($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
      productVariantsBulkUpdate(productId: $productId, variants: $variants) {
        productVariants { id barcode }
        userErrors { field message }
      }
    }"""

    def __init__(
        self,
        graphql: Callable[[str, dict[str, Any]], dict[str, Any]],
        *,
        execution_enabled: bool = False,
    ):
        self.graphql = graphql
        self.execution_enabled = execution_enabled

    def _call(self, document: str, variables: dict[str, Any]) -> dict[str, Any]:
        body = self.graphql(document, variables)
        if not isinstance(body, dict):
            raise ShopifyBarcodeError("Shopify GraphQL transport returned a non-object response")
        if body.get("errors"):
            raise ShopifyBarcodeError(f"Shopify GraphQL error: {body['errors']}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise ShopifyBarcodeError("Shopify GraphQL response is missing data")
        return data

    def read_variant(self, variant_id: str) -> dict[str, Any]:
        node = self._call(self.READ, {"id": variant_id}).get("productVariant")
        if not isinstance(node, dict) or node.get("id") != variant_id:
            raise ShopifyBarcodeError(
                "Shopify variant read-back did not resolve the requested variant"
            )
        product_id = (node.get("product") or {}).get("id")
        if not product_id:
            raise ShopifyBarcodeError("Shopify variant read-back is missing product ID")
        return {
            "variant_id": node["id"],
            "legacy_resource_id": node.get("legacyResourceId"),
            "barcode": node.get("barcode"),
            "product_id": product_id,
        }

    def find_barcode_matches(self, barcode: str) -> list[str]:
        data = self._call(self.FIND, {"query": f"barcode:{barcode}"})
        nodes = ((data.get("productVariants") or {}).get("nodes") or [])
        return [
            node.get("id")
            for node in nodes
            if isinstance(node, dict) and node.get("id")
        ]

    def write_barcode(
        self,
        *,
        product_id: str,
        variant_id: str,
        barcode: str,
    ) -> None:
        if not self.execution_enabled:
            raise ShopifyBarcodeError("Shopify barcode write execution is disabled")
        result = self._call(
            self.WRITE,
            {
                "productId": product_id,
                "variants": [{"id": variant_id, "barcode": barcode}],
            },
        ).get("productVariantsBulkUpdate") or {}
        errors = result.get("userErrors") or []
        if errors:
            raise ShopifyBarcodeError(f"Shopify rejected barcode write: {errors}")

    def ensure_verified_barcode(
        self,
        *,
        variant_id: str,
        mode: str = "write",
    ) -> dict[str, Any]:
        if mode not in {"dry_run", "write"}:
            raise ValueError("mode must be dry_run or write")

        before = self.read_variant(variant_id)
        plan = plan_barcode(
            {
                "variant_id": before["variant_id"],
                "legacy_resource_id": before["legacy_resource_id"],
                "current_shopify_barcode": before["barcode"],
            }
        )
        if plan.get("status") != "READY":
            return {**plan, "before": before}

        if plan["action"] == "KEEP_EXISTING":
            return {
                "status": "VERIFIED",
                "barcode": plan["barcode"],
                "barcode_source": "existing_shopify",
                "write_performed": False,
                "before": before,
                "after": before,
            }

        candidate = plan["barcode"]
        pre_collision = collision_status(
            candidate_barcode=candidate,
            target_variant_id=variant_id,
            matching_variant_ids=self.find_barcode_matches(candidate),
        )
        if pre_collision["status"] != "READY":
            return {
                **pre_collision,
                "barcode_source": "generated_internal",
                "write_performed": False,
                "before": before,
            }

        if mode == "dry_run":
            return {
                "status": "PROPOSED",
                "barcode": candidate,
                "barcode_source": "generated_internal",
                "write_performed": False,
                "before": before,
                "after": None,
            }

        if not self.execution_enabled:
            return {
                "status": "BLOCKED",
                "code": "WRITE_DISABLED",
                "barcode": candidate,
                "barcode_source": "generated_internal",
                "write_performed": False,
                "before": before,
                "after": None,
            }

        self.write_barcode(
            product_id=before["product_id"],
            variant_id=variant_id,
            barcode=candidate,
        )

        after = self.read_variant(variant_id)
        verified = verification_status(
            expected_barcode=candidate,
            live_barcode=after["barcode"],
        )
        if verified["status"] != "VERIFIED":
            return {
                **verified,
                "barcode_source": "generated_internal",
                "write_performed": True,
                "before": before,
                "after": after,
            }

        post_collision = collision_status(
            candidate_barcode=candidate,
            target_variant_id=variant_id,
            matching_variant_ids=self.find_barcode_matches(candidate),
        )
        if post_collision["status"] != "READY":
            return {
                **post_collision,
                "barcode_source": "generated_internal",
                "write_performed": True,
                "before": before,
                "after": after,
            }

        return {
            "status": "VERIFIED",
            "barcode": candidate,
            "barcode_source": "generated_internal",
            "write_performed": True,
            "before": before,
            "after": after,
        }
