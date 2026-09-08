#!/usr/bin/env python3
"""Deterministic NTA inventory-state decision engine.

No Shopify writes, network calls, or model calls.
This module interprets structured physical-stock facts only.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

VALID_JOB_STATES = {"ORDERED", "RECEIVED", "COUNTED", "CORRECTION"}
VALID_BASES = {"PHYSICAL_COUNT", "RECEIVED_INCREMENT", "NONE"}
VALID_SELL_UNIT = {"RESOLVED", "NOT_APPLICABLE"}


def as_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return None
    if isinstance(value, str):
        n = value.strip().lower()
        if n in {"true", "yes", "1"}:
            return True
        if n in {"false", "no", "0"}:
            return False
    return None


def as_nonnegative_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        iv = int(value)
    except (TypeError, ValueError):
        return None
    if str(iv) != str(value).strip() and not isinstance(value, int):
        # Reject decimal-like strings such as 2.5 and other lossy coercions.
        try:
            if float(value) != iv:
                return None
        except (TypeError, ValueError):
            return None
    return iv if iv >= 0 else None


def review(field: str, notes=None, partial=None) -> Dict[str, Any]:
    return {
        "status": "REVIEW_REQUIRED",
        "inventory": partial,
        "missing_or_conflicting_fields": [field],
        "notes": notes or [],
    }


def decide(data: Dict[str, Any]) -> Dict[str, Any]:
    notes = []

    variant_resolved = as_bool(data.get("variant_resolved"))
    if variant_resolved is not True:
        return review("variant_resolved")

    job_state = str(data.get("job_state") or "").strip().upper()
    if job_state not in VALID_JOB_STATES:
        return review("job_state")

    quantity_basis = str(data.get("quantity_basis") or "").strip().upper()
    if quantity_basis not in VALID_BASES:
        return review("quantity_basis")

    sell_unit_status = str(data.get("sell_unit_conversion_status") or "").strip().upper()
    if sell_unit_status not in VALID_SELL_UNIT:
        return review("sell_unit_conversion_status")

    current_available = data.get("current_available")
    if current_available is not None:
        try:
            current_available = int(current_available)
        except (TypeError, ValueError):
            return review("current_available")

    current_on_hand = data.get("current_on_hand")
    if current_on_hand is not None:
        try:
            current_on_hand = int(current_on_hand)
        except (TypeError, ValueError):
            return review("current_on_hand")

    usable_quantity = as_nonnegative_int(data.get("usable_quantity"))
    location = str(data.get("location") or "").strip() or None
    correction_authorised = as_bool(data.get("correction_authorised"))

    # ORDERED stock is not physically received inventory.
    if job_state == "ORDERED":
        return {
            "status": "READY",
            "inventory": {
                "current_available": current_available,
                "current_on_hand": current_on_hand,
                "usable_quantity": None,
                "operation": "NONE",
                "proposed_available": current_available,
                "location": location,
                "notes": ["Purchase order not yet physically received; no inventory mutation proposed."],
            },
            "missing_or_conflicting_fields": [],
            "notes": [],
        }

    if quantity_basis == "NONE":
        return {
            "status": "READY",
            "inventory": {
                "current_available": current_available,
                "current_on_hand": current_on_hand,
                "usable_quantity": None,
                "operation": "NONE",
                "proposed_available": current_available,
                "location": location,
                "notes": ["No physical quantity action requested."],
            },
            "missing_or_conflicting_fields": [],
            "notes": [],
        }

    if usable_quantity is None:
        return review("usable_quantity")

    if not location:
        return review("location")

    if quantity_basis == "PHYSICAL_COUNT":
        if current_available is not None and current_available < 0 and correction_authorised is not True:
            return review(
                "correction_authorised",
                ["Negative/corrupt current stock may only be repaired to a verified physical count when explicitly authorised."],
            )
        operation = "SET"
        proposed_available = usable_quantity
        if current_available is not None and current_available < 0:
            notes.append("Authorised correction of negative/corrupt current stock to verified physical count.")

    elif quantity_basis == "RECEIVED_INCREMENT":
        if job_state != "RECEIVED":
            return review(
                "job_state",
                ["RECEIVED_INCREMENT requires job_state=RECEIVED because ordered quantities are not inventory."],
            )
        if current_available is None:
            return review("current_available")
        if current_available < 0:
            return review(
                "current_available",
                ["Do not ADD received stock onto a negative/corrupt baseline; verify physical count and use an authorised SET correction instead."],
            )
        operation = "ADD"
        proposed_available = current_available + usable_quantity

    else:  # defensive; VALID_BASES already checked
        return review("quantity_basis")

    return {
        "status": "READY",
        "inventory": {
            "current_available": current_available,
            "current_on_hand": current_on_hand,
            "usable_quantity": usable_quantity,
            "operation": operation,
            "proposed_available": proposed_available,
            "location": location,
            "notes": notes,
        },
        "missing_or_conflicting_fields": [],
        "notes": [],
    }


def main() -> None:
    payload = json.load(sys.stdin)
    print(json.dumps(decide(payload), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
