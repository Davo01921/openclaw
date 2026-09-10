"""Draft-only execution layer for NTA Gumtree automation.

Phase 6 accepts only a Phase 5 READY listing plan and converts it into a
strict sequence of browser-facing draft operations. It does not publish,
promote, pause, remove, relist, or modify active listings.

The browser adapter is deliberately tiny: the writer supplies already-validated
values and asks the adapter to save a draft. Business rules remain upstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from gumtree_listing_plan import browser_execution_allowed

ALLOWED_ACTIONS = {"CREATE_DRAFT", "UPDATE_DRAFT"}


class DraftBrowser(Protocol):
    """Minimal browser contract for Phase 6.

    Implementations may navigate Gumtree, fill fields and save a draft, but the
    interface intentionally exposes no publish/promotion/active-listing actions.
    """

    def create_or_open_draft(self, *, action: str, ad_id: str) -> None: ...

    def set_title(self, value: str) -> None: ...

    def set_description(self, value: str) -> None: ...

    def set_price(self, value: str) -> None: ...

    def set_category(self, value: str) -> None: ...

    def set_location(self, value: str) -> None: ...

    def set_images(self, urls: Sequence[str]) -> None: ...

    def set_attributes(self, attributes: Mapping[str, str]) -> None: ...

    def save_draft(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class DraftWriteResult:
    status: str
    action: str
    ad_id: str | None
    gumtree_listing_id: str | None
    verification_required: bool
    error_code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "action": self.action,
            "ad_id": self.ad_id,
            "gumtree_listing_id": self.gumtree_listing_id,
            "verification_required": self.verification_required,
            "error_code": self.error_code,
        }


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _preflight(plan: Mapping[str, Any]) -> str | None:
    """Return a blocking code or None.

    Phase 5 remains the authority for listing validation. These checks defend
    against forged or mutated plans reaching the browser boundary.
    """
    if not browser_execution_allowed(plan):
        return "PLAN_NOT_BROWSER_EXECUTABLE"
    if plan.get("action") not in ALLOWED_ACTIONS:
        return "ACTION_NOT_ALLOWED"
    if plan.get("blocking_reasons"):
        return "PLAN_HAS_BLOCKERS"
    if not _text(plan.get("ad_id")):
        return "MISSING_AD_ID"
    if not _text(plan.get("source_fingerprint")):
        return "MISSING_SOURCE_FINGERPRINT"

    required = ("title", "description", "price", "category", "location")
    if any(not _text(plan.get(field)) for field in required):
        return "PLAN_FIELDS_INCOMPLETE"

    images = plan.get("image_urls")
    if not isinstance(images, (list, tuple)) or not images:
        return "PLAN_IMAGES_INCOMPLETE"

    return None


def execute_draft_plan(plan: Mapping[str, Any], browser: DraftBrowser) -> DraftWriteResult:
    """Execute a validated Phase 5 plan as SAVE DRAFT only.

    Success means Gumtree reported a draft save. It does not mean the draft has
    been independently verified; Phase 6 therefore always returns
    verification_required=True after a save.
    """
    action = _text(plan.get("action")) or "ERROR"
    ad_id = _text(plan.get("ad_id"))

    blocker = _preflight(plan)
    if blocker:
        return DraftWriteResult(
            status="BLOCKED",
            action=action,
            ad_id=ad_id,
            gumtree_listing_id=None,
            verification_required=False,
            error_code=blocker,
        )

    try:
        browser.create_or_open_draft(action=action, ad_id=ad_id or "")
        browser.set_title(str(plan["title"]))
        browser.set_description(str(plan["description"]))
        browser.set_price(str(plan["price"]))
        browser.set_category(str(plan["category"]))
        browser.set_location(str(plan["location"]))
        browser.set_images(tuple(str(x) for x in plan["image_urls"]))

        raw_attributes = plan.get("attributes") or {}
        attributes = (
            {str(k): str(v) for k, v in raw_attributes.items()}
            if isinstance(raw_attributes, Mapping)
            else {}
        )
        browser.set_attributes(attributes)

        saved = browser.save_draft() or {}
    except Exception:
        return DraftWriteResult(
            status="ERROR",
            action=action,
            ad_id=ad_id,
            gumtree_listing_id=None,
            verification_required=False,
            error_code="BROWSER_DRAFT_WRITE_FAILED",
        )

    if saved.get("published") is True:
        # A compliant adapter must never publish. Treat any such report as a
        # hard safety breach, not a success.
        return DraftWriteResult(
            status="ERROR",
            action=action,
            ad_id=ad_id,
            gumtree_listing_id=_text(saved.get("gumtree_listing_id")),
            verification_required=True,
            error_code="UNEXPECTED_PUBLISH_STATE",
        )

    if saved.get("saved_as_draft") is not True:
        return DraftWriteResult(
            status="ERROR",
            action=action,
            ad_id=ad_id,
            gumtree_listing_id=_text(saved.get("gumtree_listing_id")),
            verification_required=True,
            error_code="DRAFT_SAVE_NOT_CONFIRMED",
        )

    return DraftWriteResult(
        status="DRAFT_SAVED",
        action=action,
        ad_id=ad_id,
        gumtree_listing_id=_text(saved.get("gumtree_listing_id")),
        verification_required=True,
        error_code=None,
    )
