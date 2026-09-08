from __future__ import annotations

VALID_JOB_STATES = {"RECEIVED", "RECEIVED_PARTIAL", "COUNTED", "CORRECTION"}
VALID_MODES = {"dry_run", "write"}
TERMINAL_CHILD_STATUSES = {"REVIEW_REQUIRED", "BLOCK"}


def _as_bool(value, field, errors):
    if isinstance(value, bool):
        return value
    errors.append(field)
    return None


def child_result_gate(child_name: str, child_status: str) -> dict:
    """Return the deterministic fail-fast action for a child result.

    This gate intentionally recognizes only the two terminal statuses shared by
    the inventory-update orchestration contract. A non-terminal result is not
    proof that a child succeeded; the caller must still validate that child's
    documented output contract before continuing.
    """
    if child_status == "BLOCK":
        return {
            "action": "STOP",
            "workflow_status": "BLOCK",
            "stop_after": child_name,
            "reason": "child_block",
        }
    if child_status == "REVIEW_REQUIRED":
        return {
            "action": "STOP",
            "workflow_status": "REVIEW_REQUIRED",
            "stop_after": child_name,
            "reason": "required_child_review",
        }
    return {
        "action": "CONTINUE",
        "workflow_status": None,
        "stop_after": None,
        "reason": None,
    }


def build_route(data: dict) -> dict:
    errors = []
    job_state = data.get("job_state")
    mode = data.get("mode")

    if job_state == "ORDERED":
        return {
            "status": "REVIEW_REQUIRED",
            "route": [],
            "redirect": "nta-supplier-order-processing",
            "missing_or_conflicting_fields": ["job_state"],
            "notes": ["ORDERED stock is not an inventory-update receipt and must not increase physical inventory."],
        }
    if job_state not in VALID_JOB_STATES:
        errors.append("job_state")
    if mode not in VALID_MODES:
        errors.append("mode")

    cost_supplied = _as_bool(data.get("supplier_cost_supplied"), "supplier_cost_supplied", errors)
    price_review = _as_bool(data.get("price_review_required"), "price_review_required", errors)
    label_requested = _as_bool(data.get("label_requested"), "label_requested", errors)

    if errors:
        return {
            "status": "REVIEW_REQUIRED",
            "route": [],
            "redirect": None,
            "missing_or_conflicting_fields": sorted(set(errors)),
            "notes": [],
        }

    route = ["nta-product-resolver", "nta-product-classifier"]
    if cost_supplied:
        route.append("nta-supplier-unit-cost-normalizer")
    if price_review:
        route.append("nta-retail-pricing-standard")

    route.extend([
        "nta-inventory-state",
        "nta-product-availability",
        "nta-product-metafields",
        "nta-product-exception-gate",
    ])

    if mode == "write":
        route.append("nta-shopify-write-verifier")
    if label_requested:
        route.append("nta-dymo-tank-label")

    return {
        "status": "READY",
        "route": route,
        "redirect": None,
        "missing_or_conflicting_fields": [],
        "notes": [
            "Route planning is deterministic; child modules own all product-domain decisions.",
            "Execute sequentially and stop dependent work immediately when a required child returns REVIEW_REQUIRED or BLOCK.",
            "In write mode, DYMO label generation occurs only after verified Shopify state; in dry_run it uses proposed state.",
        ],
    }
