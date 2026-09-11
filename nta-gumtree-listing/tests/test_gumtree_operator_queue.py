import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from gumtree_operator_queue import build_operator_queue, mark_posted, mark_verified  # noqa: E402


def snap(
    *,
    ad_id="GT-NTA-000001",
    product_id="6840207540433",
    priority="NORMAL",
    management_state="MANAGED",
    actual_state="MISSING",
    dirty_flags=None,
    title="Red Cherry Shrimp",
):
    return {
        "run_id": "run-1",
        "product": {
            "shopify_product_id": product_id,
            "config_state": "CONFIGURED",
            "management_state": management_state,
            "policy": "WHEN_IN_STOCK",
            "priority": priority,
            "availability_status": "AVAILABLE",
        },
        "resolved_policy": {
            "config_state": "CONFIGURED",
            "policy": "WHEN_IN_STOCK",
            "priority": priority,
            "availability_status": "AVAILABLE",
        },
        "advertisement": {
            "ad_id": ad_id,
            "management_state": management_state,
            "dirty_flags": dirty_flags or [],
        },
        "gumtree_state": {
            "actual_state": actual_state,
            "matching_instance_count": 1,
        },
        "listing_input": {
            "title": title,
            "description": f"{title} available from Nano Tanks Australia.",
            "price": "5.00",
            "category": "Fish & Aquariums",
            "location": "Croydon NSW",
            "image_urls": ["https://example.com/item.jpg"],
            "attributes": {"Seller": "Nano Tanks Australia"},
            "source_fingerprint": f"fp-{product_id}",
        },
    }


def test_thursday_builds_ready_to_post_package():
    result = build_operator_queue([snap()], run_date="2026-09-10")
    assert result["allowed_day"] is True
    assert result["publish_authority"] is False
    assert result["browser_automation"] is False
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["status"] == "READY_TO_POST"
    assert item["title"] == "Red Cherry Shrimp"
    assert item["price"] == "5.00"
    assert item["category"] == "Fish & Aquariums"
    assert item["location"] == "Croydon NSW"
    assert item["image_urls"] == ["https://example.com/item.jpg"]


@pytest.mark.parametrize("run_date", ["2026-09-06", "2026-09-07", "2026-09-08", "2026-09-09"])
def test_sunday_to_wednesday_generate_no_queue(run_date):
    result = build_operator_queue([snap()], run_date=run_date)
    assert result["allowed_day"] is False
    assert result["items"] == []


@pytest.mark.parametrize("run_date", ["2026-09-10", "2026-09-11", "2026-09-12"])
def test_thursday_friday_saturday_are_allowed(run_date):
    assert build_operator_queue([], run_date=run_date)["allowed_day"] is True


def test_hard_cap_is_three_even_if_caller_requests_more():
    snapshots = [
        snap(ad_id=f"GT-NTA-{index:06d}", product_id=str(index))
        for index in range(1, 6)
    ]
    result = build_operator_queue(snapshots, run_date="2026-09-11", max_items=99)
    assert result["max_items"] == 3
    assert len(result["items"]) == 3


def test_zero_items_is_valid_when_nothing_is_worthwhile():
    result = build_operator_queue([snap(actual_state="ACTIVE")], run_date="2026-09-11")
    assert result["items"] == []


def test_priority_orders_core_traffic_before_high_normal_low():
    snapshots = [
        snap(ad_id="GT-LOW", product_id="4", priority="LOW", title="Low"),
        snap(ad_id="GT-HIGH", product_id="2", priority="HIGH", title="High"),
        snap(ad_id="GT-CORE", product_id="1", priority="CORE_TRAFFIC", title="Core"),
        snap(ad_id="GT-NORMAL", product_id="3", priority="NORMAL", title="Normal"),
    ]
    result = build_operator_queue(snapshots, run_date="2026-09-12")
    assert [item["priority"] for item in result["items"]] == ["CORE_TRAFFIC", "HIGH", "NORMAL"]


def test_mapped_and_managed_identity_can_enter_manual_queue():
    mapped = build_operator_queue([snap(management_state="MAPPED")], run_date="2026-09-10")
    managed = build_operator_queue([snap(management_state="MANAGED")], run_date="2026-09-10")
    assert len(mapped["items"]) == 1
    assert len(managed["items"]) == 1


def test_unmapped_identity_is_skipped():
    result = build_operator_queue([snap(management_state="DISCOVERED")], run_date="2026-09-10")
    assert result["items"] == []
    assert result["skipped"] == 1


def test_review_actions_do_not_enter_operator_queue():
    result = build_operator_queue(
        [snap(actual_state="ACTIVE", dirty_flags=["PRICE_DIRTY"])],
        run_date="2026-09-10",
    )
    assert result["items"] == []


def test_duplicate_ad_id_is_not_queued_twice():
    result = build_operator_queue(
        [snap(product_id="1"), snap(product_id="2")],
        run_date="2026-09-10",
    )
    assert len(result["items"]) == 1


def test_malformed_snapshot_fails_closed_without_breaking_batch():
    good = snap()
    bad = {"advertisement": {"ad_id": "BROKEN"}}
    result = build_operator_queue([bad, good], run_date="2026-09-10")
    assert len(result["items"]) == 1
    assert result["skipped"] == 1


def test_ready_to_post_requires_manual_listing_reference_to_mark_posted():
    item = build_operator_queue([snap()], run_date="2026-09-10")["items"][0]
    with pytest.raises(ValueError):
        mark_posted(item)
    posted = mark_posted(item, gumtree_url="https://www.gumtree.com.au/s-ad/example/123")
    assert posted["status"] == "POSTED"
    assert posted["gumtree_url"].endswith("/123")


def test_posted_can_only_become_verified_after_explicit_success():
    item = build_operator_queue([snap()], run_date="2026-09-10")["items"][0]
    posted = mark_posted(item, gumtree_listing_id="123")
    with pytest.raises(ValueError):
        mark_verified(posted, verified=False)
    verified = mark_verified(posted, verified=True)
    assert verified["status"] == "VERIFIED"


def test_lifecycle_cannot_skip_states():
    item = build_operator_queue([snap()], run_date="2026-09-10")["items"][0]
    with pytest.raises(ValueError):
        mark_verified(item, verified=True)
    posted = mark_posted(item, gumtree_listing_id="123")
    with pytest.raises(ValueError):
        mark_posted(posted, gumtree_listing_id="456")
