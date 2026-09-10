import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from gumtree_availability import (  # noqa: E402
    AVAILABLE,
    NOT_APPLICABLE,
    UNKNOWN,
    UNAVAILABLE,
    resolve_availability,
)


def product(
    *,
    title="Test Fish",
    handle="test-fish",
    product_type="Fish",
    status="ACTIVE",
    inventory=10,
    tracks_inventory=True,
    override=None,
):
    return {
        "shopify_product_id": "123",
        "shopify_gid": "gid://shopify/Product/123",
        "title": title,
        "handle": handle,
        "product_type": product_type,
        "status": status,
        "inventory": inventory,
        "tracks_inventory": tracks_inventory,
        "gumtree": {"gumtree_availability_override": override},
    }


def policy(name="WHEN_IN_STOCK", min_stock=1, stockout_policy=None):
    return {
        "gumtree_policy": name,
        "gumtree_min_stock": min_stock,
        "gumtree_stockout_policy": stockout_policy,
    }


def test_rcs_override_available_even_when_inventory_untracked():
    p = product(
        title="RCS Red Cherry Shrimp 1-3cm",
        product_type="Shrimps",
        inventory=0,
        tracks_inventory=False,
        override="AVAILABLE",
    )
    decision = resolve_availability(p, policy("WHEN_IN_STOCK", 10))
    assert decision.status == AVAILABLE
    assert decision.authoritative is True
    assert decision.reason_code == "AVAILABLE_BY_OVERRIDE"


def test_unavailable_override_blocks_listing():
    p = product(tracks_inventory=False, override="UNAVAILABLE")
    decision = resolve_availability(p, policy("WHEN_IN_STOCK", 1))
    assert decision.status == UNAVAILABLE
    assert decision.reason_code == "UNAVAILABLE_BY_OVERRIDE"


def test_invalid_override_never_grants_availability():
    p = product(tracks_inventory=False, override="YES")
    decision = resolve_availability(p, policy("WHEN_IN_STOCK", 1))
    assert decision.status == UNKNOWN
    assert decision.authoritative is False
    assert decision.review_required is True
    assert "INVALID_AVAILABILITY_OVERRIDE" in decision.errors


def test_blackworms_always_on_keep_active_is_stock_not_applicable():
    p = product(
        title="LBW Australian Blackworms Live Worms",
        product_type="Fish Food",
        inventory=0,
        tracks_inventory=False,
    )
    decision = resolve_availability(
        p, policy("ALWAYS_ON", 1, stockout_policy="KEEP_ACTIVE")
    )
    assert decision.status == NOT_APPLICABLE
    assert decision.reason_code == "ALWAYS_ON_KEEP_ACTIVE"


def test_tracked_white_caridina_above_minimum_is_available():
    p = product(
        title="White Caridina Shrimps 2-4cm ADULTS",
        product_type="Shrimps",
        inventory=50,
        tracks_inventory=True,
    )
    decision = resolve_availability(p, policy("WHEN_IN_STOCK", 5))
    assert decision.status == AVAILABLE
    assert decision.reason_code == "TRACKED_STOCK_AT_OR_ABOVE_MIN"


def test_tracked_scarlet_blue_endler_above_minimum_is_available():
    p = product(
        title="Endler - Scarlet Blue (Poecillia wingei)",
        product_type="Endlers",
        inventory=13,
        tracks_inventory=True,
    )
    decision = resolve_availability(p, policy("WHEN_IN_STOCK", 2))
    assert decision.status == AVAILABLE


def test_tracked_el_tigre_zero_stock_is_unavailable():
    p = product(
        title="Endler - EL TIGRE (Poecillia wingei) 3-5cm",
        product_type="Endlers",
        inventory=0,
        tracks_inventory=True,
    )
    decision = resolve_availability(p, policy("WHEN_IN_STOCK", 2))
    assert decision.status == UNAVAILABLE
    assert decision.reason_code == "TRACKED_STOCK_BELOW_MIN"


def test_untracked_bt_betta_quantity_one_is_available_by_unique_rule():
    p = product(
        title="1BT11 - Halfmoon Plakat Betta Male",
        handle="1bt11",
        product_type="Domesticated Betta",
        inventory=1,
        tracks_inventory=False,
    )
    decision = resolve_availability(p, policy("UNIQUE", 1))
    assert decision.status == AVAILABLE
    assert decision.reason_code == "AVAILABLE_BY_UNIQUE_BETTA_RULE"
    assert decision.source == "UNIQUE_BETTA_RULE"


def test_untracked_bt_betta_zero_quantity_is_unavailable():
    p = product(
        title="2BT24 - Teal Halfmoon Betta Male",
        handle="2bt24",
        product_type="Domesticated Betta",
        inventory=0,
        tracks_inventory=False,
    )
    decision = resolve_availability(p, policy("UNIQUE", 1))
    assert decision.status == UNAVAILABLE
    assert decision.reason_code == "UNIQUE_BETTA_SOLD_OR_ZERO"


def test_bt_like_text_on_non_betta_does_not_qualify():
    p = product(
        title="1BT11 Aquarium Tool",
        handle="1bt11-aquarium-tool",
        product_type="Aquarium Equipment",
        inventory=1,
        tracks_inventory=False,
    )
    decision = resolve_availability(p, policy("UNIQUE", 1))
    assert decision.status == UNKNOWN
    assert decision.reason_code == "UNTRACKED_STOCK_DEPENDENT_POLICY"


def test_betta_without_bt_identifier_does_not_get_unique_exception():
    p = product(
        title="Halfmoon Betta Male",
        handle="halfmoon-betta-male",
        product_type="Domesticated Betta",
        inventory=1,
        tracks_inventory=False,
    )
    decision = resolve_availability(p, policy("UNIQUE", 1))
    assert decision.status == UNKNOWN


def test_untracked_non_betta_stock_dependent_product_requires_review():
    p = product(
        title="Assorted Guppy",
        product_type="Guppies",
        inventory=100,
        tracks_inventory=False,
    )
    decision = resolve_availability(p, policy("WHEN_IN_STOCK", 5))
    assert decision.status == UNKNOWN
    assert decision.authoritative is False
    assert decision.review_required is True
    assert decision.reason_code == "UNTRACKED_STOCK_DEPENDENT_POLICY"


def test_do_not_list_is_not_applicable():
    p = product(inventory=100, tracks_inventory=True)
    decision = resolve_availability(p, policy("DO_NOT_LIST", 1))
    assert decision.status == NOT_APPLICABLE
    assert decision.reason_code == "EXCLUDED_POLICY"


def test_inactive_product_cannot_be_resurrected_by_available_override():
    p = product(
        status="ARCHIVED",
        inventory=10,
        tracks_inventory=True,
        override="AVAILABLE",
    )
    decision = resolve_availability(p, policy("WHEN_IN_STOCK", 1))
    assert decision.status == UNAVAILABLE
    assert decision.reason_code == "PRODUCT_INACTIVE"


def test_tracked_product_missing_inventory_is_unknown():
    p = product(inventory=None, tracks_inventory=True)
    decision = resolve_availability(p, policy("WHEN_IN_STOCK", 1))
    assert decision.status == UNKNOWN
    assert decision.review_required is True
    assert "INVENTORY_DATA_MISSING" in decision.errors


def test_explicit_zero_minimum_stock_is_respected():
    p = product(inventory=0, tracks_inventory=True)
    decision = resolve_availability(p, policy("WHEN_IN_STOCK", 0))
    assert decision.status == AVAILABLE


def test_tracked_unique_betta_also_resolves_available():
    p = product(
        title="3BT10 - Halfmoon Betta Male",
        handle="3bt10",
        product_type="Domesticated Betta",
        inventory=1,
        tracks_inventory=True,
    )
    decision = resolve_availability(p, policy("UNIQUE", 1))
    assert decision.status == AVAILABLE
