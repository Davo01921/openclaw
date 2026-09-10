import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from gumtree_config import all_gumtree_fields_blank, classify_product  # noqa: E402


def product(gumtree):
    return {
        "shopify_product_id": "123",
        "title": "Test Livestock",
        "inventory": 100,
        "gumtree": gumtree,
    }


def test_all_blank_is_unconfigured_even_with_high_inventory():
    decision = classify_product(product({}))
    assert decision.config_state == "UNCONFIGURED"
    assert decision.report_only is True
    assert decision.allowed_to_create is False
    assert decision.reason == "ALL_GUMTREE_FIELDS_BLANK"


def test_whitespace_and_null_are_blank():
    assert all_gumtree_fields_blank({"gumtree_policy": "   ", "gumtree_priority": None})


def test_zero_is_not_blank():
    assert not all_gumtree_fields_blank({"gumtree_min_stock": 0})


def test_explicit_do_not_list_is_excluded():
    decision = classify_product(product({"gumtree_policy": "DO_NOT_LIST"}))
    assert decision.config_state == "EXCLUDED"
    assert decision.allowed_to_create is False


def test_valid_policy_is_configured():
    decision = classify_product(product({"gumtree_policy": "WHEN_IN_STOCK"}))
    assert decision.config_state == "CONFIGURED"
    assert decision.allowed_to_create is True


def test_invalid_policy_is_config_error():
    decision = classify_product(product({"gumtree_policy": "MAYBE"}))
    assert decision.config_state == "CONFIG_ERROR"
    assert "INVALID_POLICY" in decision.errors
    assert decision.allowed_to_create is False


def test_campaign_requires_dates():
    decision = classify_product(product({"gumtree_policy": "CAMPAIGN"}))
    assert decision.config_state == "CONFIG_ERROR"
    assert "CAMPAIGN_REQUIRES_START" in decision.errors
    assert "CAMPAIGN_REQUIRES_END" in decision.errors


def test_grace_period_requires_days():
    decision = classify_product(product({"gumtree_stockout_policy": "GRACE_PERIOD"}))
    assert decision.config_state == "CONFIG_ERROR"
    assert "GRACE_PERIOD_REQUIRES_DAYS" in decision.errors
