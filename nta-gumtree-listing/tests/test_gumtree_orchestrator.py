from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from gumtree_orchestrator import build_dashboard_snapshot, run_cycle


class FakeBrowser:
    def __init__(self, listing_id="GT-123"):
        self.listing_id = listing_id
        self.calls = []

    def create_or_open_draft(self, *, action, ad_id): self.calls.append(("open", action, ad_id))
    def set_title(self, value): self.calls.append(("title", value))
    def set_description(self, value): self.calls.append(("description", value))
    def set_price(self, value): self.calls.append(("price", value))
    def set_category(self, value): self.calls.append(("category", value))
    def set_location(self, value): self.calls.append(("location", value))
    def set_images(self, urls): self.calls.append(("images", tuple(urls)))
    def set_attributes(self, attributes): self.calls.append(("attributes", dict(attributes)))
    def save_draft(self):
        self.calls.append(("save_draft",))
        return {"saved_as_draft": True, "published": False, "gumtree_listing_id": self.listing_id}


def ready_snapshot(management_state="MANAGED", actual_state="MISSING"):
    return {
        "product": {
            "shopify_product_id": "gid://shopify/Product/1",
            "config_state": "CONFIGURED",
            "management_state": management_state,
        },
        "resolved_policy": {
            "policy": "WHEN_IN_STOCK",
            "availability_status": "AVAILABLE",
            "config_state": "CONFIGURED",
        },
        "advertisement": {
            "ad_id": "GT-NTA-000001",
            "management_state": management_state,
            "dirty_flags": [],
        },
        "gumtree_state": {
            "actual_state": actual_state,
            "matching_instance_count": 1,
        },
        "listing_input": {
            "title": "Red Cherry Shrimp",
            "description": "Healthy aquarium shrimp available from NTA.",
            "price": "5.00",
            "category": "Fish & Aquariums",
            "location": "Croydon NSW",
            "image_urls": ["https://example.com/shrimp.jpg"],
            "attributes": {"Type": "Shrimp"},
            "source_fingerprint": "fp-1",
        },
    }


def observed_from(plan, listing_id="GT-123"):
    return {
        "gumtree_listing_id": listing_id,
        "actual_state": "DRAFT",
        "published": False,
        "title": plan["title"],
        "description": plan["description"],
        "price": plan["price"],
        "category": plan["category"],
        "location": plan["location"],
        "image_urls": plan["image_urls"],
        "attributes": plan["attributes"],
        "source_fingerprint": plan["source_fingerprint"],
    }


def test_dry_run_never_calls_browser():
    called = []

    def factory(snapshot, plan):
        called.append(True)
        return FakeBrowser()

    result = run_cycle([ready_snapshot()], execute_drafts=False, browser_factory=factory)
    item = result["items"][0]
    assert item["reconciliation_action"] == "CREATE_DRAFT"
    assert item["plan_status"] == "READY"
    assert item["execution_status"] == "NOT_EXECUTED"
    assert called == []


def test_mapped_ad_cannot_auto_execute():
    called = []

    def factory(snapshot, plan):
        called.append(True)
        return FakeBrowser()

    result = run_cycle([ready_snapshot("MAPPED")], execute_drafts=True, browser_factory=factory)
    item = result["items"][0]
    assert item["execution_status"] == "BLOCKED"
    assert item["error_code"] == "MANAGEMENT_STATE_NOT_MANAGED"
    assert item["review_required"] is True
    assert called == []


def test_managed_ready_plan_saves_and_verifies():
    browser = FakeBrowser()

    def factory(snapshot, plan):
        return browser

    def observer(snapshot, plan, write_result):
        return observed_from(plan, write_result["gumtree_listing_id"])

    result = run_cycle(
        [ready_snapshot()],
        execute_drafts=True,
        browser_factory=factory,
        observe_draft=observer,
    )
    item = result["items"][0]
    assert item["execution_status"] == "DRAFT_SAVED"
    assert item["verification_status"] == "VERIFIED"
    assert item["review_required"] is False
    assert browser.calls[-1] == ("save_draft",)
    assert result["dashboard"]["verification"]["verified"] == 1


def test_saved_draft_without_observer_is_not_healthy():
    result = run_cycle(
        [ready_snapshot()],
        execute_drafts=True,
        browser_factory=lambda snapshot, plan: FakeBrowser(),
    )
    item = result["items"][0]
    assert item["execution_status"] == "DRAFT_SAVED"
    assert item["verification_status"] == "ERROR"
    assert item["error_code"] == "VERIFICATION_OBSERVER_UNAVAILABLE"
    assert result["dashboard"]["healthy"] is False


def test_review_action_never_reaches_browser():
    snapshot = ready_snapshot()
    snapshot["resolved_policy"]["availability_status"] = "UNAVAILABLE"
    snapshot["gumtree_state"]["actual_state"] = "ACTIVE"
    called = []

    def factory(snapshot, plan):
        called.append(True)
        return FakeBrowser()

    result = run_cycle([snapshot], execute_drafts=True, browser_factory=factory)
    item = result["items"][0]
    assert item["reconciliation_action"] == "PAUSE_REVIEW"
    assert item["execution_status"] == "NOT_EXECUTABLE"
    assert item["review_required"] is True
    assert called == []


def test_bad_input_fails_closed_per_item():
    bad = {"product": {"config_state": "CONFIGURED"}, "gumtree_state": {"matching_instance_count": "not-a-number"}}
    result = run_cycle([bad], execute_drafts=True)
    item = result["items"][0]
    assert item["execution_status"] == "ERROR"
    assert item["review_required"] is True
    assert item["error_code"] == "ORCHESTRATION_INPUT_ERROR"


def test_dashboard_never_grants_publish_or_active_change_authority():
    dashboard = build_dashboard_snapshot([])
    assert dashboard["publish_authority"] is False
    assert dashboard["paid_promotion_authority"] is False
    assert dashboard["automatic_active_listing_changes"] is False


def test_verification_mismatch_surfaces_in_dashboard():
    def observer(snapshot, plan, write_result):
        observed = observed_from(plan, write_result["gumtree_listing_id"])
        observed["price"] = "999.00"
        return observed

    result = run_cycle(
        [ready_snapshot()],
        execute_drafts=True,
        browser_factory=lambda snapshot, plan: FakeBrowser(),
        observe_draft=observer,
    )
    item = result["items"][0]
    assert item["verification_status"] == "MISMATCH"
    assert item["review_required"] is True
    assert result["dashboard"]["verification"]["mismatch_codes"]["PRICE_MISMATCH"] == 1
    assert result["dashboard"]["healthy"] is False
