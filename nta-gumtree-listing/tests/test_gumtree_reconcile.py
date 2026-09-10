import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from gumtree_reconcile import reconcile  # noqa: E402


def snap(
    *,
    config_state="CONFIGURED",
    policy="WHEN_IN_STOCK",
    availability="AVAILABLE",
    management_state="MANAGED",
    actual_state="ACTIVE",
    dirty_flags=None,
    **extra,
):
    data = {
        "run_id": "run-1",
        "product": {
            "config_state": config_state,
            "management_state": management_state,
            "policy": policy,
            "availability_status": availability,
        },
        "resolved_policy": {
            "config_state": config_state,
            "policy": policy,
            "availability_status": availability,
        },
        "advertisement": {
            "ad_id": "GT-NTA-000001",
            "management_state": management_state,
            "dirty_flags": dirty_flags or [],
        },
        "gumtree_state": {
            "actual_state": actual_state,
            "matching_instance_count": 1,
        },
    }
    for section, values in extra.items():
        if section in data and isinstance(values, dict):
            data[section].update(values)
        else:
            data[section] = values
    return data


def assert_action(snapshot, action, reason=None):
    result = reconcile(snapshot)
    assert result.action == action
    if reason:
        assert result.reason_code == reason
    return result


def test_unconfigured_always_goes_to_config_review():
    assert_action(snap(config_state="UNCONFIGURED", actual_state="MISSING"), "CONFIG_REVIEW", "PRODUCT_UNCONFIGURED")


def test_config_error_goes_to_config_review():
    assert_action(snap(config_state="CONFIG_ERROR"), "CONFIG_REVIEW", "CONFIG_INVALID")


def test_duplicate_overrides_normal_reconciliation():
    s = snap(actual_state="ACTIVE")
    s["gumtree_state"]["duplicate_suspected"] = True
    assert_action(s, "DUPLICATE_REVIEW", "DUPLICATE_SUSPECTED")


def test_unmapped_identity_goes_to_identity_review():
    assert_action(snap(management_state="DISCOVERED"), "IDENTITY_REVIEW", "IDENTITY_NOT_MAPPED")


def test_unknown_actual_state_is_error():
    assert_action(snap(actual_state="UNKNOWN"), "ERROR", "ACTUAL_STATE_UNCERTAIN")


def test_stale_snapshot_is_error():
    s = snap()
    s["gumtree_state"]["snapshot_stale"] = True
    assert_action(s, "ERROR", "GUMTREE_SNAPSHOT_UNSAFE")


def test_active_missing_creates_draft():
    result = assert_action(snap(actual_state="MISSING"), "CREATE_DRAFT", "ACTIVE_BUT_MISSING")
    assert result.executable is True
    assert result.review_required is False


def test_active_clean_draft_is_no_action():
    assert_action(snap(actual_state="DRAFT"), "NO_ACTION", "DRAFT_CURRENT")


def test_active_dirty_draft_updates_draft():
    result = assert_action(
        snap(actual_state="DRAFT", dirty_flags=["CONTENT_DIRTY", "PRICE_DIRTY"]),
        "UPDATE_DRAFT",
        "DRAFT_DIRTY",
    )
    assert result.dirty_flags == ("CONTENT_DIRTY", "PRICE_DIRTY")
    assert result.executable is True


def test_active_clean_active_is_no_action():
    assert_action(snap(actual_state="ACTIVE"), "NO_ACTION", "ACTIVE_CURRENT")


def test_active_dirty_active_requires_review():
    result = assert_action(
        snap(actual_state="ACTIVE", dirty_flags=["PRICE_DIRTY"]),
        "UPDATE_ACTIVE_REVIEW",
        "ACTIVE_DIRTY",
    )
    assert result.review_required is True
    assert result.executable is False


def test_active_expired_requires_relist_review():
    assert_action(snap(actual_state="EXPIRED"), "RELIST_REVIEW", "ACTIVE_BUT_EXPIRED")


def test_absent_active_requires_pause_review():
    assert_action(
        snap(policy="DO_NOT_LIST", availability="NOT_APPLICABLE", actual_state="ACTIVE"),
        "PAUSE_REVIEW",
        "ABSENT_BUT_ACTIVE",
    )


def test_absent_draft_requires_remove_review():
    assert_action(
        snap(policy="DO_NOT_LIST", availability="NOT_APPLICABLE", actual_state="DRAFT"),
        "REMOVE_REVIEW",
        "ABSENT_BUT_DRAFT",
    )


@pytest.mark.parametrize("actual_state", ["MISSING", "EXPIRED", "SOLD", "REMOVED", "PAUSED"])
def test_absent_non_live_states_are_no_action(actual_state):
    assert_action(
        snap(policy="DO_NOT_LIST", availability="NOT_APPLICABLE", actual_state=actual_state),
        "NO_ACTION",
    )


def test_when_in_stock_unavailable_desires_absent():
    result = reconcile(snap(policy="WHEN_IN_STOCK", availability="UNAVAILABLE", actual_state="ACTIVE"))
    assert result.desired_state == "ABSENT"
    assert result.action == "PAUSE_REVIEW"


def test_when_in_stock_unknown_availability_errors():
    assert_action(
        snap(policy="WHEN_IN_STOCK", availability="UNKNOWN", actual_state="MISSING"),
        "ERROR",
        "AVAILABILITY_UNCERTAIN",
    )


def test_always_on_ignores_inventory_and_desires_active():
    result = reconcile(snap(policy="ALWAYS_ON", availability="NOT_APPLICABLE", actual_state="MISSING"))
    assert result.desired_state == "ACTIVE"
    assert result.action == "CREATE_DRAFT"


def test_inactive_campaign_desires_absent():
    s = snap(policy="CAMPAIGN", availability="AVAILABLE", actual_state="ACTIVE")
    s["resolved_policy"]["campaign_active"] = False
    result = reconcile(s)
    assert result.desired_state == "ABSENT"
    assert result.action == "PAUSE_REVIEW"


def test_reconcile_is_idempotent_for_same_snapshot():
    s = snap(actual_state="DRAFT", dirty_flags=["CONTENT_DIRTY", "CONTENT_DIRTY"])
    first = reconcile(s).as_dict()
    second = reconcile(s).as_dict()
    assert first == second


def test_unknown_dirty_flags_are_ignored_not_executed():
    result = reconcile(snap(actual_state="ACTIVE", dirty_flags=["AI_SAYS_CHANGE_IT"]))
    assert result.action == "NO_ACTION"
    assert result.dirty_flags == ()


def test_publish_is_never_emitted():
    scenarios = [
        snap(actual_state="MISSING"),
        snap(actual_state="DRAFT", dirty_flags=["CONTENT_DIRTY"]),
        snap(actual_state="ACTIVE", dirty_flags=["PRICE_DIRTY"]),
        snap(policy="DO_NOT_LIST", availability="NOT_APPLICABLE", actual_state="ACTIVE"),
    ]
    for scenario in scenarios:
        assert reconcile(scenario).action != "PUBLISH"
