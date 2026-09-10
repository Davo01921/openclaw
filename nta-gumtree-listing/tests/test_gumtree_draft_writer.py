from __future__ import annotations

import pathlib
import sys

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from gumtree_draft_writer import execute_draft_plan


class FakeBrowser:
    def __init__(self, save_result=None, fail_on=None):
        self.calls = []
        self.save_result = save_result or {"saved_as_draft": True, "gumtree_listing_id": "12345"}
        self.fail_on = fail_on

    def _call(self, name, *args, **kwargs):
        if self.fail_on == name:
            raise RuntimeError("boom")
        self.calls.append((name, args, kwargs))

    def create_or_open_draft(self, **kwargs): self._call("create_or_open_draft", **kwargs)
    def set_title(self, value): self._call("set_title", value)
    def set_description(self, value): self._call("set_description", value)
    def set_price(self, value): self._call("set_price", value)
    def set_category(self, value): self._call("set_category", value)
    def set_location(self, value): self._call("set_location", value)
    def set_images(self, urls): self._call("set_images", tuple(urls))
    def set_attributes(self, attributes): self._call("set_attributes", dict(attributes))
    def save_draft(self):
        self._call("save_draft")
        return self.save_result


def ready_plan(action="CREATE_DRAFT"):
    return {
        "plan_status": "READY",
        "action": action,
        "ad_id": "GT-NTA-000001",
        "shopify_product_id": "gid://shopify/Product/1",
        "title": "Red Cherry Shrimp",
        "description": "Healthy aquarium shrimp. Pickup Croydon NSW.",
        "price": "5.00",
        "category": "Fish",
        "location": "Croydon NSW",
        "image_urls": ["https://example.com/shrimp.jpg"],
        "attributes": {"Type": "Shrimp"},
        "blocking_reasons": [],
        "source_fingerprint": "sha256:abc",
    }


def test_create_draft_ready_plan_saves_draft_only():
    browser = FakeBrowser()
    result = execute_draft_plan(ready_plan(), browser)
    assert result.status == "DRAFT_SAVED"
    assert result.gumtree_listing_id == "12345"
    assert result.verification_required is True
    assert [c[0] for c in browser.calls] == [
        "create_or_open_draft", "set_title", "set_description", "set_price",
        "set_category", "set_location", "set_images", "set_attributes", "save_draft"
    ]


def test_update_draft_is_allowed():
    browser = FakeBrowser()
    result = execute_draft_plan(ready_plan("UPDATE_DRAFT"), browser)
    assert result.status == "DRAFT_SAVED"


def test_review_action_is_blocked_before_browser():
    plan = ready_plan("UPDATE_ACTIVE_REVIEW")
    browser = FakeBrowser()
    result = execute_draft_plan(plan, browser)
    assert result.status == "BLOCKED"
    assert result.error_code == "PLAN_NOT_BROWSER_EXECUTABLE"
    assert browser.calls == []


def test_publish_action_is_blocked_before_browser():
    plan = ready_plan("PUBLISH")
    browser = FakeBrowser()
    result = execute_draft_plan(plan, browser)
    assert result.status == "BLOCKED"
    assert browser.calls == []


def test_blocked_plan_is_blocked_before_browser():
    plan = ready_plan()
    plan["plan_status"] = "BLOCKED"
    plan["blocking_reasons"] = ["MISSING_TITLE"]
    browser = FakeBrowser()
    result = execute_draft_plan(plan, browser)
    assert result.status == "BLOCKED"
    assert browser.calls == []


def test_missing_source_fingerprint_is_blocked():
    plan = ready_plan()
    plan["source_fingerprint"] = ""
    browser = FakeBrowser()
    result = execute_draft_plan(plan, browser)
    assert result.status == "BLOCKED"
    assert result.error_code == "MISSING_SOURCE_FINGERPRINT"
    assert browser.calls == []


def test_missing_image_is_blocked():
    plan = ready_plan()
    plan["image_urls"] = []
    browser = FakeBrowser()
    result = execute_draft_plan(plan, browser)
    assert result.status == "BLOCKED"
    assert result.error_code == "PLAN_IMAGES_INCOMPLETE"


def test_browser_failure_returns_error_not_success():
    browser = FakeBrowser(fail_on="set_price")
    result = execute_draft_plan(ready_plan(), browser)
    assert result.status == "ERROR"
    assert result.error_code == "BROWSER_DRAFT_WRITE_FAILED"
    assert result.verification_required is False


def test_unconfirmed_save_returns_error():
    browser = FakeBrowser(save_result={"saved_as_draft": False, "gumtree_listing_id": "12345"})
    result = execute_draft_plan(ready_plan(), browser)
    assert result.status == "ERROR"
    assert result.error_code == "DRAFT_SAVE_NOT_CONFIRMED"
    assert result.verification_required is True


def test_unexpected_publish_report_is_safety_error():
    browser = FakeBrowser(save_result={
        "saved_as_draft": True,
        "published": True,
        "gumtree_listing_id": "12345",
    })
    result = execute_draft_plan(ready_plan(), browser)
    assert result.status == "ERROR"
    assert result.error_code == "UNEXPECTED_PUBLISH_STATE"
    assert result.verification_required is True


def test_execution_is_deterministic_for_equivalent_plan():
    first_browser = FakeBrowser()
    second_browser = FakeBrowser()
    first = execute_draft_plan(ready_plan(), first_browser).as_dict()
    second = execute_draft_plan(ready_plan(), second_browser).as_dict()
    assert first == second
    assert first_browser.calls == second_browser.calls
