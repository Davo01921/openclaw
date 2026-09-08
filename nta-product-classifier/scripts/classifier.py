#!/usr/bin/env python3
"""Deterministic-first NTA product classifier.

No Shopify writes, network calls, or model calls.
Classification is based on structured authoritative fields only.
Titles and free-form names are evidence only and never silently drive
commercially important classification decisions.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional, Tuple

PRIMARY_MAP = {
    # livestock
    "fish": ("LIVESTOCK", "FISH"),
    "aquarium fish": ("LIVESTOCK", "FISH"),
    "betta": ("LIVESTOCK", "BETTA"),
    "shrimp": ("LIVESTOCK", "SHRIMP"),
    "aquarium shrimp": ("LIVESTOCK", "SHRIMP"),
    "snail": ("LIVESTOCK", "SNAIL"),
    "snails": ("LIVESTOCK", "SNAIL"),
    "crayfish": ("LIVESTOCK", "CRAYFISH"),
    "crab": ("LIVESTOCK", "CRAB"),
    "aquatic livestock": ("LIVESTOCK", "OTHER_LIVESTOCK"),
    "livestock": ("LIVESTOCK", "OTHER_LIVESTOCK"),
    # plants
    "aquarium plants": ("PLANTS", "AQUARIUM_PLANT"),
    "aquarium plant": ("PLANTS", "AQUARIUM_PLANT"),
    "plants": ("PLANTS", "AQUARIUM_PLANT"),
    "plant": ("PLANTS", "AQUARIUM_PLANT"),
    "tissue culture": ("PLANTS", "TISSUE_CULTURE"),
    "tissue culture plant": ("PLANTS", "TISSUE_CULTURE"),
    # dry goods
    "fish food": ("DRY_GOODS", "FOOD_CONSUMABLE"),
    "aquarium food": ("DRY_GOODS", "FOOD_CONSUMABLE"),
    "food": ("DRY_GOODS", "FOOD_CONSUMABLE"),
    "consumables": ("DRY_GOODS", "FOOD_CONSUMABLE"),
    "water treatment": ("DRY_GOODS", "FOOD_CONSUMABLE"),
    "aquarium equipment": ("DRY_GOODS", "EQUIPMENT"),
    "equipment": ("DRY_GOODS", "EQUIPMENT"),
    "filter": ("DRY_GOODS", "EQUIPMENT"),
    "lighting": ("DRY_GOODS", "EQUIPMENT"),
    "heater": ("DRY_GOODS", "EQUIPMENT"),
    "pump": ("DRY_GOODS", "EQUIPMENT"),
    "aquarium accessory": ("DRY_GOODS", "ACCESSORY"),
    "aquarium accessories": ("DRY_GOODS", "ACCESSORY"),
    "accessory": ("DRY_GOODS", "ACCESSORY"),
    "accessories": ("DRY_GOODS", "ACCESSORY"),
    "medication": ("DRY_GOODS", "MEDICATION"),
    "aquarium": ("DRY_GOODS", "AQUARIUM"),
    "tank": ("DRY_GOODS", "AQUARIUM"),
    "stand": ("DRY_GOODS", "STAND_CABINET"),
    "cabinet": ("DRY_GOODS", "STAND_CABINET"),
    "spare parts": ("DRY_GOODS", "SPARE_PART"),
    "dry goods": ("DRY_GOODS", "OTHER_DRY_GOODS"),
}

VALID_PRIMARY = {"LIVESTOCK", "PLANTS", "DRY_GOODS"}
VALID_PRICING = {
    "COMMON_LIVESTOCK",
    "PREMIUM_RARE_LIVESTOCK",
    "INDIVIDUAL_BETTAS",
    "SHRIMP_SPECIALIST_INVERTEBRATES",
    "AQUARIUM_PLANTS",
    "TISSUE_CULTURE",
    "FOOD_CONSUMABLES",
    "COMMODITY_BRANDED_EQUIPMENT",
    "SPECIALIST_NICHE_EQUIPMENT",
    "LOW_COST_ACCESSORIES",
}


def norm(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().replace("_", " ").replace("-", " ").split())


def bool_or_none(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return None
    if isinstance(value, str):
        n = value.strip().lower()
        if n in {"true", "yes", "1"}:
            return True
        if n in {"false", "no", "0"}:
            return False
        if n in {"unknown", "null", "none", "unset"}:
            return None
    return None


def add_candidate(candidates: List[Tuple[str, str, str]], source: str, value: Any) -> None:
    n = norm(value)
    if not n:
        return
    mapped = PRIMARY_MAP.get(n)
    if mapped:
        candidates.append((mapped[0], mapped[1], f"{source}={value}"))


def tri_state(value: Optional[bool]) -> Any:
    return "unknown" if value is None else value


def classify(data: Dict[str, Any]) -> Dict[str, Any]:
    candidates: List[Tuple[str, str, str]] = []
    evidence: List[str] = []
    issues: List[str] = []
    notes: List[str] = []

    explicit_primary = data.get("authoritative_primary")
    if explicit_primary:
        ep = str(explicit_primary).strip().upper()
        if ep in VALID_PRIMARY:
            candidates.append((ep, str(data.get("authoritative_subtype") or "").strip().upper() or "UNKNOWN", "authoritative_primary"))
        else:
            issues.append("authoritative_primary")

    for source in ("shopify_product_type", "shopify_category", "verified_supplier_category"):
        before = len(candidates)
        add_candidate(candidates, source, data.get(source))
        if data.get(source) and len(candidates) == before:
            notes.append(f"Unmapped authoritative category: {source}={data.get(source)}")

    primaries = {c[0] for c in candidates}
    if len(primaries) > 1:
        return {
            "status": "REVIEW_REQUIRED",
            "classification": None,
            "missing_or_conflicting_fields": ["primary_category_evidence"],
            "notes": [f"Conflicting authoritative primary evidence: {sorted(primaries)}"] + notes,
        }
    if not candidates:
        return {
            "status": "REVIEW_REQUIRED",
            "classification": None,
            "missing_or_conflicting_fields": ["authoritative_category_evidence"],
            "notes": notes + ["Title/common/scientific names are evidence only and were not used as silent authority."],
        }

    primary = candidates[0][0]
    subtype_candidates = {c[1] for c in candidates if c[1] and c[1] != "UNKNOWN"}
    subtype = next(iter(subtype_candidates)) if len(subtype_candidates) == 1 else (str(data.get("authoritative_subtype") or "").strip().upper() or "UNKNOWN")
    evidence.extend(c[2] for c in candidates)

    # Preserve tri-state values. Unknown is not false.
    individually_identified = bool_or_none(data.get("individually_identified"))

    tissue_culture = bool_or_none(data.get("tissue_culture"))
    if tissue_culture is None:
        tissue_culture = subtype == "TISSUE_CULTURE"

    if tissue_culture and primary != "PLANTS":
        issues.append("tissue_culture_conflicts_with_primary")
    if individually_identified is True and primary != "LIVESTOCK":
        issues.append("individually_identified_conflicts_with_primary")

    premium_rare = bool_or_none(data.get("premium_rare")) or False
    specialist_niche = bool_or_none(data.get("specialist_niche")) or False
    low_cost_accessory = bool_or_none(data.get("low_cost_accessory")) or False
    commodity_branded = bool_or_none(data.get("commodity_branded")) or False

    # A Betta hint in free-form text is never classification authority. It is only
    # a safety gate: if individual-identification state is unresolved, pricing
    # classification must stop because COMMON_LIVESTOCK vs INDIVIDUAL_BETTAS
    # cannot be decided safely.
    title_words = set(norm(data.get("title")).split())
    betta_context = subtype == "BETTA" or (primary == "LIVESTOCK" and "betta" in title_words)

    explicit_pricing = data.get("pricing_category")
    pricing_category: Optional[str] = None
    if explicit_pricing:
        pc = str(explicit_pricing).strip().upper()
        if pc in VALID_PRICING:
            pricing_category = pc
            evidence.append("pricing_category=explicit")
        else:
            issues.append("pricing_category")

    if pricing_category is None:
        if primary == "LIVESTOCK":
            if betta_context and individually_identified is None:
                issues.append("individually_identified")
                notes.append("Betta context detected; explicit individual-identification state is required before pricing category can be determined.")
            elif individually_identified is True and betta_context:
                pricing_category = "INDIVIDUAL_BETTAS"
            elif subtype in {"SHRIMP", "SNAIL", "CRAYFISH", "CRAB", "OTHER_LIVESTOCK"}:
                pricing_category = "SHRIMP_SPECIALIST_INVERTEBRATES"
            elif premium_rare:
                pricing_category = "PREMIUM_RARE_LIVESTOCK"
            else:
                pricing_category = "COMMON_LIVESTOCK"
        elif primary == "PLANTS":
            pricing_category = "TISSUE_CULTURE" if tissue_culture else "AQUARIUM_PLANTS"
        elif primary == "DRY_GOODS":
            if subtype in {"FOOD_CONSUMABLE", "MEDICATION"}:
                pricing_category = "FOOD_CONSUMABLES"
            elif low_cost_accessory and subtype == "ACCESSORY":
                pricing_category = "LOW_COST_ACCESSORIES"
            elif specialist_niche and subtype in {"EQUIPMENT", "ACCESSORY", "AQUARIUM", "STAND_CABINET", "SPARE_PART", "OTHER_DRY_GOODS"}:
                pricing_category = "SPECIALIST_NICHE_EQUIPMENT"
            elif commodity_branded and subtype in {"EQUIPMENT", "ACCESSORY", "AQUARIUM", "STAND_CABINET", "SPARE_PART", "OTHER_DRY_GOODS"}:
                pricing_category = "COMMODITY_BRANDED_EQUIPMENT"
            else:
                issues.append("pricing_category_evidence")

    false_replenishment_flags = {
        "individually_identified": individually_identified is True,
        "discontinued": bool_or_none(data.get("discontinued")) or False,
        "clearance_only": bool_or_none(data.get("clearance_only")) or False,
        "internal_use": bool_or_none(data.get("internal_use")) or False,
    }
    reorderable = bool_or_none(data.get("reorderable"))
    if any(false_replenishment_flags.values()) or reorderable is False:
        replenishable: Any = False
    elif reorderable is True:
        replenishable = True
    else:
        replenishable = "unknown"

    classification = {
        "primary": primary,
        "subtype": subtype,
        "pricing_category": pricing_category,
        "replenishable": replenishable,
        "individually_identified": tri_state(individually_identified),
        "tissue_culture": tissue_culture,
        "evidence": evidence,
    }

    if issues:
        return {
            "status": "REVIEW_REQUIRED",
            "classification": classification,
            "missing_or_conflicting_fields": sorted(set(issues)),
            "notes": notes,
        }

    return {
        "status": "CLASSIFIED",
        "classification": classification,
        "missing_or_conflicting_fields": [],
        "notes": notes,
    }


def main() -> None:
    payload = json.load(sys.stdin)
    print(json.dumps(classify(payload), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
