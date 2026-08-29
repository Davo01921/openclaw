"""
Reference routing logic for NTA Betta Processing v2.

This is intentionally provider-agnostic. Wire the adapter functions to the
OpenClaw runtime/plugin/tooling already used on David's installation.
"""

from dataclasses import dataclass
from math import ceil
from typing import Optional

@dataclass
class Thresholds:
    tank_accept: float = 0.90
    tank_retry: float = 0.70
    date_accept: float = 0.90
    date_retry: float = 0.70
    sex_accept: float = 0.85
    sex_retry: float = 0.60
    sol_max_ratio: float = 0.15
    sol_min_cap: int = 2

def sol_batch_cap(batch_size: int, t: Thresholds = Thresholds()) -> int:
    return max(t.sol_min_cap, ceil(batch_size * t.sol_max_ratio))

def route_visual_field(field: str, confidence: float, t: Thresholds = Thresholds()) -> str:
    """Return ACCEPT, CHEAP_RETRY, SOL, or UNCERTAIN."""
    if field == "tank":
        if confidence >= t.tank_accept:
            return "ACCEPT"
        if confidence >= t.tank_retry:
            return "CHEAP_RETRY"
        return "CHEAP_RETRY_THEN_SOL"

    if field == "date":
        if confidence >= t.date_accept:
            return "ACCEPT"
        if confidence >= t.date_retry:
            return "CHEAP_RETRY"
        return "CHEAP_RETRY_THEN_SOL"

    if field == "sex":
        if confidence >= t.sex_accept:
            return "ACCEPT"
        if confidence >= t.sex_retry:
            return "CHEAP_RETRY"
        return "UNCERTAIN"

    raise ValueError(f"Unknown visual field: {field}")

def may_escalate_to_sol(sol_calls: int, batch_size: int, destructive_risk: bool,
                        t: Thresholds = Thresholds()) -> bool:
    # Destructive-risk cases should stop safely; Sol diagnosis is allowed even
    # when the normal cost guard is reached because guessing is prohibited.
    if destructive_risk:
        return True
    return sol_calls < sol_batch_cap(batch_size, t)

def can_archive(item_states: list[str]) -> bool:
    return bool(item_states) and all(s == "PASS" for s in item_states)

def assert_preserved(before: dict, after: dict, approved_changes: set[str]) -> list[str]:
    protected = {"title", "price", "cost", "description", "vendor",
                 "product_type", "handle", "status"}
    errors = []
    for key in protected - approved_changes:
        if before.get(key) != after.get(key):
            errors.append(f"Unexpected change: {key}")
    return errors
