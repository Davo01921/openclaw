#!/usr/bin/env python3
"""Deterministic NTA product availability decision engine.

This module is side-effect free: no Shopify writes, network calls, or model calls.
It decides customer orderability state from structured authoritative inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


VALID_SOURCE_STATES = {
    "NORMAL",
    "ORDERABLE_TIMING_UNCERTAIN",
    "CANNOT_SOURCE",
    "UNKNOWN",
}
VALID_OVERRIDES = {None, "automatic", "eta_tbc", "disabled"}
VALID_POLICIES = {None, "CONTINUE", "DENY"}


def bool_or_none(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "yes", "1"}:
            return True
        if v in {"false", "no", "0"}:
            return False
        if v in {"unknown", "", "null", "none"}:
            return None
    return None


def int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        iv = int(value)
    except (TypeError, ValueError):
        return None
    return iv


@dataclass
class AvailabilityResult:
    status: str
    availability: Dict[str, Any]
    missing_or_conflicting_fields: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def decide_availability(data: Dict[str, Any]) -> AvailabilityResult:
    missing: List[str] = []
    notes: List[str] = []

    variant_resolved = bool_or_none(data.get("variant_resolved"))
    replenishable = bool_or_none(data.get("replenishable"))
    individually_identified = bool_or_none(data.get("individually_identified"))
    discontinued = bool_or_none(data.get("discontinued"))
    clearance_only = bool_or_none(data.get("clearance_only"))
    internal_use = bool_or_none(data.get("internal_use"))
    nta_wants_further_orders = bool_or_none(data.get("nta_wants_further_orders"))
    available_qty = int_or_none(data.get("available_qty"))

    source_state = data.get("supplier_source_state")
    if isinstance(source_state, str):
        source_state = source_state.strip().upper()
    if source_state is None:
        source_state = "UNKNOWN"
    if source_state not in VALID_SOURCE_STATES:
        missing.append("supplier_source_state")

    eta = data.get("authoritative_eta")
    if isinstance(eta, str):
        eta = eta.strip() or None

    explicit_override = data.get("explicit_status_override")
    if isinstance(explicit_override, str):
        explicit_override = explicit_override.strip().lower() or None
    if explicit_override not in VALID_OVERRIDES:
        missing.append("explicit_status_override")

    if variant_resolved is not True:
        missing.append("variant_resolved")

    if available_qty is None:
        missing.append("available_qty")
    elif available_qty < 0:
        missing.append("available_qty")
        notes.append("Negative physical inventory is not a valid availability input; repair inventory state upstream first.")

    blockers = any(x is True for x in [individually_identified, discontinued, clearance_only, internal_use])
    if nta_wants_further_orders is False:
        blockers = True

    # Explicit disabled is authoritative for customer orderability.
    if explicit_override == "disabled":
        return AvailabilityResult(
            status="READY" if not missing else "REVIEW_REQUIRED",
            availability={
                "preorder_eligible": False,
                "inventory_policy": "DENY",
                "status_override": "disabled",
                "customer_state": "IN_STOCK" if (available_qty or 0) > 0 else "UNAVAILABLE",
                "eta": eta,
                "notes": notes + ["Explicit operator override disabled future ordering."],
            },
            missing_or_conflicting_fields=sorted(set(missing)),
        )

    if missing:
        return AvailabilityResult(
            status="REVIEW_REQUIRED",
            availability={
                "preorder_eligible": None,
                "inventory_policy": None,
                "status_override": None,
                "customer_state": None,
                "eta": eta,
                "notes": notes,
            },
            missing_or_conflicting_fields=sorted(set(missing)),
        )

    assert available_qty is not None

    # Physical stock can be sold even when future replenishment is blocked.
    if available_qty > 0:
        if blockers or replenishable is False or source_state == "CANNOT_SOURCE":
            return AvailabilityResult(
                status="READY",
                availability={
                    "preorder_eligible": False,
                    "inventory_policy": "DENY",
                    "status_override": "automatic" if explicit_override is None else explicit_override,
                    "customer_state": "IN_STOCK",
                    "eta": eta,
                    "notes": notes + ["Sell remaining physical stock only; do not oversell beyond available quantity."],
                },
                missing_or_conflicting_fields=[],
            )

        if replenishable is True:
            return AvailabilityResult(
                status="READY",
                availability={
                    "preorder_eligible": True,
                    "inventory_policy": "CONTINUE",
                    "status_override": "automatic" if explicit_override is None else explicit_override,
                    "customer_state": "IN_STOCK",
                    "eta": eta,
                    "notes": notes,
                },
                missing_or_conflicting_fields=[],
            )

        # With stock in hand, customer can buy now, but oversell policy is unsafe if replenishment is unknown.
        return AvailabilityResult(
            status="READY",
            availability={
                "preorder_eligible": False,
                "inventory_policy": "DENY",
                "status_override": "automatic",
                "customer_state": "IN_STOCK",
                "eta": eta,
                "notes": notes + ["Replenishability unknown; current stock may be sold but overselling is disabled."],
            },
            missing_or_conflicting_fields=[],
        )

    # available_qty == 0 from here.
    if blockers or replenishable is False or source_state == "CANNOT_SOURCE":
        return AvailabilityResult(
            status="READY",
            availability={
                "preorder_eligible": False,
                "inventory_policy": "DENY",
                "status_override": "disabled",
                "customer_state": "UNAVAILABLE",
                "eta": eta,
                "notes": notes,
            },
            missing_or_conflicting_fields=[],
        )

    if replenishable is None:
        return AvailabilityResult(
            status="REVIEW_REQUIRED",
            availability={
                "preorder_eligible": None,
                "inventory_policy": None,
                "status_override": None,
                "customer_state": None,
                "eta": eta,
                "notes": notes + ["Zero stock does not establish preorder eligibility when replenishment is unknown."],
            },
            missing_or_conflicting_fields=["replenishable"],
        )

    if source_state == "UNKNOWN":
        return AvailabilityResult(
            status="REVIEW_REQUIRED",
            availability={
                "preorder_eligible": None,
                "inventory_policy": None,
                "status_override": None,
                "customer_state": None,
                "eta": eta,
                "notes": notes + ["Supplier source state must be resolved before enabling zero-stock ordering."],
            },
            missing_or_conflicting_fields=["supplier_source_state"],
        )

    if source_state == "ORDERABLE_TIMING_UNCERTAIN":
        return AvailabilityResult(
            status="READY",
            availability={
                "preorder_eligible": True,
                "inventory_policy": "CONTINUE",
                "status_override": "eta_tbc",
                "customer_state": "AVAILABLE_TO_ORDER_ETA_TBC",
                "eta": eta,
                "notes": notes,
            },
            missing_or_conflicting_fields=[],
        )

    # replenishable True + NORMAL source + zero stock
    return AvailabilityResult(
        status="READY",
        availability={
            "preorder_eligible": True,
            "inventory_policy": "CONTINUE",
            "status_override": "automatic",
            "customer_state": "PREORDER",
            "eta": eta,
            "notes": notes,
        },
        missing_or_conflicting_fields=[],
    )


if __name__ == "__main__":
    import json
    import sys

    payload = json.load(sys.stdin)
    print(json.dumps(decide_availability(payload).to_dict(), indent=2))
