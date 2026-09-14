import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from gumtree_config import classify_product  # noqa: E402


def _product(gumtree):
    return {"shopify_product_id": "123", "title": "Test", "gumtree": gumtree}


def test_availability_override_alone_remains_unconfigured():
    decision = classify_product(_product({"gumtree_availability_override": "AVAILABLE"}))
    assert decision.config_state == "UNCONFIGURED"
    assert decision.allowed_to_create is False


def test_invalid_availability_override_is_rejected_when_configuration_is_active():
    decision = classify_product(_product({
        "gumtree_policy": "WHEN_IN_STOCK",
        "gumtree_availability_override": "MAYBE",
    }))
    assert decision.config_state == "CONFIG_ERROR"
    assert "INVALID_AVAILABILITY_OVERRIDE" in decision.errors
