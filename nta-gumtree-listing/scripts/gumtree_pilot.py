"""Controlled live-pilot guard for NTA Gumtree automation.

This is a rollout safety wrapper around Phase 8. It adds no business authority
and no Gumtree capabilities. Pilot execution is dry-run by default, limited to
an explicit product allowlist, capped to a tiny batch, and requires every
selected advertisement to already be MANAGED before draft execution can occur.

Publishing, paid promotion, active-listing edits, pause/remove/relist and any
automatic promotion of MAPPED -> MANAGED remain outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from gumtree_orchestrator import run_cycle

MAX_PILOT_ITEMS = 3


@dataclass(frozen=True)
class PilotConfig:
    allowlisted_product_ids: tuple[str, ...]
    execution_enabled: bool = False
    max_items: int = MAX_PILOT_ITEMS


class PilotSafetyError(ValueError):
    """Raised when the live-pilot contract is not safe to execute."""


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _product_id(snapshot: Mapping[str, Any]) -> str | None:
    return _text((snapshot.get("product") or {}).get("shopify_product_id"))


def _management_state(snapshot: Mapping[str, Any]) -> str | None:
    ad = snapshot.get("advertisement") or {}
    product = snapshot.get("product") or {}
    return _text(ad.get("management_state") or product.get("management_state"))


def _validate_config(config: PilotConfig) -> tuple[str, ...]:
    if not isinstance(config.max_items, int) or not (1 <= config.max_items <= MAX_PILOT_ITEMS):
        raise PilotSafetyError("PILOT_BATCH_CAP_INVALID")

    ids = tuple(_text(x) for x in config.allowlisted_product_ids)
    if not ids or any(x is None for x in ids):
        raise PilotSafetyError("PILOT_ALLOWLIST_EMPTY_OR_INVALID")

    clean = tuple(x for x in ids if x is not None)
    if len(clean) != len(set(clean)):
        raise PilotSafetyError("PILOT_ALLOWLIST_DUPLICATE")
    if len(clean) > config.max_items:
        raise PilotSafetyError("PILOT_ALLOWLIST_EXCEEDS_CAP")
    return clean


def run_pilot(
    snapshots: Iterable[Mapping[str, Any]],
    *,
    config: PilotConfig,
    browser_factory: Any = None,
    observe_draft: Any = None,
) -> dict[str, Any]:
    """Run a tiny, explicitly allowlisted Phase 8 pilot.

    Dry-run is the default. Draft execution requires:
    - execution_enabled=True explicitly;
    - every allowlisted product present exactly once;
    - every selected ad already MANAGED;
    - browser and independent observer adapters supplied.

    The wrapper never changes management state itself.
    """
    allowlist = _validate_config(config)
    allowset = set(allowlist)

    by_product: dict[str, Mapping[str, Any]] = {}
    for snapshot in snapshots:
        product_id = _product_id(snapshot)
        if product_id not in allowset:
            continue
        if product_id in by_product:
            raise PilotSafetyError("PILOT_PRODUCT_SNAPSHOT_DUPLICATE")
        by_product[product_id] = snapshot

    missing = [product_id for product_id in allowlist if product_id not in by_product]
    if missing:
        raise PilotSafetyError("PILOT_ALLOWLIST_PRODUCT_MISSING")

    selected = [by_product[product_id] for product_id in allowlist]

    if config.execution_enabled:
        if browser_factory is None or observe_draft is None:
            raise PilotSafetyError("PILOT_EXECUTION_ADAPTERS_REQUIRED")
        if any(_management_state(snapshot) != "MANAGED" for snapshot in selected):
            raise PilotSafetyError("PILOT_REQUIRES_MANAGED")

    cycle = run_cycle(
        selected,
        execute_drafts=config.execution_enabled,
        browser_factory=browser_factory,
        observe_draft=observe_draft,
    )

    return {
        "pilot": {
            "mode": "DRAFT_EXECUTION" if config.execution_enabled else "DRY_RUN",
            "allowlisted_product_ids": list(allowlist),
            "selected_count": len(selected),
            "batch_cap": config.max_items,
            "publish_authority": False,
            "paid_promotion_authority": False,
            "automatic_active_listing_changes": False,
            "management_state_mutation": False,
        },
        **cycle,
    }
