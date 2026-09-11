import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from gumtree_availability import UNKNOWN, resolve_availability  # noqa: E402
from gumtree_listing_plan import build_listing_plan  # noqa: E402
from gumtree_manual_bootstrap import bootstrap_existing_listing  # noqa: E402
from gumtree_registry import initialize_registry  # noqa: E402


def test_featured_image_fallback_makes_plan_ready():
    snapshot = {
        "product": {
            "shopify_product_id": "6840207540433",
            "featured_image_url": "https://cdn.shopify.com/rcs.jpg",
        },
        "advertisement": {"ad_id": "GT-NTA-000001"},
        "listing_input": {
            "title": "Red Cherry Shrimp",
            "description": "Healthy Red Cherry Shrimp from Nano Tanks Australia.",
            "price": "5.00",
            "category": "Fish & Aquariums",
            "location": "Croydon NSW",
            "image_urls": [],
            "source_fingerprint": "fp-rcs",
        },
    }
    plan = build_listing_plan(snapshot, {"action": "CREATE_DRAFT"})
    assert plan.plan_status == "READY"
    assert plan.image_urls == ("https://cdn.shopify.com/rcs.jpg",)


def test_listing_images_still_take_precedence_over_featured_fallback():
    snapshot = {
        "product": {
            "shopify_product_id": "1",
            "featured_image_url": "https://cdn.shopify.com/fallback.jpg",
        },
        "advertisement": {"ad_id": "GT-NTA-000001"},
        "listing_input": {
            "title": "Item",
            "description": "Description",
            "price": "5.00",
            "category": "Fish & Aquariums",
            "location": "Croydon NSW",
            "image_urls": ["https://cdn.shopify.com/primary.jpg"],
            "source_fingerprint": "fp-1",
        },
    }
    plan = build_listing_plan(snapshot, {"action": "CREATE_DRAFT"})
    assert plan.image_urls == ("https://cdn.shopify.com/primary.jpg",)


def test_title_only_betta_identity_does_not_activate_unique_exception():
    product = {
        "title": "1BT11 - Halfmoon Betta Male",
        "handle": "1bt11-halfmoon-betta",
        "product_type": "Fish",
        "status": "ACTIVE",
        "inventory": 1,
        "tracks_inventory": False,
        "gumtree": {},
    }
    policy = {
        "gumtree_policy": "UNIQUE",
        "gumtree_min_stock": 1,
        "gumtree_stockout_policy": None,
    }
    result = resolve_availability(product, policy)
    assert result.status == UNKNOWN
    assert result.reason_code == "UNTRACKED_STOCK_DEPENDENT_POLICY"


def test_manual_bootstrap_records_operator_supplied_url_without_network(tmp_path):
    registry = initialize_registry(tmp_path / "gumtree.db")
    registry.upsert_advertisement({"ad_id": "GT-NTA-000001"})

    result = bootstrap_existing_listing(
        registry,
        ad_id="GT-NTA-000001",
        gumtree_url="https://www.gumtree.com.au/s-ad/croydon/fish/1234567890",
    )

    assert result.outcome == "BOOTSTRAPPED"
    assert result.gumtree_listing_id == "1234567890"
    instances = registry.list_instances("GT-NTA-000001")
    assert len(instances) == 1
    assert instances[0]["actual_state"] == "ACTIVE"
    assert instances[0]["is_canonical"] == 1


def test_manual_bootstrap_requires_existing_ad(tmp_path):
    registry = initialize_registry(tmp_path / "gumtree.db")
    with pytest.raises(ValueError, match="advertisement does not exist"):
        bootstrap_existing_listing(
            registry,
            ad_id="GT-NTA-MISSING",
            gumtree_listing_id="1234567890",
        )


def test_manual_bootstrap_rejects_unparseable_reference(tmp_path):
    registry = initialize_registry(tmp_path / "gumtree.db")
    registry.upsert_advertisement({"ad_id": "GT-NTA-000001"})
    with pytest.raises(ValueError, match="valid Gumtree listing ID or URL"):
        bootstrap_existing_listing(
            registry,
            ad_id="GT-NTA-000001",
            gumtree_url="https://www.gumtree.com.au/no-listing-id-here",
        )
