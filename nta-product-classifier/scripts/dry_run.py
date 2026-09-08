#!/usr/bin/env python3
from classifier import classify


def expect(name, payload, status, primary=None, pricing=None, replenishable=None):
    result = classify(payload)
    assert result["status"] == status, (name, result)
    if primary is not None:
        assert result["classification"]["primary"] == primary, (name, result)
    if pricing is not None:
        assert result["classification"]["pricing_category"] == pricing, (name, result)
    if replenishable is not None:
        assert result["classification"]["replenishable"] == replenishable, (name, result)
    return result


fish = expect(
    "common livestock",
    {"shopify_product_type": "Fish", "individually_identified": False, "reorderable": True},
    "CLASSIFIED",
    "LIVESTOCK",
    "COMMON_LIVESTOCK",
    True,
)

tissue = expect(
    "tissue culture",
    {"shopify_product_type": "Tissue Culture", "reorderable": True},
    "CLASSIFIED",
    "PLANTS",
    "TISSUE_CULTURE",
    True,
)

food = expect(
    "fish food",
    {"shopify_product_type": "Fish Food", "reorderable": True},
    "CLASSIFIED",
    "DRY_GOODS",
    "FOOD_CONSUMABLES",
    True,
)

betta = expect(
    "individual betta",
    {
        "shopify_product_type": "Betta",
        "individually_identified": True,
        "reorderable": True,
        "title": "Blue Halfmoon Betta BT17",
    },
    "CLASSIFIED",
    "LIVESTOCK",
    "INDIVIDUAL_BETTAS",
    False,
)

unknown_betta = expect(
    "betta with unknown individual-identification state",
    {
        "shopify_product_type": "Fish",
        "title": "Premium Rare Betta",
        "individually_identified": "unknown",
        "reorderable": "unknown",
        "premium_rare": "unknown",
    },
    "REVIEW_REQUIRED",
    "LIVESTOCK",
)
assert unknown_betta["classification"]["pricing_category"] is None, unknown_betta
assert unknown_betta["classification"]["individually_identified"] == "unknown", unknown_betta
assert unknown_betta["classification"]["replenishable"] == "unknown", unknown_betta
assert "individually_identified" in unknown_betta["missing_or_conflicting_fields"], unknown_betta

ambiguous = expect(
    "title only",
    {"title": "Premium Rare Betta Tissue Culture Special"},
    "REVIEW_REQUIRED",
)

conflict = expect(
    "conflicting category evidence",
    {"shopify_product_type": "Fish", "shopify_category": "Aquarium Plants"},
    "REVIEW_REQUIRED",
)

dry_ambiguous = expect(
    "generic equipment without pricing evidence",
    {"shopify_product_type": "Aquarium Equipment", "reorderable": True},
    "REVIEW_REQUIRED",
    "DRY_GOODS",
)

print("DRY_RUN_PASS: deterministic-first product classifier; livestock, tissue culture, food, individual betta, unresolved-betta tri-state gate, title-only ambiguity, conflicting category evidence, and dry-goods pricing ambiguity; no Shopify writes, network calls, or model calls")
print("Common livestock:", fish["classification"]["pricing_category"])
print("Tissue culture:", tissue["classification"]["pricing_category"])
print("Fish food:", food["classification"]["pricing_category"])
print("Individual betta replenishable:", betta["classification"]["replenishable"])
print("Unknown betta status:", unknown_betta["status"])
print("Unknown betta individual identification:", unknown_betta["classification"]["individually_identified"])
print("Unknown betta pricing category:", unknown_betta["classification"]["pricing_category"])
print("Title-only status:", ambiguous["status"])
print("Conflicting evidence status:", conflict["status"])
