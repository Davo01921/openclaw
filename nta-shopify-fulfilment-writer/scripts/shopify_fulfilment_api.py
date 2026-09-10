from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.error
import urllib.request
from typing import Any

DEFAULT_API_VERSION = "2026-07"
DEFAULT_SESSION_BRIDGE_PATH = (
    Path.home()
    / ".openclaw/workspace/nta-fred-shopify-auth/nta-betta-picture-processor/scripts/shopify-session-bridge.mjs"
)
FULFILMENT_READ_SCOPES = {
    "read_assigned_fulfillment_orders",
    "read_merchant_managed_fulfillment_orders",
    "read_third_party_fulfillment_orders",
    "read_marketplace_fulfillment_orders",
}
FULFILMENT_WRITE_SCOPES = {
    "write_assigned_fulfillment_orders",
    "write_merchant_managed_fulfillment_orders",
    "write_third_party_fulfillment_orders",
}

CAPABILITY_QUERY = """
query NtaFulfilmentAdapterCapability {
  currentAppInstallation {
    accessScopes { handle }
  }
}
"""

FULFILMENT_CREATE_MUTATION = """
mutation NtaFulfilmentCreate($fulfillment: FulfillmentInput!) {
  fulfillmentCreate(fulfillment: $fulfillment) {
    fulfillment { id status }
    userErrors { field message }
  }
}
"""

FULFILMENT_ORDER_READ_QUERY = """
query NtaFulfilmentOrderRead($id: ID!) {
  fulfillmentOrder(id: $id) {
    id
    status
    order { id }
    lineItems(first: 250) {
      nodes {
        id
        totalQuantity
        remainingQuantity
        inventoryItemId
      }
    }
  }
}
"""

INVENTORY_LEVEL_READ_QUERY = """
query NtaInventoryLevelRead($id: ID!) {
  inventoryLevel(id: $id) {
    id
    quantities(names: ["available", "on_hand", "committed"]) {
      name
      quantity
    }
    item { id sku }
    location { id name }
  }
}
"""


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if _nonempty(value):
            return value.strip()
    return None


def load_config() -> dict:
    configured_bridge = _env_first("NTA_SHOPIFY_SESSION_BRIDGE_PATH")
    bridge_path = Path(configured_bridge).expanduser() if configured_bridge else DEFAULT_SESSION_BRIDGE_PATH
    if bridge_path.is_file():
        return {
            "configured": True,
            "errors": [],
            "transport": "persisted_session_bridge",
            "bridge_path": str(bridge_path.resolve()),
            "domain": None,
            "token": None,
            "api_version": _env_first("SHOPIFY_API_VERSION") or DEFAULT_API_VERSION,
            "token_mode": "unknown",
        }
    if configured_bridge:
        return {
            "configured": False,
            "errors": ["NTA_SHOPIFY_SESSION_BRIDGE_PATH:invalid"],
            "transport": "persisted_session_bridge",
            "bridge_path": None,
            "domain": None,
            "token": None,
            "api_version": _env_first("SHOPIFY_API_VERSION") or DEFAULT_API_VERSION,
            "token_mode": "unknown",
        }

    domain = _env_first("SHOPIFY_STORE_DOMAIN", "SHOPIFY_SHOP_DOMAIN")
    token = _env_first("SHOPIFY_ADMIN_ACCESS_TOKEN", "SHOPIFY_ACCESS_TOKEN")
    api_version = _env_first("SHOPIFY_API_VERSION") or DEFAULT_API_VERSION
    token_mode = (_env_first("SHOPIFY_TOKEN_MODE") or "unknown").lower()
    errors: list[str] = []
    if not domain:
        errors.append("SHOPIFY_STORE_DOMAIN")
    elif "/" in domain or " " in domain:
        errors.append("SHOPIFY_STORE_DOMAIN:invalid")
    if not token:
        errors.append("SHOPIFY_ADMIN_ACCESS_TOKEN")
    if token_mode not in {"offline", "online", "unknown"}:
        errors.append("SHOPIFY_TOKEN_MODE:invalid")
    return {
        "configured": not errors,
        "errors": errors,
        "transport": "legacy_admin_token",
        "bridge_path": None,
        "domain": domain,
        "token": token,
        "api_version": api_version,
        "token_mode": token_mode,
    }


def _bridge_operation(query: str) -> str | None:
    operations = {
        CAPABILITY_QUERY.strip(): "capability",
        FULFILMENT_CREATE_MUTATION.strip(): "create_fulfillment",
        FULFILMENT_ORDER_READ_QUERY.strip(): "fulfillment_order",
        INVENTORY_LEVEL_READ_QUERY.strip(): "inventory_level",
    }
    return operations.get(query.strip())


def _supported_node_executable() -> str | None:
    configured = _env_first("NTA_SHOPIFY_SESSION_BRIDGE_NODE")
    candidates = [configured] if configured else [shutil.which("node"), "/opt/homebrew/bin/node", "/usr/local/bin/node"]
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            version = subprocess.run(
                [candidate, "--version"],
                text=True,
                capture_output=True,
                timeout=3,
                check=False,
            )
            major = int(version.stdout.strip().removeprefix("v").split(".", 1)[0])
        except (OSError, subprocess.TimeoutExpired, ValueError):
            continue
        if version.returncode == 0 and major >= 20:
            return candidate
    return None


def _bridge_request(config: dict, query: str, variables: dict | None, timeout: int) -> dict:
    operation = _bridge_operation(query)
    if not operation:
        return {"ok": False, "errors": ["bridge_operation_not_allowlisted"], "data": None, "auth": None}

    child_env = os.environ.copy()
    aliases = {
        "SHOPIFY_STORE_DOMAIN": "SHOPIFY_STORE",
        "SHOPIFY_API_KEY": "SHOPIFY_CLIENT_ID",
        "SHOPIFY_API_SECRET": "SHOPIFY_CLIENT_SECRET",
    }
    for target, source in aliases.items():
        if not _nonempty(child_env.get(target)) and _nonempty(child_env.get(source)):
            child_env[target] = child_env[source].strip()

    node = _supported_node_executable()
    if not node:
        return {"ok": False, "errors": ["bridge_node_20_required"], "data": None, "auth": None}
    payload = json.dumps({"operation": operation, "variables": variables or {}})
    try:
        completed = subprocess.run(
            [node, config["bridge_path"]],
            input=payload,
            text=True,
            capture_output=True,
            cwd=str(Path(config["bridge_path"]).parent.parent),
            env=child_env,
            timeout=timeout + 5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "errors": ["bridge_timeout"], "data": None, "auth": None}
    except OSError:
        return {"ok": False, "errors": ["bridge_unavailable"], "data": None, "auth": None}

    try:
        response = json.loads(completed.stdout.strip())
    except (json.JSONDecodeError, AttributeError):
        return {"ok": False, "errors": ["bridge_response_invalid"], "data": None, "auth": None}
    if not isinstance(response, dict):
        return {"ok": False, "errors": ["bridge_response_invalid"], "data": None, "auth": None}
    return {
        "ok": response.get("ok") is True and completed.returncode == 0,
        "errors": response.get("errors") if isinstance(response.get("errors"), list) else ["bridge_response_invalid"],
        "data": response.get("data"),
        "auth": response.get("auth") if isinstance(response.get("auth"), dict) else None,
    }


def graphql_request(query: str, variables: dict | None = None, *, timeout: int = 20) -> dict:
    config = load_config()
    if not config["configured"]:
        return {"ok": False, "errors": config["errors"], "data": None}
    if config["transport"] == "persisted_session_bridge":
        return _bridge_request(config, query, variables, timeout)
    url = f"https://{config['domain']}/admin/api/{config['api_version']}/graphql.json"
    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Shopify-Access-Token": config["token"]},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"ok": False, "errors": [f"http:{exc.code}"], "data": None}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"ok": False, "errors": [f"transport:{type(exc).__name__}"], "data": None}
    if payload.get("errors"):
        return {"ok": False, "errors": payload["errors"], "data": payload.get("data")}
    return {"ok": True, "errors": [], "data": payload.get("data")}


def probe_capabilities(*, live: bool = False) -> dict:
    config = load_config()
    result = {
        "configured": config["configured"],
        "api_version": config["api_version"],
        "token_mode": config["token_mode"],
        "transport": config["transport"],
        "auth_source": None,
        "persisted_offline_session_verified": False,
        "access_token_unexpired": False,
        "refresh_token_present": False,
        "refreshed": False,
        "fulfilment_read_adapter_verified": False,
        "fulfilment_create_adapter_verified": False,
        "inventory_read_adapter_verified": False,
        "scopes": [],
        "errors": list(config["errors"]),
    }
    if not live or not config["configured"]:
        return result
    response = graphql_request(CAPABILITY_QUERY)
    if not response["ok"]:
        result["errors"].append("capability_query_failed")
        return result
    auth = response.get("auth") or {}
    if config["transport"] == "persisted_session_bridge":
        result["auth_source"] = auth.get("source")
        result["token_mode"] = auth.get("token_mode") or "unknown"
        result["persisted_offline_session_verified"] = auth.get("persisted_offline_session_verified") is True
        result["access_token_unexpired"] = auth.get("access_token_unexpired") is True
        result["refresh_token_present"] = auth.get("refresh_token_present") is True
        result["refreshed"] = auth.get("refreshed") is True
    installation = (response.get("data") or {}).get("currentAppInstallation") or {}
    scopes = {x.get("handle") for x in installation.get("accessScopes", []) if isinstance(x, dict)}
    result["scopes"] = sorted(x for x in scopes if isinstance(x, str))
    result["fulfilment_read_adapter_verified"] = bool(scopes & FULFILMENT_READ_SCOPES)
    result["inventory_read_adapter_verified"] = "read_inventory" in scopes or "write_inventory" in scopes
    can_write = bool(scopes & FULFILMENT_WRITE_SCOPES)
    offline_verified = (
        result["persisted_offline_session_verified"]
        and result["access_token_unexpired"]
        and result["token_mode"] == "offline"
        if config["transport"] == "persisted_session_bridge"
        else config["token_mode"] == "offline"
    )
    result["fulfilment_create_adapter_verified"] = can_write and offline_verified
    if can_write and not offline_verified:
        result["errors"].append("offline_token_not_verified")
    return result


def build_create_payload(write_plan: dict) -> dict:
    errors: list[str] = []
    if not isinstance(write_plan, dict):
        return {"status": "REVIEW_REQUIRED", "errors": ["write_plan"], "variables": None}
    if not _nonempty(write_plan.get("order_id")):
        errors.append("order_id")
    if not isinstance(write_plan.get("notify_customer"), bool):
        errors.append("notify_customer")
    if write_plan.get("tracking_info") is not None:
        errors.append("tracking_info:unsupported_without_verified_source")
    groups = write_plan.get("fulfilment_orders")
    gql_groups: list[dict] = []
    if not isinstance(groups, list) or not groups:
        errors.append("fulfilment_orders")
    else:
        for i, group in enumerate(groups):
            if not isinstance(group, dict) or not _nonempty(group.get("fulfilment_order_id")):
                errors.append(f"fulfilment_orders[{i}].fulfilment_order_id")
                continue
            lines = group.get("line_items")
            gql_lines: list[dict] = []
            if not isinstance(lines, list) or not lines:
                errors.append(f"fulfilment_orders[{i}].line_items")
                continue
            for j, line in enumerate(lines):
                line_id = line.get("fulfilment_order_line_item_id") if isinstance(line, dict) else None
                qty = line.get("quantity") if isinstance(line, dict) else None
                if not _nonempty(line_id):
                    errors.append(f"fulfilment_orders[{i}].line_items[{j}].id")
                    continue
                if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
                    errors.append(f"fulfilment_orders[{i}].line_items[{j}].quantity")
                    continue
                gql_lines.append({"id": line_id.strip(), "quantity": qty})
            gql_groups.append({
                "fulfillmentOrderId": group["fulfilment_order_id"].strip(),
                "fulfillmentOrderLineItems": gql_lines,
            })
    if errors:
        return {"status": "REVIEW_REQUIRED", "errors": sorted(set(errors)), "variables": None}
    return {
        "status": "READY",
        "errors": [],
        "variables": {
            "fulfillment": {
                "lineItemsByFulfillmentOrder": gql_groups,
                "notifyCustomer": write_plan["notify_customer"],
            }
        },
    }


def create_fulfilment(write_plan: dict, *, execute: bool = False) -> dict:
    payload = build_create_payload(write_plan)
    if payload["status"] != "READY":
        return {"status": "REVIEW_REQUIRED", "fulfilment_id": None, "errors": payload["errors"]}
    if not execute or os.getenv("NTA_SHOPIFY_FULFILMENT_WRITE_ENABLED") != "true":
        return {"status": "BLOCKED", "fulfilment_id": None, "errors": ["explicit_write_enable_required"]}
    capability = probe_capabilities(live=True)
    if not capability["fulfilment_create_adapter_verified"]:
        return {"status": "BLOCKED", "fulfilment_id": None, "errors": capability["errors"] or ["fulfilment_create_adapter_unverified"]}
    response = graphql_request(FULFILMENT_CREATE_MUTATION, payload["variables"])
    if not response["ok"]:
        return {"status": "FAILED", "fulfilment_id": None, "errors": response["errors"]}
    result = ((response.get("data") or {}).get("fulfillmentCreate") or {})
    user_errors = result.get("userErrors") or []
    if user_errors:
        return {"status": "FAILED", "fulfilment_id": None, "errors": user_errors}
    fulfilment = result.get("fulfillment") or {}
    fulfilment_id = fulfilment.get("id")
    if not _nonempty(fulfilment_id):
        return {"status": "FAILED", "fulfilment_id": None, "errors": ["missing_created_fulfilment_id"]}
    return {"status": "SUCCESS", "fulfilment_id": fulfilment_id, "shopify_status": fulfilment.get("status"), "errors": []}


def read_fulfilment_order(fulfilment_order_id: str) -> dict:
    if not _nonempty(fulfilment_order_id):
        return {"status": "REVIEW_REQUIRED", "snapshot": None, "errors": ["fulfilment_order_id"]}
    capability = probe_capabilities(live=True)
    if not capability["fulfilment_read_adapter_verified"]:
        return {"status": "BLOCKED", "snapshot": None, "errors": capability["errors"] or ["fulfilment_read_adapter_unverified"]}
    response = graphql_request(FULFILMENT_ORDER_READ_QUERY, {"id": fulfilment_order_id.strip()})
    if not response["ok"]:
        return {"status": "FAILED", "snapshot": None, "errors": response["errors"]}
    raw = (response.get("data") or {}).get("fulfillmentOrder")
    if not isinstance(raw, dict):
        return {"status": "FAILED", "snapshot": None, "errors": ["fulfilment_order_not_found"]}
    lines = []
    for node in ((raw.get("lineItems") or {}).get("nodes") or []):
        if isinstance(node, dict):
            lines.append({
                "fulfilment_order_line_item_id": node.get("id"),
                "total_quantity": node.get("totalQuantity"),
                "remaining_quantity": node.get("remainingQuantity"),
                "inventory_item_id": node.get("inventoryItemId"),
            })
    return {
        "status": "SUCCESS",
        "snapshot": {
            "source": "FRESH_SHOPIFY_READ",
            "order_id": ((raw.get("order") or {}).get("id")),
            "fulfilment_order_id": raw.get("id"),
            "shopify_status": raw.get("status"),
            "line_items": lines,
        },
        "errors": [],
    }


def read_inventory_level(inventory_level_id: str) -> dict:
    if not _nonempty(inventory_level_id):
        return {"status": "REVIEW_REQUIRED", "snapshot": None, "errors": ["inventory_level_id"]}
    capability = probe_capabilities(live=True)
    if not capability["inventory_read_adapter_verified"]:
        return {"status": "BLOCKED", "snapshot": None, "errors": capability["errors"] or ["inventory_read_adapter_unverified"]}
    response = graphql_request(INVENTORY_LEVEL_READ_QUERY, {"id": inventory_level_id.strip()})
    if not response["ok"]:
        return {"status": "FAILED", "snapshot": None, "errors": response["errors"]}
    raw = (response.get("data") or {}).get("inventoryLevel")
    if not isinstance(raw, dict):
        return {"status": "FAILED", "snapshot": None, "errors": ["inventory_level_not_found"]}
    quantities = {q.get("name"): q.get("quantity") for q in raw.get("quantities", []) if isinstance(q, dict)}
    return {
        "status": "SUCCESS",
        "snapshot": {
            "source": "FRESH_SHOPIFY_READ",
            "inventory_level_id": raw.get("id"),
            "inventory_item_id": ((raw.get("item") or {}).get("id")),
            "sku": ((raw.get("item") or {}).get("sku")),
            "location_id": ((raw.get("location") or {}).get("id")),
            "location_name": ((raw.get("location") or {}).get("name")),
            "available": quantities.get("available"),
            "on_hand": quantities.get("on_hand"),
            "committed": quantities.get("committed"),
        },
        "errors": [],
    }
