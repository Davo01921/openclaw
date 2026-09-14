import json
import sys
from datetime import date
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import gumtree_operator_queue  # noqa: E402
from gumtree_queue_runner import (  # noqa: E402
    build_snapshot,
    prepare_live_queue,
    record_manual_post,
    record_manual_verification,
)
from gumtree_registry import initialize_registry  # noqa: E402
from gumtree_registry_backup import backup_registry  # noqa: E402


def current_product(product_id="123", **overrides):
    data = {
        "shopify_product_id": product_id,
        "shopify_gid": f"gid://shopify/Product/{product_id}",
        "title": "Red Cherry Shrimp 1-3cm",
        "handle": "red-cherry-shrimp",
        "product_type": "Shrimps",
        "status": "ACTIVE",
        "inventory": 25,
        "tracks_inventory": True,
        "price": "5.00",
        "description": "Healthy freshwater shrimp from Nano Tanks Australia.",
        "featured_image_url": "https://cdn.shopify.com/rcs.jpg",
        "gumtree_attributes": {"type": "Crustacea", "gender": "Both", "quantity": "1"},
        "gumtree": {
            "gumtree_policy": "WHEN_IN_STOCK",
            "gumtree_priority": "HIGH",
            "gumtree_min_stock": 10,
            "gumtree_stockout_policy": "PAUSE",
        },
    }
    data.update(overrides)
    return data


def seeded_registry(tmp_path, product_id="123", ad_id="GT-NTA-000001"):
    registry = initialize_registry(tmp_path / "gumtree.db")
    registry.upsert_product({
        "shopify_product_id": product_id,
        "title": "seed",
        "management_state": "MAPPED",
    })
    registry.upsert_advertisement({"ad_id": ad_id})
    registry.link_product_ad(product_id, ad_id)
    return registry


def test_build_snapshot_combines_shopify_config_registry_and_missing_state(tmp_path):
    registry = seeded_registry(tmp_path)
    snapshot = build_snapshot(current_product(), registry)
    assert snapshot["product"]["config_state"] == "CONFIGURED"
    assert snapshot["product"]["availability_status"] == "AVAILABLE"
    assert snapshot["advertisement"]["ad_id"] == "GT-NTA-000001"
    assert snapshot["advertisement"]["management_state"] == "MAPPED"
    assert snapshot["gumtree_state"]["actual_state"] == "MISSING"
    assert snapshot["listing_input"]["title"] == "Red Cherry Shrimp 1-3cm"
    assert snapshot["listing_input"]["featured_image_url"].endswith("rcs.jpg")


def test_live_runner_uses_sydney_day_and_writes_manual_only_artifact(tmp_path, monkeypatch):
    registry = seeded_registry(tmp_path)
    monkeypatch.setattr(gumtree_operator_queue, "_current_sydney_date", lambda: date(2026, 9, 17))
    output = tmp_path / "queue.json"

    queue = prepare_live_queue([current_product()], registry, output_path=output)

    assert queue["run_date"] == "2026-09-17"
    assert queue["allowed_day"] is True
    assert len(queue["items"]) == 1
    assert queue["items"][0]["status"] == "READY_TO_POST"
    assert queue["items"][0]["ad_id"] == "GT-NTA-000001"
    assert queue["publish_authority"] is False
    assert queue["browser_automation"] is False
    assert queue["manual_post_only"] is True
    persisted = json.loads(output.read_text())
    assert persisted["manual_post_only"] is True


def test_live_runner_sunday_is_empty_even_with_valid_candidate(tmp_path, monkeypatch):
    registry = seeded_registry(tmp_path)
    monkeypatch.setattr(gumtree_operator_queue, "_current_sydney_date", lambda: date(2026, 9, 13))
    queue = prepare_live_queue([current_product()], registry)
    assert queue["allowed_day"] is False
    assert queue["items"] == []


def test_missing_description_fails_closed_without_queue_item(tmp_path, monkeypatch):
    registry = seeded_registry(tmp_path)
    monkeypatch.setattr(gumtree_operator_queue, "_current_sydney_date", lambda: date(2026, 9, 17))
    queue = prepare_live_queue([current_product(description=None)], registry)
    assert queue["items"] == []
    assert queue["skipped"] >= 1


def test_unmapped_product_cannot_enter_operator_queue(tmp_path, monkeypatch):
    registry = initialize_registry(tmp_path / "gumtree.db")
    registry.upsert_product({"shopify_product_id": "123", "title": "seed", "management_state": "DISCOVERED"})
    registry.upsert_advertisement({"ad_id": "GT-NTA-000001"})
    registry.link_product_ad("123", "GT-NTA-000001")
    monkeypatch.setattr(gumtree_operator_queue, "_current_sydney_date", lambda: date(2026, 9, 17))
    queue = prepare_live_queue([current_product()], registry)
    assert queue["items"] == []


def test_manual_post_and_verification_update_registry_without_gumtree_access(tmp_path):
    registry = seeded_registry(tmp_path)
    item = {
        "status": "READY_TO_POST",
        "ad_id": "GT-NTA-000001",
        "title": "Red Cherry Shrimp",
        "price": "5.00",
        "source_fingerprint": "abc123",
    }
    posted = record_manual_post(
        registry,
        item,
        gumtree_url="https://www.gumtree.com.au/s-ad/1344082647",
    )
    assert posted["status"] == "POSTED"
    assert posted["gumtree_listing_id"] == "1344082647"
    instances = registry.list_instances("GT-NTA-000001")
    assert instances[0]["source"] == "MANUAL_OPERATOR"
    assert instances[0]["actual_state"] == "ACTIVE"

    verified = record_manual_verification(posted, verified=True)
    assert verified["status"] == "VERIFIED"


def test_manual_post_rejects_listing_id_owned_by_other_ad(tmp_path):
    registry = seeded_registry(tmp_path)
    registry.upsert_advertisement({"ad_id": "GT-NTA-000002"})
    registry.record_instance({
        "ad_id": "GT-NTA-000002",
        "gumtree_listing_id": "1344082647",
        "actual_state": "ACTIVE",
        "source": "MANUAL_OPERATOR",
    })
    item = {"status": "READY_TO_POST", "ad_id": "GT-NTA-000001"}
    with pytest.raises(ValueError, match="cannot be remapped"):
        record_manual_post(registry, item, gumtree_listing_id="1344082647")


def test_registry_backup_is_readable_copy(tmp_path):
    registry = seeded_registry(tmp_path)
    backup = backup_registry(registry.db_path, tmp_path / "backups")
    assert backup.exists()
    copied = initialize_registry(backup)
    assert copied.get_product("123")["management_state"] == "MAPPED"
