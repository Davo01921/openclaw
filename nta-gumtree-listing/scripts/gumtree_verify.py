"""Read-only post-write verification and health metrics for NTA Gumtree automation.

Phase 7 compares a saved Gumtree draft observation against the frozen Phase 5
listing plan. It performs no writes and grants no browser authority.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

VERIFY_STATUSES = {"VERIFIED", "MISMATCH", "ERROR", "NOT_REQUIRED"}


@dataclass(frozen=True)
class VerificationResult:
    status: str
    ad_id: str | None
    gumtree_listing_id: str | None
    mismatches: tuple[str, ...] = ()
    error_code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "ad_id": self.ad_id,
            "gumtree_listing_id": self.gumtree_listing_id,
            "mismatches": list(self.mismatches),
            "error_code": self.error_code,
        }


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _price(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    try:
        amount = Decimal(text.replace("$", "").replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return format(amount.quantize(Decimal("0.01")), "f")


def _images(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    out: list[str] = []
    for item in value:
        text = _text(item)
        if text and text not in out:
            out.append(text)
    return tuple(out)


def _attributes(value: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Mapping):
        return ()
    return tuple(sorted((str(k).strip(), str(v).strip()) for k, v in value.items() if str(k).strip() and str(v).strip()))


def verify_saved_draft(
    plan: Mapping[str, Any],
    write_result: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> VerificationResult:
    """Compare an independently observed Gumtree draft with the frozen plan."""
    ad_id = _text(plan.get("ad_id"))
    listing_id = _text(observed.get("gumtree_listing_id") or write_result.get("gumtree_listing_id"))

    if write_result.get("verification_required") is not True:
        return VerificationResult("NOT_REQUIRED", ad_id, listing_id)

    if write_result.get("status") != "DRAFT_SAVED":
        return VerificationResult("ERROR", ad_id, listing_id, error_code="WRITE_NOT_SUCCESSFUL")

    if observed.get("snapshot_stale") is True or observed.get("snapshot_anomalous") is True:
        return VerificationResult("ERROR", ad_id, listing_id, error_code="OBSERVED_SNAPSHOT_UNSAFE")

    actual_state = _text(observed.get("actual_state"))
    if actual_state != "DRAFT":
        return VerificationResult("ERROR", ad_id, listing_id, error_code="OBSERVED_STATE_NOT_DRAFT")

    if observed.get("published") is True:
        return VerificationResult("ERROR", ad_id, listing_id, error_code="UNEXPECTED_PUBLISH_STATE")

    mismatches: list[str] = []
    comparisons = (
        ("TITLE_MISMATCH", _text(plan.get("title")), _text(observed.get("title"))),
        ("DESCRIPTION_MISMATCH", _text(plan.get("description")), _text(observed.get("description"))),
        ("PRICE_MISMATCH", _price(plan.get("price")), _price(observed.get("price"))),
        ("CATEGORY_MISMATCH", _text(plan.get("category")), _text(observed.get("category"))),
        ("LOCATION_MISMATCH", _text(plan.get("location")), _text(observed.get("location"))),
    )
    for code, expected, actual in comparisons:
        if expected != actual:
            mismatches.append(code)

    if _images(plan.get("image_urls")) != _images(observed.get("image_urls")):
        mismatches.append("IMAGES_MISMATCH")
    if _attributes(plan.get("attributes")) != _attributes(observed.get("attributes")):
        mismatches.append("ATTRIBUTES_MISMATCH")

    plan_fp = _text(plan.get("source_fingerprint"))
    observed_fp = _text(observed.get("source_fingerprint"))
    if observed_fp is not None and plan_fp != observed_fp:
        mismatches.append("SOURCE_FINGERPRINT_MISMATCH")

    if mismatches:
        return VerificationResult("MISMATCH", ad_id, listing_id, tuple(sorted(set(mismatches))))

    return VerificationResult("VERIFIED", ad_id, listing_id)


def build_health_metrics(results: Iterable[Mapping[str, Any] | VerificationResult]) -> dict[str, Any]:
    """Aggregate deterministic Phase 7 health counters from verification results."""
    counts: Counter[str] = Counter()
    mismatch_counts: Counter[str] = Counter()
    error_counts: Counter[str] = Counter()

    for item in results:
        data = item.as_dict() if isinstance(item, VerificationResult) else dict(item)
        status = _text(data.get("status")) or "ERROR"
        if status not in VERIFY_STATUSES:
            status = "ERROR"
            error_counts["INVALID_VERIFICATION_STATUS"] += 1
        counts[status] += 1
        for mismatch in data.get("mismatches") or []:
            mismatch_counts[str(mismatch)] += 1
        if data.get("error_code"):
            error_counts[str(data["error_code"])] += 1

    total = sum(counts.values())
    verified = counts["VERIFIED"]
    unhealthy = counts["MISMATCH"] + counts["ERROR"]
    return {
        "total": total,
        "verified": verified,
        "mismatch": counts["MISMATCH"],
        "error": counts["ERROR"],
        "not_required": counts["NOT_REQUIRED"],
        "healthy": unhealthy == 0,
        "verification_rate": round(verified / total, 4) if total else 0.0,
        "mismatch_codes": dict(sorted(mismatch_counts.items())),
        "error_codes": dict(sorted(error_counts.items())),
    }
