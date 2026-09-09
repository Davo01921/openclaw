from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Any

DEFAULT_API_VERSION = "2026-07"
VALID_INVENTORY_BEHAVIOURS = {
    "BYPASS",
    "DECREMENT_IGNORING_POLICY",
    "DECREMENT_OBEYING_POLICY",
}
VALID_FINANCIAL_STATUSES = {
    "AUTHORIZED",
    "EXPIRED",
    "PAID",
    "PARTIALLY_PAID",
    "PARTIALLY_REFUNDED",
    "PENDING",
    "REFUNDED",
    "VOIDED",
}
VALID_DISCOUNT_TYPES = {"ITEM_PERCENTAGE"}

CAPABILITY_QUERY = """
query NtaOrderAdapterCapability {
  currentAppInstallation {
    accessScopes { handle }
  }
}
"""

ORDER_READ_QUERY = """
query NtaOrderRead($id: ID!) {
  order(id: $id) {
    id
    customer { id }
    lineItems(first: 250) {
      nodes { quantity variant { id } }
    }
    discountCodes
    currentTotalPriceSet { shopMoney { amount currencyCode } }
    totalOutstandingSet { shopMoney { amount currencyCode } }
    displayFinancialStatus
    tags
    note
  }
}
"""

ORDER_CREATE_MUTATION = """
mutation NtaOrderCreate($order: OrderCreateOrderInput!, $options: OrderCreateOptionsInput) {
  orderCreate(order: $order, options: $options) {
    userErrors { field message }
    order { id }
  }
}
"""


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _money_string(value: Any) -> str | None:
    if not _nonempty(value):
        return None
    try:
        return f"{Decimal(value):.2f}"
    except (InvalidOperation, ValueError):
        return None


def _percentage_number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if result <= 0 or result > 100:
        return None
    if result == result.to_integral_value():
        return int(result)
    return float(result)


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if _nonempty(value):
            return value.strip()
    return None


def load_config() -> dict:
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
        "domain": domain,
        "token": token,
        "api_version": api_version,
        "token_mode": token_mode,
    }


def graphql_request(query: str, variables: dict | None = None, *, timeout: int = 20) -> dict:
    config = load_config()
    if not config["configured"]:
        return {"ok": False, "errors": config["errors"], "data": None}

    url = f"https://{config['domain']}/admin/api/{config['api_version']}/graphql.json"
    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": config["token"],
        },
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
        "read_orders": False,
        "write_orders": False,
        "order_read_adapter_verified": False,
        "order_create_adapter_verified": False,
        "errors": list(config["errors"]),
    }
    if not live or not config["configured"]:
        return result

    response = graphql_request(CAPABILITY_QUERY)
    if not response["ok"]:
        result["errors"].append("capability_query_failed")
        return result

    installation = (response.get("data") or {}).get("currentAppInstallation") or {}
    scopes = {x.get("handle") for x in installation.get("accessScopes", []) if isinstance(x, dict)}
    result["read_orders"] = "read_orders" in scopes or "write_orders" in scopes
    result["write_orders"] = "write_orders" in scopes
    result["order_read_adapter_verified"] = result["read_orders"]
    result["order_create_adapter_verified"] = result["write_orders"] and config["token_mode"] == "offline"
    if result["write_orders"] and config["token_mode"] != "offline":
        result["errors"].append("offline_token_not_verified")
    return result


def build_create_payload(write_plan: dict) -> dict:
    errors: list[str] = []
    if not isinstance(write_plan, dict):
        return {"status": "REVIEW_REQUIRED", "errors": ["write_plan"], "variables": None}
    if write_plan.get("intent") != "CREATE_ORDER":
        errors.append("intent")

    order = write_plan.get("order")
    if not isinstance(order, dict):
        errors.append("order")
        order = {}

    customer_id = order.get("customer_id")
    if not _nonempty(customer_id):
        errors.append("order.customer_id")

    lines = order.get("line_items")
    gql_lines: list[dict] = []
    if not isinstance(lines, list) or not lines:
        errors.append("order.line_items")
    else:
        for i, line in enumerate(lines):
            if not isinstance(line, dict) or not _nonempty(line.get("variant_id")):
                errors.append(f"order.line_items[{i}].variant_id")
                continue
            qty = line.get("quantity")
            if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
                errors.append(f"order.line_items[{i}].quantity")
                continue
            gql_lines.append({"variantId": line["variant_id"].strip(), "quantity": qty})

    discount = order.get("discount") or {}
    gql_discount = None
    if not isinstance(discount, dict):
        errors.append("order.discount")
    elif any(discount.get(key) is not None for key in ("code", "type", "percentage")):
        discount_code = discount.get("code")
        discount_type = discount.get("type")
        percentage = _percentage_number(discount.get("percentage"))
        if not _nonempty(discount_code):
            errors.append("order.discount.code")
        if discount_type not in VALID_DISCOUNT_TYPES:
            errors.append("order.discount.type")
        if percentage is None:
            errors.append("order.discount.percentage")
        if _nonempty(discount_code) and discount_type == "ITEM_PERCENTAGE" and percentage is not None:
            gql_discount = {
                "itemPercentageDiscountCode": {
                    "percentage": percentage,
                    "code": discount_code.strip(),
                }
            }

    financial_target = order.get("financial_target")
    financial_status = None
    if financial_target is not None:
        if isinstance(financial_target, str) and financial_target in VALID_FINANCIAL_STATUSES:
            financial_status = financial_target
        else:
            errors.append("order.financial_target:unsupported_for_api")

    create_options = order.get("create_options")
    if not isinstance(create_options, dict):
        errors.append("order.create_options")
        create_options = {}
    inventory_behaviour = create_options.get("inventory_behaviour")
    if inventory_behaviour not in VALID_INVENTORY_BEHAVIOURS:
        errors.append("order.create_options.inventory_behaviour")

    send_receipt = create_options.get("send_receipt", False)
    send_fulfillment_receipt = create_options.get("send_fulfillment_receipt", False)
    if not isinstance(send_receipt, bool):
        errors.append("order.create_options.send_receipt")
    if not isinstance(send_fulfillment_receipt, bool):
        errors.append("order.create_options.send_fulfillment_receipt")

    if errors:
        return {"status": "REVIEW_REQUIRED", "errors": sorted(set(errors)), "variables": None}

    gql_order: dict[str, Any] = {
        "customer": {"toAssociate": {"id": customer_id.strip()}},
        "lineItems": gql_lines,
        "tags": order.get("tags", []),
        "note": order.get("note"),
    }
    if gql_discount is not None:
        gql_order["discountCode"] = gql_discount
    if financial_status:
        gql_order["financialStatus"] = financial_status

    variables = {
        "order": gql_order,
        "options": {
            "inventoryBehaviour": inventory_behaviour,
            "sendReceipt": send_receipt,
            "sendFulfillmentReceipt": send_fulfillment_receipt,
        },
    }
    return {"status": "READY", "errors": [], "variables": variables}


def create_order(write_plan: dict, *, execute: bool = False) -> dict:
    payload = build_create_payload(write_plan)
    if payload["status"] != "READY":
        return {"status": "REVIEW_REQUIRED", "order_id": None, "errors": payload["errors"]}
    if not execute or os.getenv("NTA_SHOPIFY_ORDER_WRITE_ENABLED") != "true":
        return {"status": "BLOCKED", "order_id": None, "errors": ["explicit_write_enable_required"]}

    capability = probe_capabilities(live=True)
    if not capability["order_create_adapter_verified"]:
        return {"status": "BLOCKED", "order_id": None, "errors": capability["errors"] or ["order_create_adapter_unverified"]}

    response = graphql_request(ORDER_CREATE_MUTATION, payload["variables"])
    if not response["ok"]:
        return {"status": "FAILED", "order_id": None, "errors": response["errors"]}

    result = ((response.get("data") or {}).get("orderCreate") or {})
    user_errors = result.get("userErrors") or []
    if user_errors:
        return {"status": "FAILED", "order_id": None, "errors": user_errors}
    order_id = (result.get("order") or {}).get("id")
    if not _nonempty(order_id):
        return {"status": "FAILED", "order_id": None, "errors": ["missing_created_order_id"]}
    return {"status": "SUCCESS", "order_id": order_id, "errors": []}


def read_order(order_id: str) -> dict:
    if not _nonempty(order_id):
        return {"status": "REVIEW_REQUIRED", "order": None, "errors": ["order_id"]}

    capability = probe_capabilities(live=True)
    if not capability["order_read_adapter_verified"]:
        return {"status": "BLOCKED", "order": None, "errors": capability["errors"] or ["order_read_adapter_unverified"]}

    response = graphql_request(ORDER_READ_QUERY, {"id": order_id.strip()})
    if not response["ok"]:
        return {"status": "FAILED", "order": None, "errors": response["errors"]}

    raw = (response.get("data") or {}).get("order")
    if not isinstance(raw, dict):
        return {"status": "FAILED", "order": None, "errors": ["order_not_found"]}

    lines = []
    for node in ((raw.get("lineItems") or {}).get("nodes") or []):
        variant_id = ((node.get("variant") or {}).get("id")) if isinstance(node, dict) else None
        if _nonempty(variant_id):
            lines.append({"variant_id": variant_id, "quantity": node.get("quantity")})

    current_total = ((raw.get("currentTotalPriceSet") or {}).get("shopMoney") or {})
    outstanding = ((raw.get("totalOutstandingSet") or {}).get("shopMoney") or {})
    discount_codes = raw.get("discountCodes") or []
    snapshot = {
        "order_id": raw.get("id"),
        "customer_id": ((raw.get("customer") or {}).get("id")),
        "line_items": lines,
        "discount_code": discount_codes[0] if discount_codes else None,
        "financial_status": raw.get("displayFinancialStatus"),
        "tags": raw.get("tags") or [],
        "note": raw.get("note"),
        "total_currency": current_total.get("currencyCode"),
        "outstanding_currency": outstanding.get("currencyCode"),
        "total_aud": _money_string(current_total.get("amount")) if current_total.get("currencyCode") == "AUD" else None,
        "outstanding_aud": _money_string(outstanding.get("amount")) if outstanding.get("currencyCode") == "AUD" else None,
    }
    return {"status": "SUCCESS", "order": snapshot, "errors": []}
