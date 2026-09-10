"""Read-only Gumtree census normalization and registry import.

This module does not browse Gumtree and does not mutate Gumtree. It consumes
listing observations captured elsewhere, normalizes them deterministically,
and imports only listings whose NTA advertisement identity is already known.
Unmatched or ambiguous observations are returned for review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any, Iterable, Mapping

from gumtree_registry import ACTUAL_STATES, Registry

_LISTING_ID_RE = re.compile(r"(?:/|listingId=)(\d{5,})(?:\D|$)")

_STATE_ALIASES = {
    "LIVE": "ACTIVE",
    "ACTIVE": "ACTIVE",
    "DRAFT": "DRAFT",
    "PAUSED": "PAUSED",
    "EXPIRED": "EXPIRED",
    "SOLD": "SOLD",
    "REMOVED": "REMOVED",
    "DELETED": "REMOVED",
}


@dataclass(frozen=True)
class CensusObservation:
    gumtree_listing_id: str
    url: str | None
    actual_state: str
    title: str | None
    price: str | None
    captured_at: str | None
    source_index: int


@dataclass(frozen=True)
class CensusResult:
    listing_id: str | None
    outcome: str
    reason: str
    ad_id: str | None = None
    instance_id: int | None = None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def extract_listing_id(raw: Mapping[str, Any]) -> str | None:
    explicit = _text(raw.get("gumtree_listing_id") or raw.get("listing_id") or raw.get("id"))
    if explicit:
        return explicit
    url = _text(raw.get("url"))
    if not url:
        return None
    match = _LISTING_ID_RE.search(url)
    return match.group(1) if match else None


def normalize_state(value: Any) -> str:
    text = (_text(value) or "UNKNOWN").upper().replace(" ", "_")
    state = _STATE_ALIASES.get(text, text)
    return state if state in ACTUAL_STATES else "UNKNOWN"


def normalize_observation(raw: Mapping[str, Any], *, source_index: int = 0) -> CensusObservation:
    listing_id = extract_listing_id(raw)
    if not listing_id:
        raise ValueError("missing Gumtree listing identity")
    return CensusObservation(
        gumtree_listing_id=listing_id,
        url=_text(raw.get("url")),
        actual_state=normalize_state(raw.get("actual_state") or raw.get("state") or raw.get("status")),
        title=_text(raw.get("title")),
        price=_text(raw.get("price")),
        captured_at=_text(raw.get("captured_at") or raw.get("last_seen_at")),
        source_index=int(source_index),
    )


def census_records(records: Iterable[Mapping[str, Any]]) -> tuple[list[CensusObservation], list[CensusResult]]:
    """Normalize raw observations and detect duplicate/invalid listing identities."""
    observations: list[CensusObservation] = []
    results: list[CensusResult] = []
    seen: set[str] = set()

    for index, raw in enumerate(records):
        try:
            observation = normalize_observation(raw, source_index=index)
        except (ValueError, TypeError) as exc:
            results.append(CensusResult(None, "ERROR", str(exc)))
            continue

        if observation.gumtree_listing_id in seen:
            results.append(
                CensusResult(
                    observation.gumtree_listing_id,
                    "DUPLICATE_REVIEW",
                    "duplicate listing identity in census input",
                )
            )
            continue

        seen.add(observation.gumtree_listing_id)
        observations.append(observation)

    return observations, results


def import_census(
    registry: Registry,
    records: Iterable[Mapping[str, Any]],
    *,
    listing_to_ad: Mapping[str, str],
) -> list[CensusResult]:
    """Import a read-only census into the registry using explicit identity mappings.

    `listing_to_ad` must be supplied by a trusted deterministic mapping/review step.
    The census importer never guesses product/ad identity from title text.
    """
    observations, results = census_records(records)

    for observation in observations:
        listing_id = observation.gumtree_listing_id
        ad_id = _text(listing_to_ad.get(listing_id))
        if not ad_id:
            results.append(
                CensusResult(
                    listing_id,
                    "IDENTITY_REVIEW",
                    "no trusted advertisement mapping",
                )
            )
            continue

        with registry.connect() as conn:
            ad_exists = conn.execute(
                "SELECT 1 FROM advertisements WHERE ad_id = ?",
                (ad_id,),
            ).fetchone()
        if not ad_exists:
            results.append(
                CensusResult(
                    listing_id,
                    "IDENTITY_REVIEW",
                    "mapped advertisement does not exist in registry",
                    ad_id=ad_id,
                )
            )
            continue

        instance_id = registry.record_instance(
            {
                "ad_id": ad_id,
                "gumtree_listing_id": listing_id,
                "url": observation.url,
                "actual_state": observation.actual_state,
                "title": observation.title,
                "price": observation.price,
                "last_seen_at": observation.captured_at,
                "first_seen_at": observation.captured_at,
                "is_canonical": False,
            }
        )
        results.append(
            CensusResult(
                listing_id,
                "IMPORTED",
                "trusted advertisement mapping",
                ad_id=ad_id,
                instance_id=instance_id,
            )
        )

    return results


def result_dicts(results: Iterable[CensusResult]) -> list[dict[str, Any]]:
    return [asdict(result) for result in results]
