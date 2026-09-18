#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

API_VERSION = "2026-07"
DEFAULT_ENV_FILE = "/Users/davidlo/.openclaw/workspace/nta-betta-picture-processor/.env"
DEFAULT_SESSION_BRIDGE = "/Users/davidlo/.openclaw/workspace/nta-fred-shopify-auth/nta-betta-picture-processor/scripts/shopify-session-bridge.mjs"
CUSTOMER_NAME = "NTA StoreUse"
DISCOUNT_CODE = "NTAStoreUse"

def output(payload, code=0):
    print(json.dumps(payload, indent=2))
    raise SystemExit(code)

def blocked(message, **details):
    output({"status": "BLOCKED", "message": message, **details}, 2)

def load_env(path):
    source = Path(path)
    if not source.exists():
        blocked("Shopify credential file is unavailable.")
    values = {}
    for raw in source.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key.strip()] = value
    for key in ("SHOPIFY_STORE", "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET"):
        if not values.get(key):
            blocked("Missing required Shopify configuration.", field=key)
    values["SHOPIFY_STORE"] = re.sub(r"^https?://", "", values["SHOPIFY_STORE"]).rstrip("/")
    return values

class Shopify:
    def __init__(self, env):
        self.env = env
        self.bridge = Path(os.getenv("NTA_SHOPIFY_SESSION_BRIDGE_PATH", DEFAULT_SESSION_BRIDGE))
        if not self.bridge.is_file():
            blocked("Persisted Shopify session bridge is unavailable.")
        self.node = self._node()

    @staticmethod
    def _node():
        candidates = [
            os.getenv("NTA_SHOPIFY_SESSION_BRIDGE_NODE"),
            shutil.which("node"),
            "/opt/homebrew/bin/node",
            "/usr/local/bin/node",
        ]
        for candidate in dict.fromkeys(item for item in candidates if item):
            try:
                result = subprocess.run(
                    [candidate, "--version"], capture_output=True, text=True, timeout=3, check=False,
                )
                major = int(result.stdout.strip().removeprefix("v").split(".", 1)[0])
            except (OSError, subprocess.TimeoutExpired, ValueError):
                continue
            if result.returncode == 0 and major >= 20:
                return candidate
        blocked("Persisted Shopify session bridge requires Node 20 or newer.")

    def gql(self, query, variables=None):
        operations = {
            PRODUCTS_QUERY.strip(): "products",
            VARIANT_QUERY.strip(): "variant",
            ORDERS_QUERY.strip(): "existing_orders",
            CUSTOMERS_QUERY.strip(): "customers",
            CREATE_MUTATION.strip(): "create_order",
            FULFILLMENT_STATE_QUERY.strip(): "fulfillment_state",
            CREATE_FULFILLMENT_MUTATION.strip(): "create_fulfillment",
        }
        operation = operations.get(query.strip())
        if not operation:
            raise RuntimeError("bridge_operation_not_allowlisted")
        child_env = os.environ.copy()
        child_env.update({
            "SHOPIFY_STORE": self.env["SHOPIFY_STORE"],
            "SHOPIFY_CLIENT_ID": self.env["SHOPIFY_CLIENT_ID"],
            "SHOPIFY_CLIENT_SECRET": self.env["SHOPIFY_CLIENT_SECRET"],
        })
        try:
            result = subprocess.run(
                [self.node, str(self.bridge)],
                input=json.dumps({"operation": operation, "variables": variables or {}}),
                text=True,
                capture_output=True,
                cwd=str(self.bridge.parent.parent),
                env=child_env,
                timeout=35,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("bridge_timeout") from error
        try:
            response = json.loads(result.stdout.strip())
        except json.JSONDecodeError as error:
            raise RuntimeError("bridge_response_invalid") from error
        auth = response.get("auth") or {}
        if not response.get("ok") or result.returncode != 0:
            errors = response.get("errors") or ["bridge_request_failed"]
            raise RuntimeError("; ".join(str(item) for item in errors))
        if (
            auth.get("source") != "persisted_offline_session"
            or auth.get("token_mode") != "offline"
            or auth.get("persisted_offline_session_verified") is not True
            or auth.get("access_token_unexpired") is not True
        ):
            raise RuntimeError("persisted_offline_session_not_verified")
        return response["data"]

def norm(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()

def token_match(text, token):
    return re.search(r"(^|[^A-Za-z0-9]){}([^A-Za-z0-9]|$)".format(re.escape(token)), text, re.I) is not None

PRODUCTS_QUERY = """
query Products($query:String!){
  products(first:10,query:$query){
    nodes{
      id title status
      variants(first:10){
        nodes{
          id title sku inventoryQuantity
          inventoryItem{
            id
            inventoryLevels(first:5){
              nodes{
                location{id name}
                quantities(names:["available","on_hand","committed"]){name quantity}
              }
            }
          }
        }
      }
    }
  }
}
"""

VARIANT_QUERY = """
query Variant($id:ID!){
  productVariant(id:$id){
    id title sku inventoryQuantity
    product{id title status}
    inventoryItem{
      id
      inventoryLevels(first:5){
        nodes{
          location{id name}
          quantities(names:["available","on_hand","committed"]){name quantity}
        }
      }
    }
  }
}
"""

ORDERS_QUERY = """
query Existing($query:String!){
  orders(first:10,query:$query,sortKey:CREATED_AT,reverse:true){
    nodes{
      id name displayFinancialStatus displayFulfillmentStatus
      currentTotalPriceSet{shopMoney{amount currencyCode}}
      customer{id displayName}
      tags note
      lineItems(first:20){nodes{quantity variant{id}}}
    }
  }
}
"""

def quantities(level):
    return {item["name"]: item["quantity"] for item in level["quantities"]}

def variant(shop, variant_id):
    return shop.gql(VARIANT_QUERY, {"id": variant_id})["productVariant"]

def reference_tag(source_ref):
    return "StoreUseRef-" + hashlib.sha256(source_ref.encode()).hexdigest()[:20]

def existing_orders(shop, tag):
    query = "tag:{} status:any".format(tag)
    return shop.gql(ORDERS_QUERY, {"query": query})["orders"]["nodes"]

def check_order(shop, order, before, location_id, quantity, variant_id, customer_id, tag, source_ref):
    current = variant(shop, variant_id)
    before_level = next(level for level in before["inventoryItem"]["inventoryLevels"]["nodes"] if level["location"]["id"] == location_id)
    after_level = next(level for level in current["inventoryItem"]["inventoryLevels"]["nodes"] if level["location"]["id"] == location_id)
    old = quantities(before_level)
    new = quantities(after_level)
    checks = {
        "zero_aud_total": float(order["currentTotalPriceSet"]["shopMoney"]["amount"]) == 0
            and order["currentTotalPriceSet"]["shopMoney"]["currencyCode"] == "AUD",
        "paid": order["displayFinancialStatus"] == "PAID",
        "fulfilled": order["displayFulfillmentStatus"] == "FULFILLED",
        "customer": order.get("customer", {}).get("id") == customer_id,
        "idempotency_tag": tag in order["tags"],
        "source_reference": source_ref in (order.get("note") or ""),
        "exact_line_item": any(
            line.get("variant", {}).get("id") == variant_id and line["quantity"] == quantity
            for line in order["lineItems"]["nodes"]
        ),
        "available_delta": new["available"] == old["available"] - quantity,
        "inventory_quantity_delta": current["inventoryQuantity"] == before["inventoryQuantity"] - quantity,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "before": {"inventory_quantity": before["inventoryQuantity"], "location": before_level["location"], **old},
        "after": {"inventory_quantity": current["inventoryQuantity"], "location": after_level["location"], **new},
    }

CREATE_MUTATION = """
mutation CreateStoreUse($order:OrderCreateOrderInput!,$options:OrderCreateOptionsInput){
  orderCreate(order:$order,options:$options){
    order{
      id name displayFinancialStatus displayFulfillmentStatus
      currentTotalPriceSet{shopMoney{amount currencyCode}}
      customer{id displayName}
      tags note
      lineItems(first:20){nodes{quantity variant{id}}}
    }
    userErrors{field message}
  }
}
"""

CUSTOMERS_QUERY = """
query Customers($query:String!){
  customers(first:20,query:$query){nodes{id displayName}}
}
"""

FULFILLMENT_STATE_QUERY = """
query FulfillmentState($id:ID!){
  order(id:$id){
    id displayFulfillmentStatus
    fulfillmentOrders(first:20){
      nodes{
        id status
        assignedLocation{location{id name}}
        lineItems(first:250){
          nodes{id remainingQuantity lineItem{id variant{id}}}
        }
      }
    }
    fulfillments{
      id status
      trackingInfo{company number url}
      fulfillmentLineItems(first:250){nodes{quantity lineItem{id variant{id}}}}
    }
  }
}
"""

CREATE_FULFILLMENT_MUTATION = """
mutation CreateFulfillment($fulfillment:FulfillmentInput!){
  fulfillmentCreate(fulfillment:$fulfillment){
    fulfillment{id status}
    userErrors{field message}
  }
}
"""

def parser():
    root = argparse.ArgumentParser(
        description="NTA StoreUse Shopify support module. "
                    "Live StoreUse orders must be created through daily_batch.py."
    )
    root.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    sub = root.add_subparsers(dest="command", required=True)

    variant_parser = sub.add_parser("variant")
    variant_parser.add_argument("--variant-id", required=True)

    return root


def main():
    args = parser().parse_args()
    try:
        shop = Shopify(load_env(args.env_file))
        if args.command == "variant":
            if not re.fullmatch(r"gid://shopify/ProductVariant/\d+", args.variant_id or ""):
                blocked("A valid exact variant ID is required.")
            current = variant(shop, args.variant_id)
            if not current:
                blocked("The exact variant was not found.")
            output({
                "status": "FOUND",
                "variant": current,
            })
    except SystemExit:
        raise
    except Exception as error:
        blocked("Shopify operation failed.", error=str(error))


if __name__ == "__main__":
    main()
