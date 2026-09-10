"""Deterministic listing-plan builder for NTA Gumtree automation.

Phase 5 only. Converts a reconciliation decision plus frozen listing inputs into
an inert plan record. No browsing, Gumtree writes, publishing, or LLM calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

EXECUTABLE_RECONCILIATION_ACTIONS = {"CREATE_DRAFT", "UPDATE_DRAFT"}
PLAN_STATUSES = {"READY", "BLOCKED", "NOT_APPLICABLE"}


@dataclass(frozen=True)
class ListingPlan:
    plan_status: str
    action: str
    ad_id: str | None
    shopify_product_id: str | None
    title: str | None
    description: str | None
    price: str | None
    category: str | None
    location: str | None
    image_urls: tuple[str, ...]
    attributes: tuple[tuple[str, str], ...]
    blocking_reasons: tuple[str, ...]
    source_fingerprint: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan_status": self.plan_status,
            "action": self.action,
            "ad_id": self.ad_id,
            "shopify_product_id": self.shopify_product_id,
            "title": self.title,
            "description": self.description,
            "price": self.price,
            "category": self.category,
            "location": self.location,
            "image_urls": list(self.image_urls),
            "attributes": dict(self.attributes),
            "blocking_reasons": list(self.blocking_reasons),
            "source_fingerprint": self.source_fingerprint,
        }


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _valid_price(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    cleaned = text.replace("$", "").replace(",", "").strip()
    try:
        amount = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None
    if amount <= 0:
        return None
    return format(amount.quantize(Decimal("0.01")), "f")


def _normalize_images(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    out: list[str] = []
    for item in value:
        url = _text(item)
        if url and url.startswith(("https://", "http://")) and url not in out:
            out.append(url)
    return tuple(out)


def _normalize_attributes(value: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Mapping):
        return ()
    pairs = []
    for key, raw in value.items():
        k = _text(key)
        v = _text(raw)
        if k and v:
            pairs.append((k, v))
    return tuple(sorted(pairs))


def build_listing_plan(snapshot: Mapping[str, Any], decision: Mapping[str, Any]) -> ListingPlan:
    action = _text(decision.get("action")) or "ERROR"
    product = snapshot.get("product") or {}
    ad = snapshot.get("advertisement") or {}
    listing = snapshot.get("listing_input") or {}

    ad_id = _text(ad.get("ad_id"))
    product_id = _text(product.get("shopify_product_id"))

    if action not in EXECUTABLE_RECONCILIATION_ACTIONS:
        return ListingPlan(
            plan_status="NOT_APPLICABLE",
            action=action,
            ad_id=ad_id,
            shopify_product_id=product_id,
            title=None,
            description=None,
            price=None,
            category=None,
            location=None,
            image_urls=(),
            attributes=(),
            blocking_reasons=("RECONCILIATION_ACTION_NOT_EXECUTABLE",),
            source_fingerprint=_text(listing.get("source_fingerprint")),
        )

    title = _text(listing.get("title"))
    description = _text(listing.get("description"))
    price = _valid_price(listing.get("price"))
    category = _text(listing.get("category"))
    location = _text(listing.get("location"))
    images = _normalize_images(listing.get("image_urls"))
    attributes = _normalize_attributes(listing.get("attributes"))
    fingerprint = _text(listing.get("source_fingerprint"))

    blockers: list[str] = []
    if not ad_id:
        blockers.append("MISSING_AD_ID")
    if not product_id:
        blockers.append("MISSING_PRODUCT_ID")
    if not title:
        blockers.append("MISSING_TITLE")
    elif len(title) > 100:
        blockers.append("TITLE_TOO_LONG")
    if not description:
        blockers.append("MISSING_DESCRIPTION")
    if price is None:
        blockers.append("INVALID_PRICE")
    if not category:
        blockers.append("MISSING_CATEGORY")
    if not location:
        blockers.append("MISSING_LOCATION")
    if not images:
        blockers.append("MISSING_VALID_IMAGE")
    if not fingerprint:
        blockers.append("MISSING_SOURCE_FINGERPRINT")
    if listing.get("identity_uncertain") is True:
        blockers.append("IDENTITY_UNCERTAIN")
    if listing.get("snapshot_stale") is True or listing.get("snapshot_anomalous") is True:
        blockers.append("SOURCE_SNAPSHOT_UNSAFE")
    if listing.get("duplicate_suspected") is True:
        blockers.append("DUPLICATE_SUSPECTED")

    return ListingPlan(
        plan_status="BLOCKED" if blockers else "READY",
        action=action,
        ad_id=ad_id,
        shopify_product_id=product_id,
        title=title,
        description=description,
        price=price,
        category=category,
        location=location,
        image_urls=images,
        attributes=attributes,
        blocking_reasons=tuple(sorted(set(blockers))),
        source_fingerprint=fingerprint,
    )


def browser_execution_allowed(plan: Mapping[str, Any] | ListingPlan) -> bool:
    if isinstance(plan, ListingPlan):
        return plan.plan_status == "READY" and plan.action in EXECUTABLE_RECONCILIATION_ACTIONS
    return (
        plan.get("plan_status") == "READY"
        and plan.get("action") in EXECUTABLE_RECONCILIATION_ACTIONS
    )
