from normalizer import normalize_cost


def assert_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def main():
    standard = normalize_cost(
        {
            "supplier_cost": "110.00",
            "gst_basis": "INC_GST",
            "supplier_order_qty": 1,
            "supplier_pack_size": 10,
            "shopify_sell_unit": 1,
            "bonus_base_units": 0,
            "attributable_line_cost_ex_gst": 0,
        }
    )
    assert_equal(standard["status"], "READY", "standard status")
    assert_equal(standard["cost"]["ordered_base_units"], 10, "standard ordered units")
    assert_equal(standard["cost"]["shopify_retail_units_produced"], 10, "standard retail units")
    assert_equal(standard["cost"]["supplier_line_cost_ex_gst"], "100", "standard ex-GST line cost")
    assert_equal(standard["cost"]["unit_purchase_cost_ex_gst"], "10", "standard unit cost")
    assert_equal(standard["cost"]["landed_cost_ex_gst"], "10", "standard landed cost")

    free_goods = normalize_cost(
        {
            "supplier_cost": "132.00",
            "gst_basis": "INC_GST",
            "supplier_order_qty": 1,
            "supplier_pack_size": 12,
            "shopify_sell_unit": 1,
            "bonus_base_units": 2,
            "attributable_line_cost_ex_gst": 0,
        }
    )
    assert_equal(free_goods["status"], "READY", "free-goods status")
    assert_equal(free_goods["cost"]["ordered_base_units"], 14, "free-goods ordered units")
    assert_equal(free_goods["cost"]["shopify_retail_units_produced"], 14, "free-goods retail units")
    assert_equal(free_goods["cost"]["supplier_line_cost_ex_gst"], "120", "free-goods ex-GST line cost")
    assert_equal(free_goods["cost"]["unit_purchase_cost_ex_gst"], "8.5714", "free-goods unit cost")

    shopify_pack = normalize_cost(
        {
            "supplier_cost": "55.00",
            "gst_basis": "INC_GST",
            "supplier_order_qty": 2,
            "supplier_pack_size": 5,
            "shopify_sell_unit": 5,
            "bonus_base_units": 0,
            "attributable_line_cost_ex_gst": "10.00",
        }
    )
    assert_equal(shopify_pack["status"], "READY", "Shopify-pack status")
    assert_equal(shopify_pack["cost"]["shopify_retail_units_produced"], 2, "Shopify-pack retail units")
    assert_equal(shopify_pack["cost"]["unit_purchase_cost_ex_gst"], "25", "Shopify-pack purchase cost")
    assert_equal(shopify_pack["cost"]["attributable_unit_cost_ex_gst"], "5", "Shopify-pack attributable cost")
    assert_equal(shopify_pack["cost"]["landed_cost_ex_gst"], "30", "Shopify-pack landed cost")

    unknown_gst = normalize_cost(
        {
            "supplier_cost": "110.00",
            "gst_basis": "UNKNOWN",
            "supplier_order_qty": 1,
            "supplier_pack_size": 10,
            "shopify_sell_unit": 1,
        }
    )
    assert_equal(unknown_gst["status"], "REVIEW_REQUIRED", "unknown-GST status")
    assert "gst_basis" in unknown_gst["missing_or_invalid_fields"]

    bad_unit_mapping = normalize_cost(
        {
            "supplier_cost": "100.00",
            "gst_basis": "EX_GST",
            "supplier_order_qty": 1,
            "supplier_pack_size": 10,
            "shopify_sell_unit": 3,
        }
    )
    assert_equal(bad_unit_mapping["status"], "REVIEW_REQUIRED", "bad-unit-mapping status")

    print(
        "DRY_RUN_PASS: deterministic supplier unit-cost normalizer; "
        "standard GST, free goods, Shopify-pack selling unit, unknown GST, and invalid unit mapping; "
        "no Shopify writes, pricing decisions, network calls, or model calls"
    )
    print(f"Standard landed cost ex GST: ${standard['cost']['landed_cost_ex_gst']}")
    print(f"12 + 2 FREE unit purchase cost ex GST: ${free_goods['cost']['unit_purchase_cost_ex_gst']}")
    print(f"Whole-pack landed cost ex GST: ${shopify_pack['cost']['landed_cost_ex_gst']}")


if __name__ == "__main__":
    main()
