import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from gumtree_config import classify_product  # noqa: E402
from shopify_reader import normalize_product  # noqa: E402


def node(metafields=None, inventory=100):
    return {
        "id": "gid://shopify/Product/123",
        "legacyResourceId": "123",
        "title": "Test Fish",
        "handle": "test-fish",
        "productType": "Fish",
        "status": "ACTIVE",
        "totalInventory": inventory,
        "tracksInventory": True,
        "onlineStoreUrl": "https://example.test/products/test-fish",
        "priceRangeV2": {
            "minVariantPrice": {"amount": "12.95", "currencyCode": "AUD"},
            "maxVariantPrice": {"amount": "12.95", "currencyCode": "AUD"},
        },
        "metafields": {"nodes": metafields or []},
    }


def mf(key, value, type_="single_line_text_field"):
    return {"namespace": "nta", "key": key, "value": value, "type": type_}


def test_live_reader_shape_preserves_unconfigured_safety_gate():
    normalized = normalize_product(node())
    decision = classify_product(normalized)
    assert normalized["inventory"] == 100
    assert decision.config_state == "UNCONFIGURED"
    assert decision.report_only is True
    assert decision.allowed_to_create is False


def test_reader_maps_policy_and_integer_fields():
    normalized = normalize_product(node([
        mf("gumtree_policy", "WHEN_IN_STOCK"),
        mf("gumtree_min_stock", "10", "number_integer"),
    ]))
    assert normalized["gumtree"]["gumtree_policy"] == "WHEN_IN_STOCK"
    assert normalized["gumtree"]["gumtree_min_stock"] == 10
    assert classify_product(normalized).config_state == "CONFIGURED"


def test_reader_preserves_availability_override_without_granting_configuration():
    normalized = normalize_product(node([
        mf("gumtree_availability_override", "AVAILABLE"),
    ]))
    assert normalized["gumtree"]["gumtree_availability_override"] == "AVAILABLE"
    decision = classify_product(normalized)
    assert decision.config_state == "UNCONFIGURED"
    assert decision.allowed_to_create is False


def test_invalid_integer_is_preserved_for_validator():
    normalized = normalize_product(node([mf("gumtree_min_stock", "not-a-number")]))
    decision = classify_product(normalized)
    assert decision.config_state == "CONFIG_ERROR"
    assert "INVALID_MIN_STOCK" in decision.errors


def test_zero_is_explicit_not_blank():
    normalized = normalize_product(node([mf("gumtree_min_stock", "0", "number_integer")]))
    decision = classify_product(normalized)
    assert normalized["gumtree"]["gumtree_min_stock"] == 0
    assert decision.config_state == "CONFIGURED"
