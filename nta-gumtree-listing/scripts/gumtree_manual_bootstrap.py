"""Manual bootstrap for existing Gumtree listings.

This module records operator-supplied Gumtree listing references into the local
registry. It performs no Gumtree network access, scraping, browser automation,
or identity guessing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from gumtree_census import extract_listing_id
from gumtree_registry import Registry


@dataclass(frozen=True)
class BootstrapResult:
    outcome: str
    ad_id: str
    gumtree_listing_id: str
    gumtree_url: str | None
    instance_id: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def bootstrap_existing_listing(
    registry: Registry,
    *,
    ad_id: str,
    gumtree_listing_id: str | None = None,
    gumtree_url: str | None = None,
    actual_state: str = "ACTIVE",
) -> BootstrapResult:
    """Record a listing reference explicitly supplied by the operator.

    The advertisement must already exist in the registry. A listing ID may be
    supplied directly or parsed offline from the supplied Gumtree URL.
    """
    ad_id = str(ad_id).strip()
    if not ad_id:
        raise ValueError("ad_id is required")

    with registry.connect() as conn:
        ad_exists = conn.execute(
            "SELECT 1 FROM advertisements WHERE ad_id = ?", (ad_id,)
        ).fetchone()
    if not ad_exists:
        raise ValueError("advertisement does not exist in registry")

    listing_id = extract_listing_id(
        {"gumtree_listing_id": gumtree_listing_id, "url": gumtree_url}
    )
    if not listing_id:
        raise ValueError("valid Gumtree listing ID or URL is required")

    instance_id = registry.record_instance(
        {
            "ad_id": ad_id,
            "gumtree_listing_id": listing_id,
            "url": str(gumtree_url).strip() if gumtree_url else None,
            "actual_state": actual_state,
            "is_canonical": True,
        }
    )
    return BootstrapResult(
        outcome="BOOTSTRAPPED",
        ad_id=ad_id,
        gumtree_listing_id=listing_id,
        gumtree_url=str(gumtree_url).strip() if gumtree_url else None,
        instance_id=instance_id,
    )
