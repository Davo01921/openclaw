#!/usr/bin/env python3
"""Deterministic validation of NTA handwritten Betta labels."""

import re
from datetime import date, datetime
from decimal import Decimal


def normalize_tank(raw: str) -> str:
    text = re.sub(r"[\s-]+", "", raw.upper().strip())

    if not re.fullmatch(r"\d+BT\d+", text):
        raise ValueError(f"Invalid or incomplete tank ID: {raw!r}")

    return text


def normalize_date(raw: str) -> str:
    """Parse a complete Australian D/M/YYYY date."""
    text = raw.strip()

    if not re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", text):
        raise ValueError(f"Invalid handwritten date: {raw!r}")

    return datetime.strptime(text, "%d/%m/%Y").date().isoformat()


def normalize_price(raw: str) -> Decimal:
    text = raw.strip().replace("$", "")

    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", text):
        raise ValueError(f"Invalid handwritten price: {raw!r}")

    return Decimal(text)


def validate_label(raw_tank, raw_date, raw_price=None):
    result = {
        "raw_tank": raw_tank,
        "raw_date": raw_date,
        "raw_price": raw_price,
        "tank_id": normalize_tank(raw_tank),
        "photo_date": normalize_date(raw_date),
        "status": "FORMAT_VALID",
    }

    if raw_price is not None:
        result["reference_price"] = str(normalize_price(raw_price))

    return result


def resolve_photo_date(
    raw_date: str,
    *,
    year_evidence: str,
    reference_date: str | None = None,
    reference_source: str | None = None,
) -> dict:
    """Resolve handwritten dates using explicit year provenance.

    year_evidence:
      clear     = handwritten year confidently readable
      ambiguous = year cannot be confidently distinguished
      missing   = no year written

    reference_date:
      A trusted capture or intake date in YYYY-MM-DD format.

    Never use filename dates or filesystem modification times
    as authoritative capture evidence.
    """

    if year_evidence not in {"clear", "ambiguous", "missing"}:
        raise ValueError("Invalid year evidence")

    raw = raw_date.strip()

    match = re.fullmatch(
        r"(\d{1,2})/(\d{1,2})(?:/(\d{4}|\?{4}))?",
        raw,
    )

    if not match:
        raise ValueError("Unreadable handwritten date")

    day = int(match.group(1))
    month = int(match.group(2))
    written_year = match.group(3)

    if year_evidence == "clear":
        if not written_year or not written_year.isdigit():
            raise ValueError("Clear year requires four digits")

        year = int(written_year)
        year_source = "physical_card"

    else:
        if not reference_date:
            raise ValueError("Trusted reference date required")

        if reference_source not in {
            "verified_capture",
            "verified_intake",
            "owner_approved",
        }:
            raise ValueError("Untrusted year reference")

        reference = date.fromisoformat(reference_date)

        year = reference.year
        year_source = reference_source

    resolved = date(year, month, day)

    status = "ACCEPTED"

    if year_evidence == "clear" and reference_date:
        reference = date.fromisoformat(reference_date)

        if year != reference.year:
            status = "REVIEW_YEAR_DISCREPANCY"

    return {
        "raw_date": raw,
        "photo_date": resolved.isoformat(),
        "year_evidence": year_evidence,
        "year_source": year_source,
        "reference_date": reference_date,
        "reference_source": reference_source,
        "status": status,
    }
