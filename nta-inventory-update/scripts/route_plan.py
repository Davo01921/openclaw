from __future__ import annotations

VALID_JOB_STATES = {"RECEIVED", "RECEIVED_PARTIAL", "COUNTED", "CORRECTION"}
VALID_MODES = {"dry_run", "write"}


def _as_bool(value, field, errors):
    if isinstance(value, bool):
        return value
    errors.append(field)
    return None


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
            "In write mode, DYMO label generation occurs only after verified Shopify state; in dry_run it uses proposed state.",
        ],
    }
