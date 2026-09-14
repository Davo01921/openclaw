"""Deterministic Shopify Gumtree configuration classifier.

Phase 1A is intentionally read-only. It does not call Shopify or Gumtree itself;
it classifies normalized product records supplied by a reader/fixture.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Mapping


GUMTREE_FIELDS = (
    "gumtree_policy",
    "gumtree_priority",
    "gumtree_min_stock",
    "gumtree_stockout_policy",
    "gumtree_stockout_grace_days",
    "gumtree_price_override",
    "gumtree_title_override",
    "gumtree_description_override",
    "gumtree_desired_listing_count",
    "gumtree_campaign_start",
    "gumtree_campaign_end",
    "gumtree_availability_override",
)
# Availability override is deliberately supplemental: by itself it must never
# convert an otherwise unconfigured product into an authorised configuration.
ACTIVATION_FIELDS = GUMTREE_FIELDS[:-1]

POLICIES = {"DO_NOT_LIST", "ALWAYS_ON", "WHEN_IN_STOCK", "UNIQUE", "CAMPAIGN"}
PRIORITIES = {"CORE_TRAFFIC", "HIGH", "NORMAL", "LOW"}
STOCKOUT_POLICIES = {"PAUSE", "KEEP_ACTIVE", "GRACE_PERIOD"}
AVAILABILITY_OVERRIDES = {"AVAILABLE", "UNAVAILABLE"}


def is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def all_gumtree_fields_blank(fields: Mapping[str, Any]) -> bool:
    return all(is_blank(fields.get(name)) for name in GUMTREE_FIELDS)


def _all_activation_fields_blank(fields: Mapping[str, Any]) -> bool:
    return all(is_blank(fields.get(name)) for name in ACTIVATION_FIELDS)


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def validate_populated_fields(fields: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    policy = fields.get("gumtree_policy")
    if not is_blank(policy) and policy not in POLICIES:
        errors.append("INVALID_POLICY")
    priority = fields.get("gumtree_priority")
    if not is_blank(priority) and priority not in PRIORITIES:
        errors.append("INVALID_PRIORITY")
    stockout = fields.get("gumtree_stockout_policy")
    if not is_blank(stockout) and stockout not in STOCKOUT_POLICIES:
        errors.append("INVALID_STOCKOUT_POLICY")
    override = fields.get("gumtree_availability_override")
    if not is_blank(override) and override not in AVAILABILITY_OVERRIDES:
        errors.append("INVALID_AVAILABILITY_OVERRIDE")
    min_stock = fields.get("gumtree_min_stock")
    if not is_blank(min_stock) and not _positive_int(min_stock):
        errors.append("INVALID_MIN_STOCK")
    grace_days = fields.get("gumtree_stockout_grace_days")
    if not is_blank(grace_days) and not _positive_int(grace_days):
        errors.append("INVALID_STOCKOUT_GRACE_DAYS")
    desired_count = fields.get("gumtree_desired_listing_count")
    if not is_blank(desired_count) and (not _positive_int(desired_count) or desired_count < 1):
        errors.append("INVALID_DESIRED_LISTING_COUNT")
    if stockout == "GRACE_PERIOD" and is_blank(grace_days):
        errors.append("GRACE_PERIOD_REQUIRES_DAYS")
    if policy == "CAMPAIGN":
        if is_blank(fields.get("gumtree_campaign_start")):
            errors.append("CAMPAIGN_REQUIRES_START")
        if is_blank(fields.get("gumtree_campaign_end")):
            errors.append("CAMPAIGN_REQUIRES_END")
    return errors


@dataclass(frozen=True)
class ConfigDecision:
    shopify_product_id: str
    title: str
    config_state: str
    report_only: bool
    allowed_to_create: bool
    reason: str
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["errors"] = list(self.errors)
        return data


def classify_product(product: Mapping[str, Any]) -> ConfigDecision:
    product_id = str(product.get("shopify_product_id", ""))
    title = str(product.get("title", ""))
    fields = product.get("gumtree") or {}

    if _all_activation_fields_blank(fields):
        return ConfigDecision(product_id, title, "UNCONFIGURED", True, False, "ALL_GUMTREE_FIELDS_BLANK")

    errors = validate_populated_fields(fields)
    if errors:
        return ConfigDecision(product_id, title, "CONFIG_ERROR", True, False,
                              "INVALID_GUMTREE_CONFIGURATION", tuple(errors))

    if fields.get("gumtree_policy") == "DO_NOT_LIST":
        return ConfigDecision(product_id, title, "EXCLUDED", False, False, "EXPLICIT_DO_NOT_LIST")

    return ConfigDecision(product_id, title, "CONFIGURED", False, True,
                          "GUMTREE_CONFIGURATION_PRESENT")
