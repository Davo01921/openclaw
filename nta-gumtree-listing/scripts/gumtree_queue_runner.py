"""Production entry point for the NTA Gumtree manual-post workflow.

The runner consumes current normalized Shopify product records, combines them
with the local SQLite registry, builds deterministic snapshots, and emits the
live Thursday/Friday/Saturday operator queue. It never opens Gumtree, scrapes
Gumtree, publishes an ad, or purchases promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from gumtree_availability import resolve_availability
from gumtree_config import classify_product
from gumtree_census import extract_listing_id
from gumtree_operator_queue import build_live_operator_queue, mark_posted, mark_verified
from gumtree_registry import Registry, initialize_registry

DEFAULT_CATEGORY = "Fish"
DEFAULT_LOCATION = "Croydon NSW 2132"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _linked_ad(registry: Registry, product_id: str) -> tuple[dict[str, Any] | None, bool]:
    """Return the single preferred linked ad plus an ambiguity flag."""
    with registry.connect() as conn:
        rows = conn.execute(
            """
            SELECT a.*, l.relationship
            FROM product_ad_links l
            JOIN advertisements a ON a.ad_id = l.ad_id
            WHERE l.shopify_product_id = ?
            ORDER BY CASE WHEN l.relationship = 'PRIMARY' THEN 0 ELSE 1 END, a.ad_id
            """,
            (str(product_id),),
        ).fetchall()
    if not rows:
        return None, False
    primary = [dict(row) for row in rows if row["relationship"] == "PRIMARY"]
    if len(primary) == 1:
        return primary[0], len(rows) > 1 and len(primary) != len(rows)
    if len(rows) == 1:
        return dict(rows[0]), False
    return None, True


def _gumtree_state(registry: Registry, ad_id: str | None) -> dict[str, Any]:
    if not ad_id:
        return {"actual_state": "MISSING", "matching_instance_count": 0}
    with registry.connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM gumtree_instances
            WHERE ad_id = ?
            ORDER BY is_canonical DESC, instance_id DESC
            """,
            (ad_id,),
        ).fetchall()
    if not rows:
        return {"actual_state": "MISSING", "matching_instance_count": 0}
    canonical_live = [
        row for row in rows
        if row["is_canonical"] == 1 and row["actual_state"] in {"DRAFT", "ACTIVE", "PAUSED"}
    ]
    chosen = canonical_live[0] if canonical_live else rows[0]
    return {
        "actual_state": chosen["actual_state"],
        "gumtree_listing_id": chosen["gumtree_listing_id"],
        "url": chosen["url"],
        "matching_instance_count": len(canonical_live) if canonical_live else 1,
        "duplicate_suspected": len(canonical_live) > 1,
    }


def _listing_input(product: Mapping[str, Any], gumtree: Mapping[str, Any]) -> dict[str, Any]:
    supplied = dict(product.get("listing_input") or {})
    title = supplied.get("title") or gumtree.get("gumtree_title_override") or product.get("title")
    description = (
        supplied.get("description")
        or gumtree.get("gumtree_description_override")
        or product.get("description")
        or product.get("description_text")
    )
    price = supplied.get("price") or gumtree.get("gumtree_price_override") or product.get("price")
    image_urls = supplied.get("image_urls") or product.get("image_urls") or []
    featured_image_url = supplied.get("featured_image_url") or product.get("featured_image_url")
    attributes = supplied.get("attributes") or product.get("gumtree_attributes") or {}
    category = supplied.get("category") or product.get("gumtree_category") or DEFAULT_CATEGORY
    location = supplied.get("location") or product.get("gumtree_location") or DEFAULT_LOCATION

    fingerprint_payload = {
        "shopify_product_id": product.get("shopify_product_id"),
        "title": title,
        "description": description,
        "price": price,
        "image_urls": image_urls,
        "featured_image_url": featured_image_url,
        "attributes": attributes,
        "category": category,
        "location": location,
        "gumtree": gumtree,
    }
    return {
        "title": title,
        "description": description,
        "price": price,
        "category": category,
        "location": location,
        "image_urls": image_urls,
        "featured_image_url": featured_image_url,
        "attributes": attributes,
        "source_fingerprint": supplied.get("source_fingerprint") or _fingerprint(fingerprint_payload),
        "identity_uncertain": supplied.get("identity_uncertain") is True,
        "snapshot_stale": supplied.get("snapshot_stale") is True,
        "snapshot_anomalous": supplied.get("snapshot_anomalous") is True,
        "duplicate_suspected": supplied.get("duplicate_suspected") is True,
    }


def build_snapshot(product: Mapping[str, Any], registry: Registry) -> dict[str, Any]:
    """Combine one current Shopify product with registry state.

    The caller must provide current Shopify data through the approved/read-only
    adapter boundary. Missing content remains missing and is blocked later by the
    listing-plan validator; this function never invents facts.
    """
    product = dict(product)
    product_id = str(product.get("shopify_product_id") or "").strip()
    if not product_id:
        raise ValueError("shopify_product_id is required")

    config = classify_product(product)
    gumtree = dict(product.get("gumtree") or {})
    raw_policy = {
        "gumtree_policy": gumtree.get("gumtree_policy"),
        "gumtree_priority": gumtree.get("gumtree_priority"),
        "gumtree_min_stock": gumtree.get("gumtree_min_stock"),
        "gumtree_stockout_policy": gumtree.get("gumtree_stockout_policy"),
        "gumtree_stockout_grace_days": gumtree.get("gumtree_stockout_grace_days"),
    }
    availability = resolve_availability(product, raw_policy)

    cached = registry.get_product(product_id) or {}
    management_state = cached.get("management_state") or product.get("management_state") or "DISCOVERED"
    registry.upsert_product({
        **product,
        "shopify_product_id": product_id,
        "management_state": management_state,
        "config_state": config.config_state,
        "policy": gumtree.get("gumtree_policy"),
        "priority": gumtree.get("gumtree_priority") or "NORMAL",
        "availability_status": availability.status,
    })

    ad, ambiguous = _linked_ad(registry, product_id)
    ad_id = ad.get("ad_id") if ad else None
    advertisement = dict(ad or {})
    advertisement.update({
        "ad_id": ad_id,
        "management_state": management_state,
        "identity_uncertain": ambiguous,
        "dirty_flags": product.get("dirty_flags") or [],
    })

    resolved_policy = {
        "config_state": config.config_state,
        "policy": gumtree.get("gumtree_policy"),
        "gumtree_policy": gumtree.get("gumtree_policy"),
        "priority": gumtree.get("gumtree_priority") or "NORMAL",
        "availability_status": availability.status,
        **raw_policy,
    }

    product_snapshot = dict(product)
    product_snapshot.update({
        "config_state": config.config_state,
        "management_state": management_state,
        "policy": gumtree.get("gumtree_policy"),
        "priority": gumtree.get("gumtree_priority") or "NORMAL",
        "availability_status": availability.status,
    })

    return {
        "product": product_snapshot,
        "resolved_policy": resolved_policy,
        "advertisement": advertisement,
        "gumtree_state": _gumtree_state(registry, ad_id),
        "listing_input": _listing_input(product, gumtree),
    }


def prepare_live_queue(
    products: Iterable[Mapping[str, Any]],
    registry: Registry,
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build and optionally persist today's live manual-post operator queue."""
    snapshots = []
    snapshot_errors = []
    for product in products:
        try:
            snapshots.append(build_snapshot(product, registry))
        except Exception as exc:
            snapshot_errors.append({
                "shopify_product_id": _text(product.get("shopify_product_id")),
                "error": str(exc),
            })

    queue = build_live_operator_queue(snapshots)
    queue["snapshot_errors"] = snapshot_errors
    queue["manual_post_only"] = True
    queue["publish_authority"] = False
    queue["browser_automation"] = False

    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(queue, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        queue["artifact_path"] = str(path)
    return queue


def record_manual_post(
    registry: Registry,
    item: Mapping[str, Any],
    *,
    gumtree_listing_id: str | None = None,
    gumtree_url: str | None = None,
) -> dict[str, Any]:
    """Record David's completed manual Gumtree post in the registry."""
    posted = mark_posted(item, gumtree_listing_id=gumtree_listing_id, gumtree_url=gumtree_url)
    listing_id = extract_listing_id({
        "gumtree_listing_id": gumtree_listing_id,
        "url": gumtree_url,
    })
    if not listing_id:
        raise ValueError("valid Gumtree listing ID or URL is required")
    instance_id = registry.record_instance({
        "ad_id": str(item["ad_id"]),
        "gumtree_listing_id": listing_id,
        "url": gumtree_url,
        "actual_state": "ACTIVE",
        "is_canonical": True,
        "source": "MANUAL_OPERATOR",
        "title": item.get("title"),
        "price": item.get("price"),
        "content_fingerprint": item.get("source_fingerprint"),
    })
    posted["gumtree_listing_id"] = listing_id
    posted["instance_id"] = instance_id
    return posted


def record_manual_verification(item: Mapping[str, Any], *, verified: bool) -> dict[str, Any]:
    """Advance POSTED to VERIFIED only after explicit human verification."""
    return mark_verified(item, verified=verified)


def _load_products(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, Mapping) and isinstance(payload.get("products"), list):
        return list(payload["products"])
    raise ValueError("input JSON must be a product list or an object containing products[]")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare the NTA Gumtree manual-post queue")
    parser.add_argument("--input", required=True, help="Current normalized Shopify product JSON")
    parser.add_argument("--db", default="data/gumtree.db", help="SQLite registry path")
    parser.add_argument("--output", default="data/operator-queue.json", help="Queue artifact path")
    args = parser.parse_args(argv)

    registry = initialize_registry(args.db)
    queue = prepare_live_queue(_load_products(Path(args.input)), registry, output_path=args.output)
    print(json.dumps(queue, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
