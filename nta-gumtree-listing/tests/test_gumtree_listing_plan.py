import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from gumtree_listing_plan import browser_execution_allowed, build_listing_plan  # noqa: E402


def snapshot(**listing_overrides):
    listing = {
        "title": "Red Cherry Shrimp",
        "description": "Healthy aquarium shrimp available from Nano Tanks Australia.",
        "price": "5.00",
        "category": "Fish & Aquariums",
        "location": "Croydon NSW",
        "image_urls": ["https://example.com/rcs.jpg"],
        "attributes": {"Type": "Shrimp"},
        "source_fingerprint": "abc123",
    }
    listing.update(listing_overrides)
    return {
        "product": {"shopify_product_id": "6840207540433"},
        "advertisement": {"ad_id": "GT-NTA-000001"},
        "listing_input": listing,
    }


def test_create_draft_can_be_ready():
    plan = build_listing_plan(snapshot(), {"action": "CREATE_DRAFT"})
    assert plan.plan_status == "READY"
    assert browser_execution_allowed(plan) is True


def test_update_draft_can_be_ready():
    plan = build_listing_plan(snapshot(), {"action": "UPDATE_DRAFT"})
    assert plan.plan_status == "READY"
    assert browser_execution_allowed(plan) is True


def test_review_action_is_not_executable_even_with_complete_fields():
    plan = build_listing_plan(snapshot(), {"action": "UPDATE_ACTIVE_REVIEW"})
    assert plan.plan_status == "NOT_APPLICABLE"
    assert browser_execution_allowed(plan) is False


def test_publish_can_never_become_executable():
    plan = build_listing_plan(snapshot(), {"action": "PUBLISH"})
    assert plan.plan_status == "NOT_APPLICABLE"
    assert browser_execution_allowed(plan) is False


def test_missing_required_fields_blocks_plan():
    plan = build_listing_plan(
        snapshot(title="", description="", price="0", category="", location="", image_urls=[], source_fingerprint=""),
        {"action": "CREATE_DRAFT"},
    )
    assert plan.plan_status == "BLOCKED"
    assert {
        "MISSING_TITLE",
        "MISSING_DESCRIPTION",
        "INVALID_PRICE",
        "MISSING_CATEGORY",
        "MISSING_LOCATION",
        "MISSING_VALID_IMAGE",
        "MISSING_SOURCE_FINGERPRINT",
    }.issubset(set(plan.blocking_reasons))
    assert browser_execution_allowed(plan) is False


def test_invalid_price_formats_block():
    assert build_listing_plan(snapshot(price="free"), {"action": "CREATE_DRAFT"}).plan_status == "BLOCKED"
    assert build_listing_plan(snapshot(price="-1"), {"action": "CREATE_DRAFT"}).plan_status == "BLOCKED"


def test_currency_price_is_normalized():
    plan = build_listing_plan(snapshot(price="$1,234.5"), {"action": "CREATE_DRAFT"})
    assert plan.price == "1234.50"
    assert plan.plan_status == "READY"


def test_invalid_image_urls_do_not_count():
    plan = build_listing_plan(snapshot(image_urls=["file:///tmp/a.jpg", "not-a-url"]), {"action": "CREATE_DRAFT"})
    assert plan.plan_status == "BLOCKED"
    assert "MISSING_VALID_IMAGE" in plan.blocking_reasons


def test_identity_uncertainty_blocks_ready_plan():
    plan = build_listing_plan(snapshot(identity_uncertain=True), {"action": "CREATE_DRAFT"})
    assert plan.plan_status == "BLOCKED"
    assert "IDENTITY_UNCERTAIN" in plan.blocking_reasons


def test_stale_or_anomalous_source_blocks_plan():
    stale = build_listing_plan(snapshot(snapshot_stale=True), {"action": "CREATE_DRAFT"})
    anomalous = build_listing_plan(snapshot(snapshot_anomalous=True), {"action": "CREATE_DRAFT"})
    assert "SOURCE_SNAPSHOT_UNSAFE" in stale.blocking_reasons
    assert "SOURCE_SNAPSHOT_UNSAFE" in anomalous.blocking_reasons


def test_duplicate_suspicion_blocks_plan():
    plan = build_listing_plan(snapshot(duplicate_suspected=True), {"action": "CREATE_DRAFT"})
    assert plan.plan_status == "BLOCKED"
    assert "DUPLICATE_SUSPECTED" in plan.blocking_reasons


def test_missing_ad_or_product_identity_blocks():
    data = snapshot()
    data["product"] = {}
    data["advertisement"] = {}
    plan = build_listing_plan(data, {"action": "CREATE_DRAFT"})
    assert "MISSING_AD_ID" in plan.blocking_reasons
    assert "MISSING_PRODUCT_ID" in plan.blocking_reasons


def test_title_length_is_bounded():
    plan = build_listing_plan(snapshot(title="x" * 101), {"action": "CREATE_DRAFT"})
    assert "TITLE_TOO_LONG" in plan.blocking_reasons


def test_plan_is_deterministic_for_identical_input():
    one = build_listing_plan(snapshot(), {"action": "CREATE_DRAFT"}).as_dict()
    two = build_listing_plan(snapshot(), {"action": "CREATE_DRAFT"}).as_dict()
    assert one == two


def test_browser_gate_rejects_forged_ready_review_plan():
    assert browser_execution_allowed({"plan_status": "READY", "action": "PAUSE_REVIEW"}) is False
