#!/usr/bin/env python3
"""Deterministic validation of NTA handwritten Betta labels."""

import re
from datetime import date
from decimal import Decimal

# Owner-approved tank namespaces: legacy numeric BT tanks and APE tanks.
TANK_PATTERN = r"(?:\d+BT\d+|APE\d+)"


def normalize_tank(raw: str) -> str:
    text = re.sub(r"[\s-]+", "", raw.upper().strip())

    if not re.fullmatch(TANK_PATTERN, text):
        raise ValueError(f"Invalid or incomplete tank ID: {raw!r}")

    return text


def normalize_date(raw: str) -> str:
    """Parse a complete Australian D/M/YYYY date.

    Accepts the handwritten slash form (``14/10/2026``, ``4/10/2026``) and the
    common written form where the year is separated by a space instead of the
    second slash (``14/10 2026``).  Incomplete or two-digit-year dates are
    never guessed here; year provenance is handled by ``resolve_photo_date``.
    """
    text = re.sub(r"\s+", " ", raw.strip())

    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})[/ ](\d{4})", text)

    if not match:
        raise ValueError(f"Invalid handwritten date: {raw!r}")

    day, month, year = (int(group) for group in match.groups())

    try:
        return date(year, month, day).isoformat()
    except ValueError:
        raise ValueError(f"Invalid handwritten date: {raw!r}") from None


def normalize_price(raw: str) -> Decimal:
    text = raw.strip().replace("$", "")

    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", text):
        raise ValueError(f"Invalid handwritten price: {raw!r}")

    return Decimal(text)


def parse_visible_price(raw) -> str | None:
    """Strictly parse a *model-observed* price from the focused label read.

    The label prompt asks for digits only (for example ``35``) or an empty
    string when no price is clearly visible.  This parser never invents a
    value: it returns a canonical digits/decimal string only when the model
    reported a plainly numeric price (an optional leading ``$`` and surrounding
    whitespace are tolerated), and ``None`` for absent or non-numeric text.
    """
    if raw is None:
        return None

    text = str(raw).strip()

    if text.startswith("$"):
        text = text[1:].strip()

    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", text):
        return None

    if "." in text:
        text = text.rstrip("0").rstrip(".")

    return text or None


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


def compare_reads(full: dict, crop: dict) -> dict:
    """Pinned dual-read comparator (incident repair 2026-10-15).

    ``full`` and ``crop`` are already-normalised read dicts:
    ``{"tank_id": str|None, "photo_date": str|None, "confident": bool}`` where
    ``confident`` means the caller's confidence gates passed for that read
    (normalisation of ``full`` is the caller's job; the focused label read
    already normalises its own values).

    Returns ``{"status": "AGREE"|"DISAGREE"|"INCOMPLETE", "tank": str|None,
    "date": str|None, "reasons": [str, ...]}``.

    * AGREE      - both reads are confident and match on tank AND date; the
                   agreed values are returned.
    * INCOMPLETE - either read is not confident.
    * DISAGREE   - both reads are confident and tank or date differ.

    The comparator never guesses and never majority-votes: for anything other
    than AGREE both ``tank`` and ``date`` are ``None``.
    """
    full = full or {}
    crop = crop or {}
    full_tank = full.get("tank_id") or None
    crop_tank = crop.get("tank_id") or None
    full_date = full.get("photo_date") or None
    crop_date = crop.get("photo_date") or None
    full_confident = bool(full.get("confident"))
    crop_confident = bool(crop.get("confident"))

    def show(value):
        return value if value else "unknown"

    reasons: list[str] = []

    if not full_confident:
        reasons.append(
            "full read is not confident "
            f"(tank={show(full_tank)}, date={show(full_date)})")
    if not crop_confident:
        reasons.append(
            "label-crop read is not confident "
            f"(tank={show(crop_tank)}, date={show(crop_date)})")
    if not (full_confident and crop_confident):
        return {"status": "INCOMPLETE", "tank": None, "date": None,
                "reasons": reasons}

    disagreements: list[str] = []

    if full_tank is None or crop_tank is None:
        if full_tank is None and crop_tank is None:
            disagreements.append("tank is missing from both confident reads")
        elif full_tank is None:
            disagreements.append("tank is missing from the full read")
        else:
            disagreements.append("tank is missing from the label-crop read")
    elif full_tank != crop_tank:
        disagreements.append(
            f"tank mismatch: full={full_tank} label-crop={crop_tank}")

    if full_date is None or crop_date is None:
        if full_date is None and crop_date is None:
            disagreements.append("date is missing from both confident reads")
        elif full_date is None:
            disagreements.append("date is missing from the full read")
        else:
            disagreements.append("date is missing from the label-crop read")
    elif full_date != crop_date:
        disagreements.append(
            f"date mismatch: full={full_date} label-crop={crop_date}")

    if disagreements:
        return {"status": "DISAGREE", "tank": None, "date": None,
                "reasons": reasons + disagreements}

    reasons.append(f"confident reads agree: tank={full_tank} date={full_date}")
    return {"status": "AGREE", "tank": full_tank, "date": full_date,
            "reasons": reasons}
