from __future__ import annotations

from typing import Any

INVENTORY_ITEM_LEVEL_QUERY = """
query NtaInventoryItemLevelRead($inventoryItemId: ID!, $locationId: ID!) {
  inventoryItem(id: $inventoryItemId) {
    id
    sku
    inventoryLevel(locationId: $locationId) {
      id
      quantities(names: ["available", "on_hand", "committed"]) {
        name
        quantity
      }
      location { id name }
    }
  }
}
"""


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def build_inventory_read_variables(inventory_item_id: str, location_id: str) -> dict:
    errors = []
    if not _nonempty(inventory_item_id):
        errors.append("inventory_item_id")
    if not _nonempty(location_id):
        errors.append("location_id")
    if errors:
        return {"status": "REVIEW_REQUIRED", "errors": errors, "variables": None}
    return {
        "status": "READY",
        "errors": [],
        "variables": {
            "inventoryItemId": inventory_item_id.strip(),
            "locationId": location_id.strip(),
        },
    }


def parse_inventory_item_level_response(data: dict, *, inventory_item_id: str, location_id: str) -> dict:
    if not isinstance(data, dict):
        return {"status": "FAILED", "snapshot": None, "errors": ["response_data"]}
    item = data.get("inventoryItem")
    if not isinstance(item, dict) or item.get("id") != inventory_item_id:
        return {"status": "FAILED", "snapshot": None, "errors": ["inventory_item_identity"]}
    level = item.get("inventoryLevel")
    if not isinstance(level, dict):
        return {"status": "FAILED", "snapshot": None, "errors": ["inventory_level_not_found_at_location"]}
    location = level.get("location") or {}
    if location.get("id") != location_id:
        return {"status": "FAILED", "snapshot": None, "errors": ["location_identity"]}
    quantities = {q.get("name"): q.get("quantity") for q in level.get("quantities", []) if isinstance(q, dict)}
    for required in ("available", "on_hand", "committed"):
        if not isinstance(quantities.get(required), int) or isinstance(quantities.get(required), bool):
            return {"status": "FAILED", "snapshot": None, "errors": [f"quantity:{required}"]}
    return {
        "status": "SUCCESS",
        "snapshot": {
            "source": "FRESH_SHOPIFY_READ",
            "inventory_item_id": item.get("id"),
            "sku": item.get("sku"),
            "inventory_level_id": level.get("id"),
            "location_id": location.get("id"),
            "location_name": location.get("name"),
            "available": quantities["available"],
            "on_hand": quantities["on_hand"],
            "committed": quantities["committed"],
        },
        "errors": [],
    }
