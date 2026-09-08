from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

VALID_TAG_MODES = {"SUBSET", "EXACT"}


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _decimal_string(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return f"{Decimal(value):.2f}"
    except (InvalidOperation, ValueError):
        return None


def _canonical_lines(lines: Any, field: str, errors: list[str]) -> dict[str, int] | None:
    if lines is None:
        return None
    if not isinstance(lines, list):
        errors.append(field)
        return None

    result: dict[str, int] = {}
    for i, line in enumerate(lines):
        prefix = f"{field}[{i}]"
        if not isinstance(line, dict):
            errors.append(prefix)
            continue
        variant_id = line.get("variant_id")
        quantity = line.get("quantity")
        if not _nonempty_string(variant_id):
            errors.append(f"{prefix}.variant_id")
            continue
        if not _positive_int(quantity):
            errors.append(f"{prefix}.quantity")
            continue
        variant_id = variant_id.strip()
        if variant_id in result:
            errors.append(f"{field}.duplicate_variant:{variant_id}")
            continue
        result[variant_id] = quantity
    return result


def _record(verified: list[dict], mismatches: list[dict], field: str, expected: Any, observed: Any) -> None:
    if expected == observed:
        verified.append({"field": field, "expected": expected, "observed": observed})
    else:
        mismatches.append({"field": field, "expected": expected, "observed": observed})


def audit_order(request: dict, fresh_order: dict | None) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    job_id = request.get("job_id")
    order_id = request.get("order_id")
    expected = request.get("expected")
    capability = request.get("read_adapter_capability_verified")

    if not _nonempty_string(job_id):
        errors.append("job_id")
    if not _nonempty_string(order_id):
        errors.append("order_id")
    if not isinstance(expected, dict) or not expected:
        errors.append("expected")
    if not isinstance(capability, bool):
        errors.append("read_adapter_capability_verified")

    if errors:
        return {
            "final_status": "REVIEW_REQUIRED",
            "job_id": job_id,
            "order_id": order_id,
            "expected": [],
            "verified": [],
            "mismatches": [],
            "warnings": sorted(set(errors)),
        }

    if capability is False:
        return {
            "final_status": "REVIEW_REQUIRED",
            "job_id": job_id,
            "order_id": order_id,
            "expected": [],
            "verified": [],
            "mismatches": [],
            "warnings": ["Concrete fresh Shopify order-read adapter capability is not verified."],
        }

    if not isinstance(fresh_order, dict):
        return {
            "final_status": "REVIEW_REQUIRED",
            "job_id": job_id,
            "order_id": order_id,
            "expected": [],
            "verified": [],
            "mismatches": [],
            "warnings": ["Fresh independent order snapshot is required."],
        }

    expected_records: list[dict] = []
    verified: list[dict] = []
    mismatches: list[dict] = []

    observed_order_id = fresh_order.get("order_id")
    expected_records.append({"field": "order_id", "value": order_id.strip()})
    _record(verified, mismatches, "order_id", order_id.strip(), observed_order_id)

    if "customer_id" in expected:
        expected_records.append({"field": "customer_id", "value": expected.get("customer_id")})
        _record(verified, mismatches, "customer_id", expected.get("customer_id"), fresh_order.get("customer_id"))

    if "line_items" in expected:
        line_errors: list[str] = []
        exp_lines = _canonical_lines(expected.get("line_items"), "expected.line_items", line_errors)
        obs_lines = _canonical_lines(fresh_order.get("line_items"), "fresh_order.line_items", line_errors)
        if line_errors:
            return {
                "final_status": "REVIEW_REQUIRED",
                "job_id": job_id,
                "order_id": order_id,
                "expected": expected_records,
                "verified": verified,
                "mismatches": mismatches,
                "warnings": sorted(set(line_errors)),
            }
        expected_records.append({"field": "line_items", "value": exp_lines})
        _record(verified, mismatches, "line_items", exp_lines, obs_lines)

    if "discount_code" in expected:
        expected_records.append({"field": "discount_code", "value": expected.get("discount_code")})
        _record(verified, mismatches, "discount_code", expected.get("discount_code"), fresh_order.get("discount_code"))

    if "total_aud" in expected:
        exp_total = _decimal_string(expected.get("total_aud"))
        obs_total = _decimal_string(fresh_order.get("total_aud"))
        if exp_total is None:
            return {
                "final_status": "REVIEW_REQUIRED",
                "job_id": job_id,
                "order_id": order_id,
                "expected": expected_records,
                "verified": verified,
                "mismatches": mismatches,
                "warnings": ["expected.total_aud"],
            }
        expected_records.append({"field": "total_aud", "value": exp_total})
        _record(verified, mismatches, "total_aud", exp_total, obs_total)

    if "financial_status" in expected:
        expected_records.append({"field": "financial_status", "value": expected.get("financial_status")})
        _record(verified, mismatches, "financial_status", expected.get("financial_status"), fresh_order.get("financial_status"))

    if "zero_balance" in expected:
        zero_balance = expected.get("zero_balance")
        if not isinstance(zero_balance, bool):
            return {
                "final_status": "REVIEW_REQUIRED",
                "job_id": job_id,
                "order_id": order_id,
                "expected": expected_records,
                "verified": verified,
                "mismatches": mismatches,
                "warnings": ["expected.zero_balance"],
            }
        observed_balance = _decimal_string(fresh_order.get("outstanding_aud"))
        observed_zero = observed_balance == "0.00" if observed_balance is not None else None
        expected_records.append({"field": "zero_balance", "value": zero_balance})
        _record(verified, mismatches, "zero_balance", zero_balance, observed_zero)

    if "tags" in expected:
        exp_tags = expected.get("tags")
        obs_tags = fresh_order.get("tags")
        mode = expected.get("tags_mode", "EXACT")
        if mode not in VALID_TAG_MODES or not isinstance(exp_tags, list) or not all(_nonempty_string(x) for x in exp_tags):
            return {
                "final_status": "REVIEW_REQUIRED",
                "job_id": job_id,
                "order_id": order_id,
                "expected": expected_records,
                "verified": verified,
                "mismatches": mismatches,
                "warnings": ["expected.tags/tags_mode"],
            }
        if not isinstance(obs_tags, list) or not all(_nonempty_string(x) for x in obs_tags):
            return {
                "final_status": "REVIEW_REQUIRED",
                "job_id": job_id,
                "order_id": order_id,
                "expected": expected_records,
                "verified": verified,
                "mismatches": mismatches,
                "warnings": ["fresh_order.tags"],
            }
        exp_set = set(exp_tags)
        obs_set = set(obs_tags)
        tag_ok = exp_set.issubset(obs_set) if mode == "SUBSET" else exp_set == obs_set
        expected_records.append({"field": "tags", "value": exp_tags, "mode": mode})
        if tag_ok:
            verified.append({"field": "tags", "expected": exp_tags, "observed": obs_tags, "mode": mode})
        else:
            mismatches.append({"field": "tags", "expected": exp_tags, "observed": obs_tags, "mode": mode})

    if "note" in expected:
        expected_records.append({"field": "note", "value": expected.get("note")})
        _record(verified, mismatches, "note", expected.get("note"), fresh_order.get("note"))

    final_status = "FAIL" if mismatches else ("PASS_WITH_WARNING" if warnings else "PASS")
    return {
        "final_status": final_status,
        "job_id": job_id,
        "order_id": order_id,
        "expected": expected_records,
        "verified": verified,
        "mismatches": mismatches,
        "warnings": warnings,
    }
