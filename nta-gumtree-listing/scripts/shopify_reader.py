"""Read-only Shopify GraphQL normalizer for Gumtree Phase 1B.

This module contains no Shopify credentials and performs no writes. The caller is
responsible for executing SHOPIFY_PRODUCTS_QUERY and passing each response page to
normalize_page().
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


GUMTREE_KEYS = (
    "gumtree_policy",
    "gumtree_priority",
    "gumtree_min_stock",
    "gumtree_stockout_policy",
    "gumtree_stockout_grace_days",
    "gumtree_price_override",
    "gumtree_title_override",
    "gumtree_description_override",
    "gumtree_desired_listing_count",
    "gumtree_campaign_start",
    "gumtree_campaign_end",
)

SHOPIFY_PRODUCTS_QUERY = r"""
query GumtreeProducts($first: Int!, $after: String) {
  products(first: $first, after: $after, sortKey: ID) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      legacyResourceId
      title
      handle
      productType
      status
      totalInventory
      tracksInventory
      onlineStoreUrl
      priceRangeV2 {
        minVariantPrice { amount currencyCode }
        maxVariantPrice { amount currencyCode }
      }
      metafields(keys: [
        "nta.gumtree_policy",
        "nta.gumtree_priority",
        "nta.gumtree_min_stock",
        "nta.gumtree_stockout_policy",
        "nta.gumtree_stockout_grace_days",
        "nta.gumtree_price_override",
        "nta.gumtree_title_override",
        "nta.gumtree_description_override",
        "nta.gumtree_desired_listing_count",
        "nta.gumtree_campaign_start",
        "nta.gumtree_campaign_end"
      ], first: 20) {
        nodes { namespace key value type }
      }
    }
  }
}
""".strip()

INTEGER_KEYS = {
    "gumtree_min_stock",
    "gumtree_stockout_grace_days",
    "gumtree_desired_listing_count",
}
DECIMAL_KEYS = {"gumtree_price_override"}


def _parse_metafield(key: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if key in INTEGER_KEYS:
        try:
            return int(value)
        except (TypeError, ValueError):
            return value  # preserve invalid source value so validation can reject it
    if key in DECIMAL_KEYS:
        try:
            return str(Decimal(str(value)))
        except (InvalidOperation, TypeError, ValueError):
            return value
    return value


def normalize_product(node: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a Shopify Product node into the Phase 1A normalized contract."""
    raw_metafields = (node.get("metafields") or {}).get("nodes") or []
    gumtree = {key: None for key in GUMTREE_KEYS}
    for metafield in raw_metafields:
        if metafield.get("namespace") != "nta":
            continue
        key = metafield.get("key")
        if key in gumtree:
            gumtree[key] = _parse_metafield(key, metafield.get("value"))

    price_range = node.get("priceRangeV2") or {}
    min_price = price_range.get("minVariantPrice") or {}
    max_price = price_range.get("maxVariantPrice") or {}

    return {
        "shopify_product_id": node.get("legacyResourceId") or node.get("id"),
        "shopify_gid": node.get("id"),
        "title": node.get("title", ""),
        "handle": node.get("handle", ""),
        "product_type": node.get("productType", ""),
        "status": node.get("status"),
        "inventory": node.get("totalInventory"),
        "tracks_inventory": node.get("tracksInventory"),
        "online_store_url": node.get("onlineStoreUrl"),
        "price": min_price.get("amount"),
        "max_price": max_price.get("amount"),
        "currency": min_price.get("currencyCode"),
        "gumtree": gumtree,
    }


def normalize_page(payload: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Normalize one Shopify GraphQL page and return products plus pageInfo."""
    products = ((payload.get("data") or {}).get("products") or {})
    nodes = products.get("nodes") or []
    page_info = products.get("pageInfo") or {}
    return [normalize_product(node) for node in nodes], {
        "has_next_page": bool(page_info.get("hasNextPage")),
        "end_cursor": page_info.get("endCursor"),
    }
