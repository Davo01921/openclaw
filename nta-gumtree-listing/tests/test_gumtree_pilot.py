from __future__ import annotations

import pathlib
import sys

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from gumtree_pilot import PilotConfig, PilotSafetyError, run_pilot


def snapshot(product_id: str, *, management_state: str = "MANAGED"):
    return {
        "product": {
            "shopify_product_id": product_id,
            "config_state": "CONFIGURED",
            "management_state": management_state,
        },
        "resolved_policy": {
            "policy": "WHEN_IN_STOCK",
            "availability_status": "AVAILABLE",
            "config_state": "CONFIGURED",
        },
        "advertisement": {
            "ad_id": f"AD-{product_id[-1]}",
            "management_state": management_state,
            "dirty_flags": [],
        },
        "gumtree_state": {
            "actual_state": "ACTIVE",
            "matching_instance_count": 1,
        },
    }


def test_dry_run_is_default_and_uses_only_allowlist():
    p1 = "gid://shopify/Product/1"
    p2 = "gid://shopify/Product/2"
    result = run_pilot(
        [snapshot(p1), snapshot(p2)],
        config=PilotConfig((p1,)),
    )
    assert result["pilot"]["mode"] == "DRY_RUN"
    assert result["pilot"]["selected_count"] == 1
    assert result["dashboard"]["total_items"] == 1
    assert result["pilot"]["publish_authority"] is False


def test_missing_allowlisted_product_fails_closed():
    with pytest.raises(PilotSafetyError, match="PILOT_ALLOWLIST_PRODUCT_MISSING"):
        run_pilot([], config=PilotConfig(("gid://shopify/Product/1",)))


def test_duplicate_allowlist_rejected():
    product_id = "gid://shopify/Product/1"
    with pytest.raises(PilotSafetyError, match="PILOT_ALLOWLIST_DUPLICATE"):
        run_pilot([snapshot(product_id)], config=PilotConfig((product_id, product_id)))


def test_batch_cap_cannot_exceed_hard_cap():
    with pytest.raises(PilotSafetyError, match="PILOT_BATCH_CAP_INVALID"):
        run_pilot([], config=PilotConfig(("gid://shopify/Product/1",), max_items=4))


def test_allowlist_cannot_exceed_configured_cap():
    ids = tuple(f"gid://shopify/Product/{n}" for n in range(1, 4))
    with pytest.raises(PilotSafetyError, match="PILOT_ALLOWLIST_EXCEEDS_CAP"):
        run_pilot([snapshot(x) for x in ids], config=PilotConfig(ids, max_items=2))


def test_execution_requires_adapters():
    product_id = "gid://shopify/Product/1"
    with pytest.raises(PilotSafetyError, match="PILOT_EXECUTION_ADAPTERS_REQUIRED"):
        run_pilot(
            [snapshot(product_id)],
            config=PilotConfig((product_id,), execution_enabled=True),
        )


def test_execution_requires_managed_state_before_browser():
    product_id = "gid://shopify/Product/1"
    with pytest.raises(PilotSafetyError, match="PILOT_REQUIRES_MANAGED"):
        run_pilot(
            [snapshot(product_id, management_state="MAPPED")],
            config=PilotConfig((product_id,), execution_enabled=True),
            browser_factory=lambda *_: object(),
            observe_draft=lambda *_: {},
        )


def test_duplicate_snapshot_for_allowlisted_product_rejected():
    product_id = "gid://shopify/Product/1"
    with pytest.raises(PilotSafetyError, match="PILOT_PRODUCT_SNAPSHOT_DUPLICATE"):
        run_pilot(
            [snapshot(product_id), snapshot(product_id)],
            config=PilotConfig((product_id,)),
        )


def test_pilot_never_claims_publish_or_active_change_authority():
    product_id = "gid://shopify/Product/1"
    result = run_pilot([snapshot(product_id)], config=PilotConfig((product_id,)))
    pilot = result["pilot"]
    assert pilot["publish_authority"] is False
    assert pilot["paid_promotion_authority"] is False
    assert pilot["automatic_active_listing_changes"] is False
    assert pilot["management_state_mutation"] is False
