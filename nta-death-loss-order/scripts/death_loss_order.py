#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

API_VERSION = "2026-07"
DEFAULT_ENV_FILE = None
DEFAULT_SESSION_BRIDGE = None
CUSTOMER_NAME = "NTA Losses"
DISCOUNT_CODE = "Ntalosses"

SAFE_BRIDGE_CODES = {
    'bridge_internal_error', 'bridge_request_failed', 'bridge_response_invalid',
    'bridge_timeout', 'bridge_launch_failed', 'persisted_offline_session_not_verified',
    'graphql_access_denied', 'graphql_request_failed', 'shop_domain_invalid',
    'bridge_input_invalid', 'bridge_operation_invalid', 'explicit_write_enable_required',
    'explicit_fulfilment_write_enable_required', 'offline_session_not_found',
    'offline_session_shop_invalid', 'offline_session_shop_mismatch',
    'offline_session_id_mismatch', 'offline_access_token_missing', 'offline_session_ambiguous',
    'offline_refresh_configuration_missing', 'offline_refresh_failed',
    'offline_refresh_in_progress', 'offline_refresh_lock_failed',
    'offline_refresh_reauthorization_required', 'offline_refresh_response_invalid',
    'offline_refresh_retryable',
}
TRANSIENT_BRIDGE_CODES = {'bridge_internal_error', 'bridge_timeout',
                         'offline_refresh_in_progress', 'offline_refresh_retryable',
                         'http:429', 'http:500', 'http:502', 'http:503', 'http:504'}
TRANSIENT_TRANSPORT_CODES = {'UND_ERR_CONNECT_TIMEOUT', 'UND_ERR_HEADERS_TIMEOUT',
                            'UND_ERR_SOCKET', 'ECONNRESET', 'ETIMEDOUT', 'EAI_AGAIN',
                            'ENOTFOUND', 'ECONNREFUSED', 'ABORT_ERR', '23', 'unknown'}


class BridgeError(RuntimeError):
    """Bounded machine-readable diagnostics; never raw bridge output."""
    def __init__(self, operation, code, attempts, error_type=None, transport_code=None):
        super().__init__(code)
        self.details = {'operation': operation, 'error_code': code, 'bridge_attempts': attempts}
        if error_type:
            self.details['bridge_error_type'] = error_type
        if transport_code:
            self.details['transport_code'] = transport_code

    @property
    def retryable(self):
        code = self.details['error_code']
        transport = self.details.get('transport_code')
        return code in TRANSIENT_BRIDGE_CODES and (
            code != 'bridge_internal_error' or transport in TRANSIENT_TRANSPORT_CODES or transport is None)


def bridge_failure_details(error):
    if isinstance(error, BridgeError):
        return dict(error.details)
    return {'error_code': 'internal_helper_error'}


def bridge_response_error(response, operation, attempts):
    errors = response.get('errors') or []
    raw = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], str) else ''
    if re.fullmatch(r'http:[45]\d{2}', raw):
        return BridgeError(operation, raw, attempts)
    parts = raw.split(':')
    code = parts[0] if parts[0] in SAFE_BRIDGE_CODES else 'bridge_request_failed'
    classes = {'Error', 'TypeError', 'TimeoutError', 'AbortError',
               'PrismaClientKnownRequestError', 'PrismaClientInitializationError'}
    kind = parts[1] if len(parts) == 3 and parts[1] in classes else None
    transport = parts[2] if len(parts) == 3 and (
        parts[2] in TRANSIENT_TRANSPORT_CODES or re.fullmatch(r'P\d{4}', parts[2])) else None
    return BridgeError(operation, code, attempts, kind, transport)

def output(payload, code=0):
    print(json.dumps(payload, indent=2))
    raise SystemExit(code)

def blocked(message, **details):
    output({"status": "BLOCKED", "message": message, **details}, 2)

def load_env(path):
    if not path:
        blocked("Shopify configuration path is required.")
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
    for primary, alias in [('SHOPIFY_CLIENT_ID', 'SHOPIFY_API_KEY'), ('SHOPIFY_CLIENT_SECRET', 'SHOPIFY_API_SECRET')]:
        values[primary] = values.get(primary) or values.get(alias)
    for key in ("SHOPIFY_STORE", "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET"):
        if not values.get(key):
            blocked("Missing required Shopify configuration.", field=key)
    values["SHOPIFY_STORE"] = re.sub(r"^https?://", "", values["SHOPIFY_STORE"]).rstrip("/")
    return values

class Shopify:
    def __init__(self, env):
        self.env = env
        bridge = os.getenv("NTA_SHOPIFY_SESSION_BRIDGE_PATH") or DEFAULT_SESSION_BRIDGE
        if not bridge:
            blocked("Persisted Shopify session bridge path is required.")
        self.bridge = Path(bridge)
        self.write_authorized = False
        self.read_timeout = 35
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
            READ_ORDER_QUERY.strip(): "read_order",
            CAPABILITY_QUERY.strip(): "capability",
        }
        operation = operations.get(query.strip())
        if not operation:
            raise RuntimeError("bridge_operation_not_allowlisted")
        child_env = os.environ.copy()
        # Ambient generic flags cannot authorize this helper's mutations.
        child_env.pop('NTA_SHOPIFY_ORDER_WRITE_ENABLED', None)
        child_env.pop('NTA_SHOPIFY_FULFILMENT_WRITE_ENABLED', None)
        if operation in {'create_order', 'create_fulfillment'}:
            if not self.write_authorized:
                raise RuntimeError('explicit_death_batch_authorization_required')
            child_env['NTA_SHOPIFY_ORDER_WRITE_ENABLED'] = 'true'
            child_env['NTA_SHOPIFY_FULFILMENT_WRITE_ENABLED'] = 'true'
        child_env.update({
            "NTA_AUTH_BRIDGE_SAFE_DIAGNOSTICS": "true",
            "SHOPIFY_STORE": self.env["SHOPIFY_STORE"],
            "SHOPIFY_CLIENT_ID": self.env["SHOPIFY_CLIENT_ID"],
            "SHOPIFY_CLIENT_SECRET": self.env["SHOPIFY_CLIENT_SECRET"],
            "SHOPIFY_API_KEY": self.env["SHOPIFY_CLIENT_ID"],
            "SHOPIFY_API_SECRET": self.env["SHOPIFY_CLIENT_SECRET"],
        })
        mutation = operation in {'create_order', 'create_fulfillment'}
        deadline = time.monotonic() + self.read_timeout
        last_error = None
        # Only reads retry, within the caller's existing deadline (including backoff).
        # A mutation's uncertain result always returns to the durable recovery path.
        for attempt in range(1, 2 if mutation else 4):
            remaining = deadline - time.monotonic()
            if not mutation and remaining <= 0:
                raise last_error or BridgeError(operation, 'bridge_timeout', attempt - 1)
            try:
                return self._bridge_request(operation, variables, child_env,
                                            35 if mutation else remaining, attempt)
            except BridgeError as error:
                last_error = error
                delay = attempt  # 1 then 2 seconds; no unbounded/full-job retries.
                if mutation or attempt == 3 or not error.retryable or deadline - time.monotonic() <= delay:
                    raise
                time.sleep(delay)

    def _bridge_request(self, operation, variables, child_env, timeout, attempt):
        try:
            result = subprocess.run(
                [self.node, str(self.bridge)],
                input=json.dumps({"operation": operation, "variables": variables or {}}),
                text=True,
                capture_output=True,
                cwd=str(self.bridge.parent.parent),
                env=child_env,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise BridgeError(operation, 'bridge_timeout', attempt) from error
        except OSError as error:
            raise BridgeError(operation, 'bridge_launch_failed', attempt) from error
        try:
            response = json.loads(result.stdout.strip())
        except json.JSONDecodeError as error:
            raise BridgeError(operation, 'bridge_response_invalid', attempt) from error
        if not isinstance(response, dict):
            raise BridgeError(operation, 'bridge_response_invalid', attempt)
        auth = response.get("auth") or {}
        if not response.get("ok") or result.returncode != 0:
            raise bridge_response_error(response, operation, attempt)
        if not isinstance(auth, dict) or not isinstance(response.get('data'), dict):
            raise BridgeError(operation, 'bridge_response_invalid', attempt)
        if (
            auth.get("source") != "persisted_offline_session"
            or auth.get("token_mode") != "offline"
            or auth.get("persisted_offline_session_verified") is not True
            or auth.get("access_token_unexpired") is not True
        ):
            raise BridgeError(operation, 'persisted_offline_session_not_verified', attempt)
        return response["data"]

def norm(value):
    return re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize('NFKC', str(value or '')).casefold()).strip()

def fish_identity(product_title, variant_title='', tank=''):
    title = str(product_title or '')
    # Recognizable NTA tank prefixes are context, not species identity.
    title = re.sub(r'^(?:\d*BT\d+|TT\d+|GUP\d+(?:-\d+)?)\s*[-:]\s*', '', title, flags=re.I)
    if tank:
        title = re.sub(r'^' + re.escape(tank) + r'\s*[-:]\s*', '', title, flags=re.I)
    if norm(variant_title) not in {'', 'default title'}:
        title += ' ' + variant_title
    return norm(title)

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

def resolve(shop, fish, tank):
    if not fish.strip() or not tank.strip():
        blocked("Both fish and tank are required.")
    products = {}
    incomplete = False
    fish_products = set()
    tank_search_incomplete = False
    for search in dict.fromkeys((fish, tank)):
        data = shop.gql(PRODUCTS_QUERY, {"query": search})
        connection = data['products']
        if search == fish:
            incomplete |= connection.get('pageInfo', {}).get('hasNextPage') is not False
            fish_products.update(product['id'] for product in connection['nodes'])
        else:
            tank_search_incomplete |= connection.get('pageInfo', {}).get('hasNextPage') is not False
        for product in data["products"]["nodes"]:
            products.setdefault(product['id'], product)
    candidates = []
    for product in products.values():
        if product["status"] != "ACTIVE":
            continue
        if product['id'] in fish_products:
            incomplete |= product['variants'].get('pageInfo', {}).get('hasNextPage') is not False
        for variant in product["variants"]["nodes"]:
            identity = "{} {} {}".format(product["title"], variant["title"], variant.get("sku") or "")
            tank_exact = token_match(identity, tank)
            fish_match = fish_identity(product['title'], variant['title'], tank) == norm(fish)
            if not tank_exact and not fish_match:
                continue
            candidates.append({
                "product_id": product["id"],
                "product_title": product["title"],
                "variant_id": variant["id"],
                "variant_title": variant["title"],
                "sku": variant.get("sku"),
                "inventory_quantity": variant["inventoryQuantity"],
                "tank_exact": tank_exact,
                "fish_match": fish_match,
                "canonical_fish": fish_identity(product['title'], variant['title'], tank),
                "score": (100 if fish_match else 0) + (5 if tank_exact else 0),
                "reasons": (["EXACT_NORMALIZED_FISH"] if fish_match else ["FISH_MISMATCH"]) + (["TANK_CONTEXT"] if tank_exact else []),
                "inventory_levels": variant["inventoryItem"]["inventoryLevels"]["nodes"],
            })
    exact_fish = [candidate for candidate in candidates if candidate['fish_match'] and candidate['product_id'] in fish_products]
    selected = exact_fish[0] if len(exact_fish) == 1 and not incomplete else None
    reasons = ['TRUNCATED_OR_UNATTESTED_SEARCH'] if incomplete else ['AMBIGUOUS_FISH'] if len(exact_fish) > 1 else ['EXACT_NORMALIZED_FISH'] if selected else ['FISH_MISMATCH'] if candidates else ['NO_FISH_MATCH']
    if selected and not selected['tank_exact']:
        reasons.append('STALE_OR_UNVERIFIED_TANK_CONTEXT')
    if tank_search_incomplete:
        reasons.append('SUPPORTING_TANK_SEARCH_TRUNCATED')
    output({
        "status": "RESOLVED" if selected else "REVIEW_REQUIRED" if candidates else "UNMATCHED",
        "confidence": "HIGH" if selected else None,
        "resolved_variant": selected,
        "reasons": reasons,
        "candidates": sorted(candidates, key=lambda x: (-x['score'], x['variant_id'])),
    })

CAPABILITY_QUERY = 'query Capability { currentAppInstallation { accessScopes { handle } } }'
READ_ORDER_QUERY = 'query ReadLossOrder($id:ID!) { order(id:$id) { id } }'

def quantities(level):
    values = {}
    for item in level['quantities']:
        value = item.get('quantity')
        if item.get('name') in values or not isinstance(value, int) or isinstance(value, bool):
            blocked('Invalid inventory quantity response.')
        values[item['name']] = value
    return values

def variant(shop, variant_id):
    return shop.gql(VARIANT_QUERY, {"id": variant_id})["productVariant"]

def reference_tag(source_ref):
    return "DeathRef-" + hashlib.sha256(source_ref.encode()).hexdigest()[:20]

def existing_orders(shop, tag):
    query = "tag:{} status:any".format(tag)
    connection = shop.gql(ORDERS_QUERY, {"query": query})['orders']
    if connection.get('pageInfo', {}).get('hasNextPage') is not False:
        blocked('Existing-order search is incomplete; no mutation is safe.')
    return connection['nodes']


CREATE_MUTATION = """
mutation CreateLoss($order:OrderCreateOrderInput!,$options:OrderCreateOptionsInput){
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

def create(shop, args):
    blocked("Individual loss orders are disabled; use daily_batch.py.")


def parser():
    root = argparse.ArgumentParser()
    root.add_argument('--config')
    sub = root.add_subparsers(dest='command', required=True)
    resolver = sub.add_parser('resolve')
    resolver.add_argument('--fish', required=True)
    resolver.add_argument('--tank', required=True)
    return root


def main():
    from configuration import load_config
    args = parser().parse_args()
    try:
        config = load_config(args.config)
        global DEFAULT_SESSION_BRIDGE
        DEFAULT_SESSION_BRIDGE = config['session_bridge']
        shop = Shopify(load_env(config['env_file']))
        resolve(shop, args.fish, args.tank)
    except SystemExit:
        raise
    except Exception:
        blocked('Resolution failed; inspect configuration and bridge health.')


if __name__ == '__main__':
    main()
