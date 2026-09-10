"""Deterministic reconciliation engine for NTA Gumtree automation.

Phase 4 only: compares frozen desired/business state with observed Gumtree state
and emits exactly one reconciliation action. No browsing, Shopify writes,
Gumtree writes, or language-model calls occur here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

ACTIONS = {
    "NO_ACTION",
    "CREATE_DRAFT",
    "UPDATE_DRAFT",
    "UPDATE_ACTIVE_REVIEW",
    "RELIST_REVIEW",
    "PAUSE_REVIEW",
    "REMOVE_REVIEW",
    "DUPLICATE_REVIEW",
    "CONFIG_REVIEW",
    "IDENTITY_REVIEW",
    "ERROR",
}

DIRTY_FLAGS = {
    "PRICE_DIRTY",
    "CONTENT_DIRTY",
    "IMAGE_DIRTY",
    "INVENTORY_DIRTY",
    "STATUS_DIRTY",
}

SAFE_CONFIG_STATES = {"CONFIGURED", "EXCLUDED"}
SAFE_MANAGEMENT_STATES = {"MAPPED", "MANAGED"}
ACTUAL_STATES = {
    "UNKNOWN",
    "MISSING",
    "DRAFT",
    "ACTIVE",
    "PAUSED",
    "EXPIRED",
    "SOLD",
    "REMOVED",
    "ERROR",
    "NEEDS_REVIEW",
}


@dataclass(frozen=True)
class ReconciliationDecision:
    action: str
    reason_code: str
    desired_state: str | None
    actual_state: str | None
    dirty_flags: tuple[str, ...] = ()
    review_required: bool = False
    executable: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason_code": self.reason_code,
            "desired_state": self.desired_state,
            "actual_state": self.actual_state,
            "dirty_flags": list(self.dirty_flags),
            "review_required": self.review_required,
            "executable": self.executable,
        }


def _bool(value: Any) -> bool:
    return value is True


def _dirty(advertisement: Mapping[str, Any]) -> tuple[str, ...]:
    raw = advertisement.get("dirty_flags") or []
    flags = []
    for flag in raw:
        flag = str(flag)
        if flag in DIRTY_FLAGS and flag not in flags:
            flags.append(flag)
    return tuple(sorted(flags))


def _decision(
    action: str,
    reason_code: str,
    desired_state: str | None,
    actual_state: str | None,
    *,
    dirty_flags: tuple[str, ...] = (),
) -> ReconciliationDecision:
    if action not in ACTIONS:
        raise ValueError(f"invalid reconciliation action: {action}")
    review_required = action.endswith("_REVIEW") or action in {
        "DUPLICATE_REVIEW",
        "CONFIG_REVIEW",
        "IDENTITY_REVIEW",
    }
    executable = action in {"CREATE_DRAFT", "UPDATE_DRAFT"}
    return ReconciliationDecision(
        action=action,
        reason_code=reason_code,
        desired_state=desired_state,
        actual_state=actual_state,
        dirty_flags=dirty_flags,
        review_required=review_required,
        executable=executable,
    )


def determine_desired_state(
    product: Mapping[str, Any], resolved_policy: Mapping[str, Any]
) -> tuple[str | None, str]:
    """Return (ACTIVE|ABSENT|None, reason_code). None means unsafe/indeterminate."""
    policy = resolved_policy.get("policy") or product.get("policy")
    availability = resolved_policy.get("availability_status") or product.get("availability_status")

    if policy == "DO_NOT_LIST":
        return "ABSENT", "POLICY_DO_NOT_LIST"

    if policy == "ALWAYS_ON":
        return "ACTIVE", "POLICY_ALWAYS_ON"

    if policy in {"WHEN_IN_STOCK", "UNIQUE", "CAMPAIGN"}:
        if policy == "CAMPAIGN" and resolved_policy.get("campaign_active") is False:
            return "ABSENT", "CAMPAIGN_INACTIVE"
        if availability == "AVAILABLE":
            return "ACTIVE", "AVAILABLE_BY_POLICY"
        if availability in {"UNAVAILABLE", "NOT_APPLICABLE"}:
            return "ABSENT", "UNAVAILABLE_BY_POLICY"
        return None, "AVAILABILITY_UNCERTAIN"

    return None, "POLICY_UNKNOWN"


def reconcile(snapshot: Mapping[str, Any]) -> ReconciliationDecision:
    """Reconcile one frozen ad snapshot and emit exactly one deterministic action."""
    product = snapshot.get("product") or {}
    resolved_policy = snapshot.get("resolved_policy") or {}
    advertisement = snapshot.get("advertisement") or {}
    gumtree_state = snapshot.get("gumtree_state") or {}

    config_state = product.get("config_state") or resolved_policy.get("config_state")
    actual_state = gumtree_state.get("actual_state") or "UNKNOWN"
    dirty_flags = _dirty(advertisement)

    # 1) Configuration gate.
    if config_state == "UNCONFIGURED":
        return _decision("CONFIG_REVIEW", "PRODUCT_UNCONFIGURED", None, actual_state)
    if config_state == "CONFIG_ERROR":
        return _decision("CONFIG_REVIEW", "CONFIG_INVALID", None, actual_state)
    if config_state not in SAFE_CONFIG_STATES:
        return _decision("CONFIG_REVIEW", "CONFIG_STATE_UNKNOWN", None, actual_state)

    # 2) Data integrity / identity gates. Preserve existing state when uncertain.
    if _bool(gumtree_state.get("duplicate_suspected")) or int(gumtree_state.get("matching_instance_count", 1) or 0) > 1:
        return _decision("DUPLICATE_REVIEW", "DUPLICATE_SUSPECTED", None, actual_state)

    identity_state = advertisement.get("management_state") or product.get("management_state")
    if identity_state not in SAFE_MANAGEMENT_STATES:
        return _decision("IDENTITY_REVIEW", "IDENTITY_NOT_MAPPED", None, actual_state)
    if _bool(advertisement.get("identity_uncertain")) or _bool(gumtree_state.get("identity_uncertain")):
        return _decision("IDENTITY_REVIEW", "IDENTITY_UNCERTAIN", None, actual_state)

    if actual_state not in ACTUAL_STATES:
        return _decision("ERROR", "ACTUAL_STATE_INVALID", None, str(actual_state))
    if _bool(gumtree_state.get("snapshot_anomalous")) or _bool(gumtree_state.get("snapshot_stale")):
        return _decision("ERROR", "GUMTREE_SNAPSHOT_UNSAFE", None, actual_state)
    if actual_state in {"UNKNOWN", "ERROR", "NEEDS_REVIEW"}:
        return _decision("ERROR", "ACTUAL_STATE_UNCERTAIN", None, actual_state)

    # 3) Desired state.
    desired_state, desired_reason = determine_desired_state(product, resolved_policy)
    if desired_state is None:
        return _decision("ERROR", desired_reason, None, actual_state)

    # 4) Compare desired vs actual, then 5) dirty fields.
    if desired_state == "ACTIVE":
        if actual_state == "MISSING":
            return _decision("CREATE_DRAFT", "ACTIVE_BUT_MISSING", desired_state, actual_state)
        if actual_state == "DRAFT":
            if dirty_flags:
                return _decision(
                    "UPDATE_DRAFT", "DRAFT_DIRTY", desired_state, actual_state, dirty_flags=dirty_flags
                )
            return _decision("NO_ACTION", "DRAFT_CURRENT", desired_state, actual_state)
        if actual_state == "ACTIVE":
            if dirty_flags:
                return _decision(
                    "UPDATE_ACTIVE_REVIEW",
                    "ACTIVE_DIRTY",
                    desired_state,
                    actual_state,
                    dirty_flags=dirty_flags,
                )
            return _decision("NO_ACTION", "ACTIVE_CURRENT", desired_state, actual_state)
        if actual_state == "EXPIRED":
            return _decision("RELIST_REVIEW", "ACTIVE_BUT_EXPIRED", desired_state, actual_state)
        if actual_state in {"PAUSED", "SOLD", "REMOVED"}:
            return _decision("RELIST_REVIEW", f"ACTIVE_BUT_{actual_state}", desired_state, actual_state)

    if desired_state == "ABSENT":
        if actual_state == "ACTIVE":
            return _decision("PAUSE_REVIEW", "ABSENT_BUT_ACTIVE", desired_state, actual_state)
        if actual_state == "DRAFT":
            return _decision("REMOVE_REVIEW", "ABSENT_BUT_DRAFT", desired_state, actual_state)
        if actual_state in {"MISSING", "EXPIRED", "SOLD", "REMOVED", "PAUSED"}:
            return _decision("NO_ACTION", f"ABSENT_AND_{actual_state}", desired_state, actual_state)

    return _decision("ERROR", "STATE_COMBINATION_UNHANDLED", desired_state, actual_state)
