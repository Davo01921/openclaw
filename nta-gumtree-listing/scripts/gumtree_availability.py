"""Deterministic Gumtree availability resolver for Phase 1D.

The resolver converts normalized Shopify product facts plus an already-resolved
Gumtree policy into an availability decision. It performs no Shopify or Gumtree
I/O and never creates listing authority from uncertain inventory data.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping

AVAILABLE = "AVAILABLE"
UNAVAILABLE = "UNAVAILABLE"
UNKNOWN = "UNKNOWN"
NOT_APPLICABLE = "NOT_APPLICABLE"

VALID_OVERRIDES = {AVAILABLE, UNAVAILABLE}
STOCK_DEPENDENT_POLICIES = {"WHEN_IN_STOCK", "UNIQUE"}
BT_CODE_RE = re.compile(r"(?<![A-Z0-9])(\d+BT\d+)(?![A-Z0-9])", re.IGNORECASE)


@dataclass(frozen=True)
class AvailabilityDecision:
    status: str
    authoritative: bool
    source: str
    reason_code: str
    inventory_quantity: int | None = None
    min_stock: int | None = None
    review_required: bool = False
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["errors"] = list(self.errors)
        data["warnings"] = list(self.warnings)
        return data


def _normalized_text(value: Any) -> str:
    return str(value or "").strip()


def _is_betta(product: Mapping[str, Any]) -> bool:
    """Require Shopify product_type to positively classify the product as Betta.

    Title text alone is not authoritative enough to activate the UNIQUE Betta
    exception. This intentionally fails closed when product type is absent or
    generic, even when the title contains the word Betta.
    """
    product_type = _normalized_text(product.get("product_type")).casefold()
    return "betta" in product_type


def _bt_code(product: Mapping[str, Any]) -> str | None:
    for value in (product.get("title"), product.get("handle"), product.get("sku")):
        match = BT_CODE_RE.search(_normalized_text(value))
        if match:
            return match.group(1).upper()
    return None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        if isinstance(value, str) and value.strip():
            return int(value)
    except ValueError:
        pass
    return None


def resolve_availability(
    product: Mapping[str, Any], resolved_policy: Mapping[str, Any]
) -> AvailabilityDecision:
    """Resolve product availability using only deterministic facts.

    Safety invariant: uncertain availability never becomes permission to create a
    Gumtree listing.
    """
    status = _normalized_text(product.get("status")).upper()
    inventory = _integer(product.get("inventory"))
    tracks_inventory = product.get("tracks_inventory") is True
    policy = _normalized_text(resolved_policy.get("gumtree_policy")).upper()
    stockout_policy = _normalized_text(
        resolved_policy.get("gumtree_stockout_policy")
    ).upper()
    min_stock = _integer(resolved_policy.get("gumtree_min_stock"))
    if min_stock is None:
        min_stock = 1

    gumtree = product.get("gumtree") or {}
    override = _normalized_text(gumtree.get("gumtree_availability_override")).upper()

    if status != "ACTIVE":
        return AvailabilityDecision(
            status=UNAVAILABLE,
            authoritative=True,
            source="SHOPIFY_PRODUCT_STATUS",
            reason_code="PRODUCT_INACTIVE",
            inventory_quantity=inventory,
            min_stock=min_stock,
        )

    if policy == "DO_NOT_LIST":
        return AvailabilityDecision(
            status=NOT_APPLICABLE,
            authoritative=True,
            source="GUMTREE_POLICY",
            reason_code="EXCLUDED_POLICY",
            inventory_quantity=inventory,
            min_stock=min_stock,
        )

    if override:
        if override == AVAILABLE:
            return AvailabilityDecision(
                status=AVAILABLE,
                authoritative=True,
                source="SHOPIFY_AVAILABILITY_OVERRIDE",
                reason_code="AVAILABLE_BY_OVERRIDE",
                inventory_quantity=inventory,
                min_stock=min_stock,
            )
        if override == UNAVAILABLE:
            return AvailabilityDecision(
                status=UNAVAILABLE,
                authoritative=True,
                source="SHOPIFY_AVAILABILITY_OVERRIDE",
                reason_code="UNAVAILABLE_BY_OVERRIDE",
                inventory_quantity=inventory,
                min_stock=min_stock,
            )
        return AvailabilityDecision(
            status=UNKNOWN,
            authoritative=False,
            source="SHOPIFY_AVAILABILITY_OVERRIDE",
            reason_code="INVALID_AVAILABILITY_OVERRIDE",
            inventory_quantity=inventory,
            min_stock=min_stock,
            review_required=True,
            errors=("INVALID_AVAILABILITY_OVERRIDE",),
        )

    code = _bt_code(product)
    if policy == "UNIQUE" and _is_betta(product) and code:
        if inventory is None:
            return AvailabilityDecision(
                status=UNKNOWN,
                authoritative=False,
                source="UNIQUE_BETTA_RULE",
                reason_code="UNIQUE_BETTA_QUANTITY_MISSING",
                min_stock=min_stock,
                review_required=True,
                errors=("INVENTORY_DATA_MISSING",),
            )
        if inventory > 0:
            return AvailabilityDecision(
                status=AVAILABLE,
                authoritative=True,
                source="UNIQUE_BETTA_RULE",
                reason_code="AVAILABLE_BY_UNIQUE_BETTA_RULE",
                inventory_quantity=inventory,
                min_stock=min_stock,
            )
        return AvailabilityDecision(
            status=UNAVAILABLE,
            authoritative=True,
            source="UNIQUE_BETTA_RULE",
            reason_code="UNIQUE_BETTA_SOLD_OR_ZERO",
            inventory_quantity=inventory,
            min_stock=min_stock,
        )

    if policy == "ALWAYS_ON" and stockout_policy == "KEEP_ACTIVE":
        return AvailabilityDecision(
            status=NOT_APPLICABLE,
            authoritative=True,
            source="GUMTREE_POLICY",
            reason_code="ALWAYS_ON_KEEP_ACTIVE",
            inventory_quantity=inventory,
            min_stock=min_stock,
        )

    if tracks_inventory:
        if inventory is None:
            return AvailabilityDecision(
                status=UNKNOWN,
                authoritative=False,
                source="SHOPIFY_TRACKED_INVENTORY",
                reason_code="INVENTORY_DATA_MISSING",
                min_stock=min_stock,
                review_required=True,
                errors=("INVENTORY_DATA_MISSING",),
            )
        if inventory >= min_stock:
            return AvailabilityDecision(
                status=AVAILABLE,
                authoritative=True,
                source="SHOPIFY_TRACKED_INVENTORY",
                reason_code="TRACKED_STOCK_AT_OR_ABOVE_MIN",
                inventory_quantity=inventory,
                min_stock=min_stock,
            )
        return AvailabilityDecision(
            status=UNAVAILABLE,
            authoritative=True,
            source="SHOPIFY_TRACKED_INVENTORY",
            reason_code="TRACKED_STOCK_BELOW_MIN",
            inventory_quantity=inventory,
            min_stock=min_stock,
        )

    if policy in STOCK_DEPENDENT_POLICIES:
        return AvailabilityDecision(
            status=UNKNOWN,
            authoritative=False,
            source="SHOPIFY_UNTRACKED_INVENTORY",
            reason_code="UNTRACKED_STOCK_DEPENDENT_POLICY",
            inventory_quantity=inventory,
            min_stock=min_stock,
            review_required=True,
            warnings=("UNTRACKED_INVENTORY_NOT_AUTHORITATIVE",),
        )

    return AvailabilityDecision(
        status=UNKNOWN,
        authoritative=False,
        source="AVAILABILITY_RESOLVER",
        reason_code="AVAILABILITY_RULE_NOT_RESOLVED",
        inventory_quantity=inventory,
        min_stock=min_stock,
        review_required=True,
    )
