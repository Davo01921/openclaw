"""Phase 9 manual operator queue for NTA Gumtree listings.

OpenClaw prepares complete Gumtree posting packages, but does not interact with
Gumtree. Queue generation is allowed only on Thursday, Friday, and Saturday and
returns at most three READY_TO_POST items per day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Mapping

from gumtree_listing_plan import build_listing_plan
from gumtree_reconcile import reconcile

ALLOWED_WEEKDAYS = {3, 4, 5}  # Thursday, Friday, Saturday; Monday == 0
MAX_DAILY_ITEMS = 3
ALLOWED_MANAGEMENT_STATES = {"MAPPED", "MANAGED"}
PRIORITY_RANK = {"CORE_TRAFFIC": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}
QUEUE_STATUSES = {"READY_TO_POST", "POSTED", "VERIFIED"}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _day(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _management_state(snapshot: Mapping[str, Any]) -> str | None:
    advertisement = snapshot.get("advertisement") or {}
    product = snapshot.get("product") or {}
    return _text(advertisement.get("management_state") or product.get("management_state"))


def _priority(snapshot: Mapping[str, Any]) -> str:
    resolved = snapshot.get("resolved_policy") or {}
    product = snapshot.get("product") or {}
    value = _text(resolved.get("priority") or product.get("priority")) or "NORMAL"
    return value if value in PRIORITY_RANK else "NORMAL"


@dataclass(frozen=True)
class OperatorQueueItem:
    status: str
    ad_id: str
    shopify_product_id: str
    reconciliation_action: str
    priority: str
    title: str
    description: str
    price: str
    category: str
    location: str
    image_urls: tuple[str, ...]
    attributes: tuple[tuple[str, str], ...]
    source_fingerprint: str
    gumtree_listing_id: str | None = None
    gumtree_url: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "ad_id": self.ad_id,
            "shopify_product_id": self.shopify_product_id,
            "reconciliation_action": self.reconciliation_action,
            "priority": self.priority,
            "title": self.title,
            "description": self.description,
            "price": self.price,
            "category": self.category,
            "location": self.location,
            "image_urls": list(self.image_urls),
            "attributes": [list(pair) for pair in self.attributes],
            "source_fingerprint": self.source_fingerprint,
            "gumtree_listing_id": self.gumtree_listing_id,
            "gumtree_url": self.gumtree_url,
        }


def _candidate(snapshot: Mapping[str, Any]) -> OperatorQueueItem | None:
    if _management_state(snapshot) not in ALLOWED_MANAGEMENT_STATES:
        return None

    decision = reconcile(snapshot)
    if decision.review_required:
        return None

    plan = build_listing_plan(snapshot, decision.as_dict())
    if plan.plan_status != "READY":
        return None
    if plan.action not in {"CREATE_DRAFT", "UPDATE_DRAFT"}:
        return None

    required = {
        "ad_id": plan.ad_id,
        "shopify_product_id": plan.shopify_product_id,
        "title": plan.title,
        "description": plan.description,
        "price": plan.price,
        "category": plan.category,
        "location": plan.location,
        "source_fingerprint": plan.source_fingerprint,
    }
    if any(value in (None, "") for value in required.values()):
        return None
    if not plan.image_urls:
        return None

    return OperatorQueueItem(
        status="READY_TO_POST",
        ad_id=str(plan.ad_id),
        shopify_product_id=str(plan.shopify_product_id),
        reconciliation_action=str(plan.action),
        priority=_priority(snapshot),
        title=str(plan.title),
        description=str(plan.description),
        price=str(plan.price),
        category=str(plan.category),
        location=str(plan.location),
        image_urls=tuple(plan.image_urls),
        attributes=tuple(plan.attributes),
        source_fingerprint=str(plan.source_fingerprint),
    )


def build_operator_queue(
    snapshots: Iterable[Mapping[str, Any]],
    *,
    run_date: date | datetime | str,
    max_items: int = MAX_DAILY_ITEMS,
) -> dict[str, Any]:
    """Build a deterministic manual-posting queue for one calendar day.

    Sunday-Wednesday return an empty queue. The hard cap is three even if a caller
    passes a larger max_items value. Invalid snapshots fail closed and are counted
    as skipped rather than interrupting the whole queue.
    """
    day = _day(run_date)
    allowed_day = day.weekday() in ALLOWED_WEEKDAYS
    cap = max(0, min(int(max_items), MAX_DAILY_ITEMS))

    if not allowed_day or cap == 0:
        return {
            "run_date": day.isoformat(),
            "allowed_day": allowed_day,
            "max_items": cap,
            "items": [],
            "skipped": 0,
            "publish_authority": False,
            "browser_automation": False,
        }

    candidates: list[OperatorQueueItem] = []
    skipped = 0
    seen_ads: set[str] = set()

    for snapshot in snapshots:
        try:
            item = _candidate(snapshot)
        except Exception:
            item = None
        if item is None:
            skipped += 1
            continue
        if item.ad_id in seen_ads:
            skipped += 1
            continue
        seen_ads.add(item.ad_id)
        candidates.append(item)

    candidates.sort(
        key=lambda item: (
            PRIORITY_RANK[item.priority],
            0 if item.reconciliation_action == "CREATE_DRAFT" else 1,
            item.ad_id,
            item.shopify_product_id,
        )
    )
    selected = candidates[:cap]

    return {
        "run_date": day.isoformat(),
        "allowed_day": True,
        "max_items": cap,
        "items": [item.as_dict() for item in selected],
        "skipped": skipped + max(0, len(candidates) - len(selected)),
        "publish_authority": False,
        "browser_automation": False,
    }


def mark_posted(item: Mapping[str, Any], *, gumtree_listing_id: str | None = None, gumtree_url: str | None = None) -> dict[str, Any]:
    """Record the operator handoff after David manually posts an ad."""
    if item.get("status") != "READY_TO_POST":
        raise ValueError("only READY_TO_POST items can move to POSTED")
    listing_id = _text(gumtree_listing_id)
    url = _text(gumtree_url)
    if not listing_id and not url:
        raise ValueError("gumtree_listing_id or gumtree_url is required")
    result = dict(item)
    result.update({"status": "POSTED", "gumtree_listing_id": listing_id, "gumtree_url": url})
    return result


def mark_verified(item: Mapping[str, Any], *, verified: bool) -> dict[str, Any]:
    """Advance a manually posted item only after independent verification."""
    if item.get("status") != "POSTED":
        raise ValueError("only POSTED items can move to VERIFIED")
    if verified is not True:
        raise ValueError("verification must explicitly succeed")
    result = dict(item)
    result["status"] = "VERIFIED"
    return result
