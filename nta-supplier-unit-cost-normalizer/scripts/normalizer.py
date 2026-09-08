from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List

GST_RATE = Decimal("1.10")
MONEY_QUANT = Decimal("0.0001")
VALID_GST_BASIS = {"INC_GST", "EX_GST"}


def _decimal(value: Any, field: str, errors: List[str]) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        errors.append(field)
        return None
    if not number.is_finite() or number < 0:
        errors.append(field)
        return None
    return number


def _positive_int(value: Any, field: str, errors: List[str]) -> int | None:
    if isinstance(value, bool):
        errors.append(field)
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        errors.append(field)
        return None
    if str(value).strip() not in {str(number), f"{number}.0"} and not isinstance(value, int):
        errors.append(field)
        return None
    if number <= 0:
        errors.append(field)
        return None
    return number


def _nonnegative_int(value: Any, field: str, errors: List[str]) -> int | None:
    if isinstance(value, bool):
        errors.append(field)
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        errors.append(field)
        return None
    if str(value).strip() not in {str(number), f"{number}.0"} and not isinstance(value, int):
        errors.append(field)
        return None
    if number < 0:
        errors.append(field)
        return None
    return number


def _money(value: Decimal) -> str:
    rounded = value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    text = format(rounded, "f").rstrip("0").rstrip(".")
    return text or "0"


def normalize_cost(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize already-resolved supplier purchasing data into Shopify selling-unit cost.

    This function is intentionally deterministic. It performs no model, network,
    Shopify, pricing, inventory, or vendor-resolution work.
    """

    errors: List[str] = []
    notes: List[str] = []

    supplier_cost = _decimal(data.get("supplier_cost"), "supplier_cost", errors)
    attributable_line_cost_ex_gst = _decimal(
        data.get("attributable_line_cost_ex_gst", 0),
        "attributable_line_cost_ex_gst",
        errors,
    )
    supplier_order_qty = _positive_int(data.get("supplier_order_qty"), "supplier_order_qty", errors)
    supplier_pack_size = _positive_int(data.get("supplier_pack_size"), "supplier_pack_size", errors)
    shopify_sell_unit = _positive_int(data.get("shopify_sell_unit"), "shopify_sell_unit", errors)
    bonus_base_units = _nonnegative_int(data.get("bonus_base_units", 0), "bonus_base_units", errors)

    gst_basis = data.get("gst_basis")
    if gst_basis not in VALID_GST_BASIS:
        errors.append("gst_basis")

    if errors:
        return {
            "status": "REVIEW_REQUIRED",
            "cost": None,
            "missing_or_invalid_fields": sorted(set(errors)),
            "notes": notes,
        }

    assert supplier_cost is not None
    assert attributable_line_cost_ex_gst is not None
    assert supplier_order_qty is not None
    assert supplier_pack_size is not None
    assert shopify_sell_unit is not None
    assert bonus_base_units is not None

    paid_base_units = supplier_order_qty * supplier_pack_size
    ordered_base_units = paid_base_units + bonus_base_units

    if ordered_base_units % shopify_sell_unit != 0:
        return {
            "status": "REVIEW_REQUIRED",
            "cost": None,
            "missing_or_invalid_fields": ["shopify_sell_unit"],
            "notes": [
                "ordered_base_units is not exactly divisible by shopify_sell_unit; resolve the selling-unit mapping upstream"
            ],
        }

    shopify_retail_units_produced = ordered_base_units // shopify_sell_unit
    if shopify_retail_units_produced <= 0:
        return {
            "status": "REVIEW_REQUIRED",
            "cost": None,
            "missing_or_invalid_fields": ["shopify_sell_unit"],
            "notes": ["no Shopify retail units are produced by the supplied unit mapping"],
        }

    if gst_basis == "INC_GST":
        supplier_line_cost_ex_gst = supplier_cost / GST_RATE
    else:
        supplier_line_cost_ex_gst = supplier_cost

    unit_purchase_cost_ex_gst = supplier_line_cost_ex_gst / Decimal(shopify_retail_units_produced)
    attributable_unit_cost_ex_gst = attributable_line_cost_ex_gst / Decimal(shopify_retail_units_produced)
    landed_cost_ex_gst = unit_purchase_cost_ex_gst + attributable_unit_cost_ex_gst

    if bonus_base_units:
        notes.append(
            f"purchase cost allocated across {ordered_base_units} physical base units including {bonus_base_units} bonus/free units"
        )

    return {
        "status": "READY",
        "cost": {
            "supplier_cost": _money(supplier_cost),
            "gst_basis": gst_basis,
            "supplier_order_qty": supplier_order_qty,
            "supplier_pack_size": supplier_pack_size,
            "shopify_sell_unit": shopify_sell_unit,
            "bonus_base_units": bonus_base_units,
            "ordered_base_units": ordered_base_units,
            "shopify_retail_units_produced": shopify_retail_units_produced,
            "supplier_line_cost_ex_gst": _money(supplier_line_cost_ex_gst),
            "unit_purchase_cost_ex_gst": _money(unit_purchase_cost_ex_gst),
            "attributable_unit_cost_ex_gst": _money(attributable_unit_cost_ex_gst),
            "landed_cost_ex_gst": _money(landed_cost_ex_gst),
        },
        "missing_or_invalid_fields": [],
        "notes": notes,
    }
