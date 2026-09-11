"""Phase 8 orchestration and dashboard summary for NTA Gumtree automation.

This module composes the deterministic Phase 4-7 components into one scheduler-safe
run. It does not add browser capabilities. Automated execution remains limited to
SAVE DRAFT operations and, as an extra final safety gate, only MANAGED ads may
reach the Phase 6 writer.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Protocol

from gumtree_draft_writer import execute_draft_plan
from gumtree_listing_plan import build_listing_plan, browser_execution_allowed
from gumtree_reconcile import reconcile
from gumtree_verify import VerificationResult, build_health_metrics, verify_saved_draft


class BrowserFactory(Protocol):
    def __call__(self, snapshot: Mapping[str, Any], plan: Mapping[str, Any]) -> Any: ...


class DraftObserver(Protocol):
    def __call__(
        self,
        snapshot: Mapping[str, Any],
        plan: Mapping[str, Any],
        write_result: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class CycleItemResult:
    ad_id: str | None
    shopify_product_id: str | None
    reconciliation_action: str
    reconciliation_reason: str
    plan_status: str
    execution_status: str
    verification_status: str
    review_required: bool
    error_code: str | None = None
    verification: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ad_id": self.ad_id,
            "shopify_product_id": self.shopify_product_id,
            "reconciliation_action": self.reconciliation_action,
            "reconciliation_reason": self.reconciliation_reason,
            "plan_status": self.plan_status,
            "execution_status": self.execution_status,
            "verification_status": self.verification_status,
            "review_required": self.review_required,
            "error_code": self.error_code,
            "verification": dict(self.verification) if self.verification else None,
        }


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _management_state(snapshot: Mapping[str, Any]) -> str | None:
    ad = snapshot.get("advertisement") or {}
    product = snapshot.get("product") or {}
    return _text(ad.get("management_state") or product.get("management_state"))


def run_cycle(
    snapshots: Iterable[Mapping[str, Any]],
    *,
    execute_drafts: bool = False,
    browser_factory: BrowserFactory | None = None,
    observe_draft: DraftObserver | None = None,
) -> dict[str, Any]:
    """Run one deterministic Gumtree reconciliation cycle.

    Safe modes:
    - execute_drafts=False: reconcile and plan only; no browser calls.
    - execute_drafts=True: only READY CREATE_DRAFT/UPDATE_DRAFT plans for MANAGED ads
      may reach the Phase 6 writer. A successful save is independently verified
      when an observer is supplied.

    No publish, promotion, pause, remove, relist, or active-listing changes exist
    in this orchestration contract.
    """
    results: list[CycleItemResult] = []
    verifications: list[VerificationResult | Mapping[str, Any]] = []

    for snapshot in snapshots:
        try:
            decision = reconcile(snapshot)
            decision_dict = decision.as_dict()
            plan = build_listing_plan(snapshot, decision_dict)
            plan_dict = plan.as_dict()
        except Exception:
            results.append(
                CycleItemResult(
                    ad_id=_text((snapshot.get("advertisement") or {}).get("ad_id")),
                    shopify_product_id=_text((snapshot.get("product") or {}).get("shopify_product_id")),
                    reconciliation_action="ERROR",
                    reconciliation_reason="ORCHESTRATION_INPUT_ERROR",
                    plan_status="BLOCKED",
                    execution_status="ERROR",
                    verification_status="NOT_REQUIRED",
                    review_required=True,
                    error_code="ORCHESTRATION_INPUT_ERROR",
                )
            )
            continue

        ad_id = _text(plan_dict.get("ad_id"))
        product_id = _text(plan_dict.get("shopify_product_id"))
        base = {
            "ad_id": ad_id,
            "shopify_product_id": product_id,
            "reconciliation_action": decision.action,
            "reconciliation_reason": decision.reason_code,
            "plan_status": plan.plan_status,
        }

        if not execute_drafts:
            results.append(
                CycleItemResult(
                    **base,
                    execution_status="NOT_EXECUTED",
                    verification_status="NOT_REQUIRED",
                    review_required=decision.review_required,
                )
            )
            continue

        if not browser_execution_allowed(plan_dict):
            results.append(
                CycleItemResult(
                    **base,
                    execution_status="NOT_EXECUTABLE",
                    verification_status="NOT_REQUIRED",
                    review_required=decision.review_required,
                )
            )
            continue

        # Final v1 authority gate: MAPPED is enough for reconciliation, but only
        # MANAGED is allowed to auto-change Gumtree through a browser.
        if _management_state(snapshot) != "MANAGED":
            results.append(
                CycleItemResult(
                    **base,
                    execution_status="BLOCKED",
                    verification_status="NOT_REQUIRED",
                    review_required=True,
                    error_code="MANAGEMENT_STATE_NOT_MANAGED",
                )
            )
            continue

        if browser_factory is None:
            results.append(
                CycleItemResult(
                    **base,
                    execution_status="BLOCKED",
                    verification_status="NOT_REQUIRED",
                    review_required=True,
                    error_code="BROWSER_FACTORY_UNAVAILABLE",
                )
            )
            continue

        try:
            browser = browser_factory(snapshot, plan_dict)
            write = execute_draft_plan(plan_dict, browser)
            write_dict = write.as_dict()
        except Exception:
            results.append(
                CycleItemResult(
                    **base,
                    execution_status="ERROR",
                    verification_status="NOT_REQUIRED",
                    review_required=True,
                    error_code="ORCHESTRATION_DRAFT_EXECUTION_FAILED",
                )
            )
            continue

        if write.status != "DRAFT_SAVED":
            results.append(
                CycleItemResult(
                    **base,
                    execution_status=write.status,
                    verification_status="ERROR" if write.verification_required else "NOT_REQUIRED",
                    review_required=True,
                    error_code=write.error_code,
                )
            )
            continue

        if observe_draft is None:
            verification = VerificationResult(
                status="ERROR",
                ad_id=ad_id,
                gumtree_listing_id=write.gumtree_listing_id,
                error_code="VERIFICATION_OBSERVER_UNAVAILABLE",
            )
        else:
            try:
                observed = observe_draft(snapshot, plan_dict, write_dict)
                verification = verify_saved_draft(plan_dict, write_dict, observed)
            except Exception:
                verification = VerificationResult(
                    status="ERROR",
                    ad_id=ad_id,
                    gumtree_listing_id=write.gumtree_listing_id,
                    error_code="VERIFICATION_OBSERVER_FAILED",
                )

        verifications.append(verification)
        verification_dict = verification.as_dict()
        results.append(
            CycleItemResult(
                **base,
                execution_status="DRAFT_SAVED",
                verification_status=verification.status,
                review_required=verification.status != "VERIFIED",
                error_code=verification.error_code,
                verification=verification_dict,
            )
        )

    item_dicts = [result.as_dict() for result in results]
    return {
        "items": item_dicts,
        "dashboard": build_dashboard_snapshot(item_dicts, verifications),
    }


def build_dashboard_snapshot(
    items: Iterable[Mapping[str, Any]],
    verifications: Iterable[Mapping[str, Any] | VerificationResult] = (),
) -> dict[str, Any]:
    """Build a deterministic, presentation-neutral operational dashboard payload."""
    item_list = [dict(item) for item in items]
    actions = Counter(_text(item.get("reconciliation_action")) or "ERROR" for item in item_list)
    executions = Counter(_text(item.get("execution_status")) or "ERROR" for item in item_list)
    reviews = sum(1 for item in item_list if item.get("review_required") is True)
    errors = Counter(
        str(item["error_code"])
        for item in item_list
        if item.get("error_code")
    )
    health = build_health_metrics(verifications)

    blocked = executions["BLOCKED"] + executions["ERROR"]
    healthy = blocked == 0 and reviews == 0 and health["healthy"]

    return {
        "total_items": len(item_list),
        "healthy": healthy,
        "review_required": reviews,
        "actions": dict(sorted(actions.items())),
        "execution": dict(sorted(executions.items())),
        "errors": dict(sorted(errors.items())),
        "verification": health,
        "publish_authority": False,
        "paid_promotion_authority": False,
        "automatic_active_listing_changes": False,
    }
