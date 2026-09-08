#!/usr/bin/env python3
"""Deterministic NTA DYMO tank-label formatter.

No network calls, Shopify writes, printing, credentials, or model calls.
The caller must provide already-approved intake/Shopify state.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

_ALLOWED_SOURCES = {"shopify_readback", "dry_run_proposed_shopify_state"}


def _decimal(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("not a valid decimal") from exc
    if not amount.is_finite():
        raise ValueError("decimal must be finite")
    return amount


def _money(value: Decimal) -> str:
    if value < 0:
        raise ValueError("price must be non-negative")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def render_label(label: dict[str, Any]) -> dict[str, Any]:
    """Return the SKILL.md READY/REVIEW_REQUIRED contract."""
    invalid: list[str] = []
    warnings: list[str] = []

    name = label.get("product_name")
    if not isinstance(name, str) or not name.strip():
        invalid.append("product_name")
    else:
        name = name.strip()

    try:
        retail = _decimal(label.get("retail_price"))
        if retail < 0:
            raise ValueError
    except ValueError:
        retail = None
        invalid.append("retail_price")

    quantity = label.get("quantity")
    if (
        not isinstance(quantity, int)
        or isinstance(quantity, bool)
        or quantity <= 0
    ):
        invalid.append("quantity")

    raw_date = label.get("shopify_arrival_date")
    try:
        arrival = date.fromisoformat(raw_date) if isinstance(raw_date, str) else None
        if arrival is None:
            raise ValueError
    except ValueError:
        arrival = None
        invalid.append("shopify_arrival_date")

    source = label.get("source")
    if source not in _ALLOWED_SOURCES:
        invalid.append("source")

    bulk_segment = ""
    bulk_price = label.get("bulk_price")
    bulk_minimum = label.get("bulk_min_quantity")

    # If either bulk field is supplied, validate the pair. Bad bulk data does
    # not make the base label unsafe; it is omitted and surfaced as a warning.
    if bulk_price is not None or bulk_minimum is not None:
        try:
            bulk = _decimal(bulk_price) if bulk_price is not None else None
            valid_bulk = bulk is not None and bulk >= 0
        except ValueError:
            bulk = None
            valid_bulk = False

        valid_minimum = (
            isinstance(bulk_minimum, int)
            and not isinstance(bulk_minimum, bool)
            and bulk_minimum >= 2
        )

        if (
            retail is not None
            and valid_bulk
            and valid_minimum
            and bulk < retail
        ):
            bulk_segment = f" | ${_money(bulk)}ea/{bulk_minimum}+"
        else:
            warnings.append(
                "bulk pricing omitted: requires numeric bulk_price, integer "
                "bulk_min_quantity >= 2, and bulk_price < retail_price for "
                "the same Shopify selling unit"
            )

    if invalid:
        return {
            "status": "REVIEW_REQUIRED",
            "text": None,
            "source": source if source in _ALLOWED_SOURCES else None,
            "warnings": warnings,
            "missing_or_invalid_fields": sorted(set(invalid)),
        }

    text = (
        f"{name} | ${_money(retail)}ea{bulk_segment}\n"
        f"{arrival:%d%m%y} | Q{quantity}"
    )
    return {
        "status": "READY",
        "text": text,
        "source": source,
        "warnings": warnings,
    }
