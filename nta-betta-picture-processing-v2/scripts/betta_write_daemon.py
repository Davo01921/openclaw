#!/usr/bin/env python3
"""Root-owned UNIX-socket daemon for the NTA Betta trusted write boundary.

Run by the ``com.nanotanksaustralia.betta-write`` LaunchDaemon as root with
Apple's ``/usr/bin/python3`` (stdlib only; Python 3.9-compatible). The daemon:

- loads ``betta_write_boundary.py`` from ``--code-root`` (the root-owned,
  hash-pinned snapshot; a changed repo copy never affects the daemon);
- reads policy and credentials ONLY from root-owned files under ``--state-dir``
  (environment variables never influence decisions, and credential values are
  never logged or returned by any operation);
- identifies callers with the kernel peer credential (SO_PEERCRED on Linux,
  LOCAL_PEERCRED/getpeereid on macOS) and rejects any uid outside the policy's
  ``allowed_uids`` (root is always allowed for admin/status);
- speaks one JSON request line -> one JSON response line;
- executes the validated mutations against the Shopify Admin GraphQL API over
  urllib with the credentials that only root can read. The Shopify layer is
  injectable so the test suite runs hermetically against a fake endpoint.

Hard rules enforced here (see ``docs/incident/
TRUSTED_WRITE_BOUNDARY_BRIEF_2026-10-16.md``): the disabled flag fails closed,
mutation outcomes are never blindly replayed (RECONCILIATION_REQUIRED), and
structured logs go to stderr only and never contain secret values.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import socket
import stat
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

# The boundary module is loaded from --code-root at startup; nothing below
# imports code that could live in an agent-writable location.
MAX_JSON_LINE_BYTES = 1024 * 1024
DEFAULT_SOCKET_MODE = 0o660
DEFAULT_API_VERSION = "2026-07"
CONNECTION_TIMEOUT_SECONDS = 30.0
TOKEN_EXPIRY_SKEW_SECONDS = 60

SHOPIFY_ENV_KEYS = frozenset({
    "SHOPIFY_STORE_DOMAIN", "SHOPIFY_STORE_URL", "SHOPIFY_CLIENT_ID",
    "SHOPIFY_CLIENT_SECRET", "SHOPIFY_ACCESS_TOKEN", "SHOPIFY_API_VERSION",
    "SHOPIFY_GRAPHQL_URL", "SHOPIFY_OAUTH_URL",
})


# ---------------------------------------------------------------------------
# Peer credential (injectable for tests)
# ---------------------------------------------------------------------------


def default_peer_uid(conn: socket.socket) -> int:
    """Return the kernel-authenticated uid of the peer of a UNIX socket.

    Linux uses ``SO_PEERCRED``; macOS has no ``SO_PEERCRED``, so the xucred
    blob is read with ``getsockopt(SOL_LOCAL, LOCAL_PEERCRED)`` with a
    ``getpeereid`` fallback. The daemon never trusts a caller-supplied uid.
    """
    so_peercred = getattr(socket, "SO_PEERCRED", None)
    if so_peercred is not None:
        try:
            blob = conn.getsockopt(
                socket.SOL_SOCKET, so_peercred, struct.calcsize("iII"))
            _pid, uid, _gid = struct.unpack("iII", blob)
            return int(uid)
        except OSError:
            pass
    if sys.platform == "darwin" or sys.platform.startswith("darwin"):
        # SOL_LOCAL=0, LOCAL_PEERCRED=1, struct xucred (76 bytes); cr_uid at 4.
        try:
            blob = conn.getsockopt(0, 1, 76)
            if len(blob) >= 8:
                return int(struct.unpack_from("I", blob, 4)[0])
        except OSError:
            pass
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            uid = ctypes.c_uint(0)
            gid = ctypes.c_uint(0)
            if libc.getpeereid(conn.fileno(), ctypes.byref(uid),
                               ctypes.byref(gid)) == 0:
                return int(uid.value)
        except Exception:  # noqa: BLE001 - fall through to refusal
            pass
    raise OSError("cannot determine peer uid")


# ---------------------------------------------------------------------------
# Shopify credentials (root-only file; values are never logged)
# ---------------------------------------------------------------------------


class CredentialsError(RuntimeError):
    pass


class ShopifyCredentials:
    """Parsed ``shopify.env`` values. ``__repr__`` never reveals secrets."""

    def __init__(self, values: Mapping[str, str]):
        self.store_domain = values.get("SHOPIFY_STORE_DOMAIN", "")
        self.store_url = values.get("SHOPIFY_STORE_URL", "")
        self.client_id = values.get("SHOPIFY_CLIENT_ID", "")
        self.client_secret = values.get("SHOPIFY_CLIENT_SECRET", "")
        self.access_token = values.get("SHOPIFY_ACCESS_TOKEN", "")
        self.api_version = values.get("SHOPIFY_API_VERSION", "") or DEFAULT_API_VERSION
        self.graphql_url = values.get("SHOPIFY_GRAPHQL_URL", "")
        self.oauth_url = values.get("SHOPIFY_OAUTH_URL", "")

    def __repr__(self) -> str:  # never repr secret material
        return (
            "ShopifyCredentials(store_configured=%s, token_configured=%s, "
            "client_configured=%s)" % (
                bool(self.store_domain or self.store_url),
                bool(self.access_token),
                bool(self.client_id and self.client_secret),
            )
        )

    @property
    def base_url(self) -> str:
        if self.store_url:
            return self.store_url.rstrip("/")
        return f"https://{self.store_domain}"

    def resolved_graphql_url(self) -> str:
        return self.graphql_url or (
            f"{self.base_url}/admin/api/{self.api_version}/graphql.json")

    def resolved_oauth_url(self) -> str:
        return self.oauth_url or f"{self.base_url}/admin/oauth/access_token"

    def validate(self) -> None:
        if not (self.store_domain or self.store_url):
            raise CredentialsError("Shopify store is not configured")
        if not self.access_token and not (self.client_id and self.client_secret):
            raise CredentialsError("Shopify credentials are not configured")


def parse_env_file(path: Path) -> dict:
    """Parse a small ``KEY=value`` file; unknown keys are ignored."""
    values: dict = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CredentialsError("shopify.env is missing") from exc
    except OSError as exc:
        raise CredentialsError("shopify.env is unreadable") from exc
    for number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            raise CredentialsError(f"shopify.env line {number} is malformed")
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if key not in SHOPIFY_ENV_KEYS:
            continue  # never trespass on other tools' variables
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def load_credentials(path: Path) -> ShopifyCredentials:
    credentials = ShopifyCredentials(parse_env_file(path))
    credentials.validate()
    return credentials


# ---------------------------------------------------------------------------
# Shopify HTTP transport (urllib; injectable opener for tests)
# ---------------------------------------------------------------------------


class HttpShopifyTransport:
    """Minimal Admin GraphQL client with client-credentials token exchange."""

    def __init__(
        self,
        credentials: ShopifyCredentials,
        *,
        opener: Optional[Callable] = None,
        timeout: float = 45.0,
        clock: Callable[[], float] = time.time,
    ):
        self.credentials = credentials
        self.opener = opener or urllib.request.urlopen
        self.timeout = timeout
        self.clock = clock
        self._token = credentials.access_token or ""
        self._token_expiry = float("inf") if credentials.access_token else 0.0

    # -- low-level ---------------------------------------------------------

    def _open(self, request: urllib.request.Request, timeout: float):
        opener = self.opener
        try:
            return opener(request, timeout=timeout)
        except TypeError:
            # Injectables may not accept the timeout kwarg.
            return opener(request)

    def _exchange_token(self) -> str:
        body = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self.credentials.client_id,
            "client_secret": self.credentials.client_secret,
        }).encode("ascii")
        request = urllib.request.Request(
            self.credentials.resolved_oauth_url(), data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with self._open(request, self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CredentialsError("Shopify token exchange failed") from exc
        except ValueError as exc:
            raise CredentialsError("Shopify token exchange returned invalid JSON") from exc
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise CredentialsError("Shopify token exchange returned no token")
        expires_in = payload.get("expires_in", 3600)
        try:
            lifetime = float(expires_in)
        except (TypeError, ValueError):
            lifetime = 3600.0
        self._token = token
        self._token_expiry = self.clock() + max(0.0, lifetime - TOKEN_EXPIRY_SKEW_SECONDS)
        return token

    def _ensure_token(self) -> str:
        if self._token and self.clock() < self._token_expiry:
            return self._token
        if self.credentials.access_token:
            return self._token or self.credentials.access_token
        return self._exchange_token()

    # -- public API --------------------------------------------------------

    def graphql(
        self,
        query: str,
        variables: Optional[Mapping[str, Any]] = None,
        *,
        mutation: bool = False,
        headers: Optional[Mapping[str, str]] = None,
        boundary: Any = None,
    ) -> dict:
        """POST one GraphQL document.

        Mutation uncertainty semantics: transport/timeout/5xx/429 mean the
        outcome is UNKNOWN (the caller must reconcile); deterministic 4xx or
        GraphQL validation errors mean the mutation was NOT applied.
        """
        payload: dict = {"query": query}
        if variables:
            payload["variables"] = dict(variables)
        request = urllib.request.Request(
            self.credentials.resolved_graphql_url(),
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Access-Token": self._ensure_token(),
                **dict(headers or {}),
            },
        )
        try:
            with self._open(request, self.timeout) as response:
                status_code = getattr(response, "status", 200)
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code >= 500 or exc.code == 429:
                raise _uncertain(boundary, "Shopify transport error") from exc
            raise _rejected(
                boundary, f"Shopify rejected the call (HTTP {exc.code})") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise _uncertain(boundary, "Shopify transport error") from exc
        if status_code >= 500 or status_code == 429:
            raise _uncertain(boundary, "Shopify transport error")
        try:
            parsed = json.loads(raw)
        except ValueError as exc:
            raise _uncertain(boundary, "Shopify returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise _uncertain(boundary, "Shopify returned an unexpected payload")
        errors = parsed.get("errors")
        if errors:
            text = json.dumps(errors)[:400]
            throttled = "THROTTLED" in text or "throttl" in text.lower()
            if throttled:
                raise _uncertain(boundary, "Shopify throttled the call")
            raise _rejected(boundary, f"Shopify GraphQL error: {_clean(text)}")
        data = parsed.get("data")
        if not isinstance(data, dict):
            if mutation:
                raise _uncertain(boundary, "Shopify returned no data")
            raise _read_error(boundary, "Shopify returned no data")
        return data

    def staged_upload(self, target: Mapping[str, Any], path, mime_type: str,
                      boundary: Any = None) -> None:
        """POST one staged upload without logging signed parameters or URLs."""
        target_url = target.get("url")
        if not isinstance(target_url, str) or (
                urllib.parse.urlparse(target_url).scheme != "https" and
                not target_url.startswith("http://127.0.0.1")):
            raise _rejected(boundary, "invalid Shopify staged-upload target")
        parameters = target.get("parameters")
        if not isinstance(parameters, list):
            raise _rejected(boundary, "missing Shopify staged-upload parameters")
        file_path = Path(path)
        boundary_name = "----nta-betta-boundary-%s" % uuid.uuid4().hex
        body = bytearray()
        for parameter in parameters:
            name = parameter.get("name")
            value = parameter.get("value")
            if not isinstance(name, str) or not isinstance(value, str):
                raise _rejected(boundary, "invalid staged-upload parameter")
            body.extend(f"--{boundary_name}\r\n".encode())
            body.extend(
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            body.extend(value.encode())
            body.extend(b"\r\n")
        body.extend(f"--{boundary_name}\r\n".encode())
        body.extend((
            f'Content-Disposition: form-data; name="file"; '
            f'filename="{file_path.name}"\r\n'
        ).encode())
        body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode())
        body.extend(file_path.read_bytes())
        body.extend(b"\r\n")
        body.extend(f"--{boundary_name}--\r\n".encode())
        request = urllib.request.Request(
            target_url, data=bytes(body), method="POST",
            headers={"Content-Type":
                     f"multipart/form-data; boundary={boundary_name}"},
        )
        try:
            with self._open(request, 120.0) as response:
                if not 200 <= getattr(response, "status", 200) < 300:
                    raise _rejected(boundary, "staged upload failed")
        except urllib.error.HTTPError as exc:
            if exc.code >= 500 or exc.code == 429:
                raise _uncertain(boundary, "staged upload outcome is uncertain") from exc
            raise _rejected(boundary, "staged upload was rejected") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise _uncertain(boundary, "staged upload outcome is uncertain") from exc


def _clean(text: str) -> str:
    return text.replace("\n", " ")[:400]


def _uncertain(boundary: Any, message: str) -> Exception:
    cls = getattr(boundary, "ShopifyUncertainError", RuntimeError)
    return cls(message)


def _rejected(boundary: Any, message: str) -> Exception:
    cls = getattr(boundary, "ShopifyRejectedError", RuntimeError)
    return cls(message)


def _read_error(boundary: Any, message: str) -> Exception:
    cls = getattr(boundary, "ShopifyReadError", RuntimeError)
    return cls(message)


# ---------------------------------------------------------------------------
# GraphQL documents (ported semantics; R2 confirms versions at install time)
# ---------------------------------------------------------------------------

READ_PRODUCT_QUERY = """
query BettaBoundaryProduct($id: ID!, $namespace: String!, $key: String!) {
  product(id: $id) {
    id
    title
    status
    descriptionHtml
    handle
    vendor
    productType
    metafield(namespace: $namespace, key: $key) { value type }
    media(first: 50) {
      pageInfo { hasNextPage }
      nodes { id alt status mediaContentType }
    }
    variants(first: 5) {
      pageInfo { hasNextPage }
      nodes {
        id
        price
        inventoryQuantity
        inventoryPolicy
        inventoryItem {
          id
          tracked
          unitCost { amount currencyCode }
          inventoryLevels(first: 10) {
            pageInfo { hasNextPage }
            nodes {
              location { id name }
              quantities(names: ["available", "on_hand", "committed"]) {
                name
                quantity
              }
            }
          }
        }
      }
    }
  }
}
""".strip()

UPDATE_DETAILS_MUTATION = """
mutation BettaBoundaryUpdateDetails($product: ProductUpdateInput!) {
  productUpdate(product: $product) {
    product { id }
    userErrors { field message }
  }
}
""".strip()

SET_ARRIVAL_DATE_MUTATION = """
mutation BettaBoundarySetArrivalDate($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    metafields { id }
    userErrors { field message }
  }
}
""".strip()

SET_INVENTORY_MUTATION = """
mutation BettaBoundarySetInventory($input: InventorySetQuantitiesInput!) {
  inventorySetQuantities(input: $input) {
    inventoryAdjustmentGroup { createdAt reason }
    userErrors { field message }
  }
}
""".strip()

STAGE_MEDIA_MUTATION = """
mutation BettaBoundaryStageMedia($input: [StagedUploadInput!]!) {
  stagedUploadsCreate(input: $input) {
    stagedTargets { url resourceUrl parameters { name value } }
    userErrors { field message }
  }
}
""".strip()

ADD_MEDIA_MUTATION = """
mutation BettaBoundaryAddMedia($product: ProductUpdateInput!) {
  productUpdate(product: $product) {
    product { id }
    userErrors { field message }
  }
}
""".strip()

REORDER_MEDIA_MUTATION = """
mutation BettaBoundaryReorderMedia($id: ID!, $moves: [MoveInput!]!) {
  productReorderMedia(id: $id, moves: $moves) {
    job { id }
    mediaUserErrors { field message }
  }
}
""".strip()

UPDATE_VARIANT_MUTATION = """
mutation BettaBoundaryUpdateVariant($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    productVariants { id price }
    userErrors { field message }
  }
}
""".strip()

UPDATE_COST_MUTATION = """
mutation BettaBoundaryUpdateCost($id: ID!, $input: InventoryItemInput!) {
  inventoryItemUpdate(id: $id, input: $input) {
    inventoryItem { id unitCost { amount currencyCode } }
    userErrors { field message }
  }
}
""".strip()


def user_errors(boundary: Any, node: Any, field: str) -> list:
    if not isinstance(node, dict):
        raise _uncertain(boundary, "Shopify returned no mutation receipt")
    errors = node.get(field)
    if not isinstance(errors, list) or not errors:
        return []
    return [str(error.get("message", "Shopify user error"))
            for error in errors if isinstance(error, dict)] or ["Shopify user error"]


# ---------------------------------------------------------------------------
# Shopify service: op executors
# ---------------------------------------------------------------------------


class HttpShopifyService:
    """Executors for the pinned operation set over the Admin GraphQL API."""

    def __init__(self, boundary: Any, transport: HttpShopifyTransport, *,
                 sleep: Callable[[float], None] = time.sleep,
                 metafield_namespace: str = "custom",
                 metafield_key: str = "arrival_date"):
        self.boundary = boundary
        self.transport = transport
        self.sleep = sleep
        self.metafield_namespace = metafield_namespace
        self.metafield_key = metafield_key

    # -- reads -------------------------------------------------------------

    def read_product(self, product_id: str, location_id: Optional[str] = None) -> dict:
        data = self.transport.graphql(
            READ_PRODUCT_QUERY,
            {"id": product_id, "namespace": self.metafield_namespace,
             "key": self.metafield_key},
            boundary=self.boundary,
        )
        return self._normalise_product(data.get("product"), location_id)

    def _normalise_product(self, product: Any, location_id: Optional[str]) -> dict:
        if not isinstance(product, dict):
            raise _read_error(self.boundary, "Shopify product was not found")
        variants_connection = product.get("variants") or {}
        variants = variants_connection.get("nodes") or []
        if variants_connection.get("pageInfo", {}).get("hasNextPage") is not False:
            raise _read_error(self.boundary, "Shopify variant read is truncated")
        if len(variants) != 1:
            raise _read_error(
                self.boundary, "individual Betta must have exactly one variant")
        variant = variants[0]
        inventory_item = variant.get("inventoryItem") or {}
        levels_connection = inventory_item.get("inventoryLevels") or {}
        levels = levels_connection.get("nodes") or []
        if levels_connection.get("pageInfo", {}).get("hasNextPage") is not False:
            raise _read_error(self.boundary, "Shopify inventory-level read is truncated")
        if location_id is not None:
            matched = [level for level in levels
                       if (level.get("location") or {}).get("id") == location_id]
            if len(matched) != 1:
                raise _read_error(
                    self.boundary, "exact inventory location is missing/ambiguous")
            level = matched[0]
        else:
            if len(levels) != 1:
                raise _read_error(
                    self.boundary, "inventory location is ambiguous; pass location_id")
            level = levels[0]
        quantities = {
            value.get("name"): value.get("quantity")
            for value in level.get("quantities") or [] if isinstance(value, dict)
        }
        media_connection = product.get("media") or {}
        if media_connection.get("pageInfo", {}).get("hasNextPage") is not False:
            raise _read_error(self.boundary, "Shopify media read is truncated")
        media = [{
            "id": node.get("id"),
            "alt": node.get("alt"),
            "status": node.get("status"),
        } for node in media_connection.get("nodes") or [] if isinstance(node, dict)]
        description = product.get("descriptionHtml")
        if not isinstance(description, str):
            raise _read_error(self.boundary, "Shopify descriptionHtml is missing")
        metafield = product.get("metafield") or {}
        cost = inventory_item.get("unitCost") or {}
        return {
            "source": "FRESH_SHOPIFY_READ",
            "product_id": product.get("id"),
            "variant_id": variant.get("id"),
            "inventory_item_id": inventory_item.get("id"),
            "location_id": (level.get("location") or {}).get("id"),
            "title": product.get("title"),
            "arrival_date": metafield.get("value"),
            "available": quantities.get("available"),
            "inventory_quantity": variant.get("inventoryQuantity"),
            "status": product.get("status"),
            "vendor": product.get("vendor"),
            "price": variant.get("price"),
            "cost": cost.get("amount"),
            "description_sha256": hashlib.sha256(description.encode()).hexdigest(),
            "inventory_policy": variant.get("inventoryPolicy"),
            "tracked": inventory_item.get("tracked"),
            "media": media,
        }

    # -- mutations ---------------------------------------------------------

    def apply_update_details(self, product_id: str, fields: Mapping[str, Any]) -> dict:
        if "title" in fields:
            data = self.transport.graphql(
                UPDATE_DETAILS_MUTATION,
                {"product": {"id": product_id, "title": fields["title"]}},
                mutation=True, boundary=self.boundary)
            errors = user_errors(self.boundary, data.get("productUpdate"), "userErrors")
            if errors:
                raise _rejected(self.boundary, "; ".join(errors))
        if "arrival_date" in fields:
            data = self.transport.graphql(
                SET_ARRIVAL_DATE_MUTATION,
                {"metafields": [{
                    "ownerId": product_id,
                    "namespace": self.metafield_namespace,
                    "key": self.metafield_key,
                    "type": "date",
                    "value": fields["arrival_date"],
                }]},
                mutation=True, boundary=self.boundary)
            errors = user_errors(self.boundary, data.get("metafieldsSet"), "userErrors")
            if errors:
                raise _rejected(self.boundary, "; ".join(errors))
        return {"updated": sorted(fields)}

    def apply_set_inventory(
        self,
        *,
        inventory_item_id: str,
        location_id: str,
        quantity: int,
        reason: str,
        change_from: int,
        reference_document_uri: str,
        idempotency_key: str,
    ) -> dict:
        data = self.transport.graphql(
            SET_INVENTORY_MUTATION,
            {"input": {
                "name": "available",
                "reason": reason,
                "referenceDocumentUri": reference_document_uri,
                "quantities": [{
                    "inventoryItemId": inventory_item_id,
                    "locationId": location_id,
                    "quantity": quantity,
                    "changeFromQuantity": change_from,
                }],
            }},
            mutation=True,
            headers={"Shopify-Idempotency-Key": idempotency_key},
            boundary=self.boundary,
        )
        errors = user_errors(
            self.boundary, data.get("inventorySetQuantities"), "userErrors")
        if errors:
            raise _rejected(self.boundary, "; ".join(errors))
        return {"quantity": quantity, "reason": reason}

    def apply_media_append(
        self,
        *,
        product_id: str,
        assets: list,
        batch_id: str,
        tank: str,
        poll_attempts: int = 30,
        poll_interval: float = 2.0,
    ) -> dict:
        # Assets arrive hero-first (pinned port semantics).
        inputs = [{
            "filename": Path(asset["path"]).name,
            "mimeType": self._mime_for(asset["path"]),
            "fileSize": str(Path(asset["path"]).stat().st_size),
            "resource": "PRODUCT_IMAGE",
            "httpMethod": "POST",
        } for asset in assets]
        data = self.transport.graphql(
            STAGE_MEDIA_MUTATION, {"input": inputs},
            mutation=True, boundary=self.boundary)
        node = data.get("stagedUploadsCreate")
        errors = user_errors(self.boundary, node, "userErrors")
        if errors:
            raise _rejected(self.boundary, "; ".join(errors))
        targets = (node or {}).get("stagedTargets")
        if not isinstance(targets, list) or len(targets) != len(assets):
            raise _rejected(self.boundary, "Shopify did not return staging targets")
        for target, asset in zip(targets, assets):
            self.transport.staged_upload(
                target, asset["path"], self._mime_for(asset["path"]),
                boundary=self.boundary)
        media_input = [{
            "mediaContentType": "IMAGE",
            "originalSource": target["resourceUrl"],
            "alt": asset["alt"],
        } for target, asset in zip(targets, assets)]
        data = self.transport.graphql(
            ADD_MEDIA_MUTATION,
            {"product": {"id": product_id, "media": media_input}},
            mutation=True, boundary=self.boundary)
        errors = user_errors(self.boundary, data.get("productUpdate"), "userErrors")
        if errors:
            raise _rejected(self.boundary, "; ".join(errors))

        tagged = self._poll_media(product_id, assets, poll_attempts, poll_interval)
        wanted = [asset["alt"] for asset in assets]
        current = [value.get("alt") for value in tagged["media"][:2]]
        if current != wanted:
            data = self.transport.graphql(
                REORDER_MEDIA_MUTATION,
                {"id": product_id, "moves": [
                    {"id": tagged["by_alt"][asset["alt"]]["id"],
                     "newPosition": str(index)}
                    for index, asset in enumerate(assets)
                ]},
                mutation=True, boundary=self.boundary)
            errors = user_errors(
                self.boundary, data.get("productReorderMedia"), "mediaUserErrors")
            if errors:
                raise _rejected(self.boundary, "; ".join(errors))
            tagged = self._poll_media(
                product_id, assets, poll_attempts, poll_interval, require_order=True)
        return {
            "media_ids": [tagged["by_alt"][asset["alt"]]["id"] for asset in assets],
            "media_alts": [asset["alt"] for asset in assets],
        }

    def _poll_media(self, product_id: str, assets: list, attempts: int,
                    interval: float, *, require_order: bool = False) -> dict:
        wanted = [asset["alt"] for asset in assets]
        last: dict = {"media": [], "by_alt": {}}
        for attempt in range(max(1, attempts)):
            readback = self.read_product(product_id)
            media = readback.get("media") or []
            by_alt = {}
            for value in media:
                alt = value.get("alt")
                if alt in wanted and alt not in by_alt:
                    by_alt[alt] = value
            last = {"media": media, "by_alt": by_alt}
            if any((last["by_alt"].get(alt) or {}).get("status") in ("FAILED", "CANCELED")
                   for alt in wanted):
                raise _rejected(self.boundary, "Shopify media processing failed")
            if all(alt in by_alt for alt in wanted):
                if not require_order:
                    return last
                if [value.get("alt") for value in media[:2]] == wanted:
                    return last
            if attempt + 1 < attempts:
                self.sleep(interval)
        raise _uncertain(self.boundary, "Shopify media is not ready after polling")

    def apply_merch_update(self, *, product_id: str, variant_id: str,
                           inventory_item_id: Optional[str],
                           fields: Mapping[str, Any]) -> dict:
        if "vendor" in fields:
            data = self.transport.graphql(
                UPDATE_DETAILS_MUTATION,
                {"product": {"id": product_id, "vendor": fields["vendor"]}},
                mutation=True, boundary=self.boundary)
            errors = user_errors(self.boundary, data.get("productUpdate"), "userErrors")
            if errors:
                raise _rejected(self.boundary, "; ".join(errors))
        if "price" in fields:
            data = self.transport.graphql(
                UPDATE_VARIANT_MUTATION,
                {"productId": product_id,
                 "variants": [{"id": variant_id, "price": fields["price"]}]},
                mutation=True, boundary=self.boundary)
            errors = user_errors(
                self.boundary, data.get("productVariantsBulkUpdate"), "userErrors")
            if errors:
                raise _rejected(self.boundary, "; ".join(errors))
        if "cost" in fields:
            if not inventory_item_id:
                raise _rejected(self.boundary, "cost update requires an inventory item")
            data = self.transport.graphql(
                UPDATE_COST_MUTATION,
                {"id": inventory_item_id, "input": {"cost": fields["cost"]}},
                mutation=True, boundary=self.boundary)
            errors = user_errors(
                self.boundary, data.get("inventoryItemUpdate"), "userErrors")
            if errors:
                raise _rejected(self.boundary, "; ".join(errors))
        return {"updated": sorted(fields)}

    def _mime_for(self, path: str) -> str:
        mime = self.boundary.detect_image_mime(Path(path))
        if mime is None:
            raise _rejected(self.boundary, "media asset is not png/jpeg")
        return mime


# ---------------------------------------------------------------------------
# The daemon
# ---------------------------------------------------------------------------


class WriteDaemon:
    def __init__(
        self,
        *,
        boundary: Any,
        socket_path: Path,
        state_dir: Path,
        code_root: Path,
        socket_group: Optional[str] = None,
        uid_provider: Callable[[socket.socket], int] = default_peer_uid,
        shopify_factory: Optional[Callable[[], Any]] = None,
        log_stream: Any = None,
    ):
        self.boundary = boundary
        self.socket_path = Path(socket_path)
        self.state_dir = Path(state_dir)
        self.code_root = Path(code_root)
        self.socket_group = socket_group
        self.uid_provider = uid_provider
        self.shopify_factory = shopify_factory or self._build_shopify
        self.log_stream = log_stream if log_stream is not None else sys.stderr
        self.paths = boundary.BoundaryPaths(self.state_dir)
        self.engine = boundary.BoundaryEngine(
            self.paths,
            corrections_path=self.code_root / "betta_corrections.py",
            version_sha256=compute_version_sha256(self.code_root),
            logger=self.log,
        )
        self._service = None
        self._service_mtime: Optional[float] = None
        self._stop = False

    # -- logging (stderr only; never secrets) ------------------------------

    def log(self, event: Any = None, **fields: Any) -> None:
        if isinstance(event, Mapping):
            record = {"at": _now_iso(), **dict(event), **fields}
        else:
            if event is not None:
                fields.setdefault("event", event)
            record = {"at": _now_iso(), **fields}
        try:
            self.log_stream.write(json.dumps(record, sort_keys=True) + "\n")
            self.log_stream.flush()
        except Exception:  # noqa: BLE001 - logging must never break serving
            pass

    # -- Shopify service (cached; rebuilt when shopify.env changes) --------

    def _build_shopify(self) -> Any:
        env_path = self.paths.shopify_env_path
        try:
            mtime = env_path.stat().st_mtime
        except OSError:
            self._service = None
            self._service_mtime = None
            return None
        if self._service is not None and self._service_mtime == mtime:
            return self._service
        try:
            credentials = load_credentials(env_path)
            transport = HttpShopifyTransport(credentials)
            self._service = HttpShopifyService(self.boundary, transport)
            self._service_mtime = mtime
            self.log(event="shopify_credentials_loaded",
                     store_configured=bool(credentials.store_domain or credentials.store_url))
            return self._service
        except (CredentialsError, OSError) as exc:
            self.log(event="shopify_credentials_unavailable",
                     error=type(exc).__name__)
            self._service = None
            self._service_mtime = None
            return None

    def shopify(self) -> Any:
        return self.shopify_factory()

    # -- request handling ---------------------------------------------------

    def handle_line(self, line: Any, peer_uid: Optional[int]) -> dict:
        request = None
        if isinstance(line, (bytes, bytearray)):
            try:
                line = bytes(line).decode("utf-8")
            except UnicodeDecodeError:
                line = None
        if isinstance(line, str) and line.strip():
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                request = None
            if request is not None:
                return self.engine.handle(
                    request, peer_uid=peer_uid, shopify=self.shopify())
        return {
            "schema": self.boundary.RESPONSE_SCHEMA,
            "ok": False,
            "outcome": self.boundary.OUTCOME_REFUSED,
            "receipt": None,
            "receipt_sha256": None,
            "receipt_signature": None,
            "error_code": self.boundary.ERR_BAD_REQUEST,
            "detail": "request line is not a JSON object",
            "readback": None,
        }

    def _read_line(self, conn: socket.socket) -> Optional[bytes]:
        chunks = bytearray()
        while True:
            try:
                chunk = conn.recv(65536)
            except socket.timeout:
                return None
            if not chunk:
                break
            chunks.extend(chunk)
            index = chunks.find(b"\n")
            if index != -1:
                return bytes(chunks[:index])
            if len(chunks) > MAX_JSON_LINE_BYTES:
                return None
        return bytes(chunks) if chunks else None

    def _session(self, conn: socket.socket) -> None:
        peer_uid: Optional[int] = None
        try:
            peer_uid = int(self.uid_provider(conn))
        except Exception:  # noqa: BLE001 - unknown peer is not allowed
            peer_uid = None
        line = self._read_line(conn)
        response = self.handle_line(line, peer_uid)
        try:
            conn.sendall(json.dumps(response).encode("utf-8") + b"\n")
        except OSError:
            pass
        self.log(event="request_served",
                 request_id=(response.get("receipt") or {}).get("request_id"),
                 outcome=response.get("outcome"),
                 error_code=response.get("error_code"),
                 peer_uid=peer_uid)

    # -- socket lifecycle ---------------------------------------------------

    def _bind(self) -> socket.socket:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            try:
                metadata = os.lstat(self.socket_path)
            except OSError:
                metadata = None
            if metadata is None or not stat.S_ISSOCK(metadata.st_mode):
                raise RuntimeError("socket path exists and is not a socket")
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.settimeout(1.0)
                probe.connect(str(self.socket_path))
            except OSError:
                os.unlink(self.socket_path)  # stale socket from a dead daemon
            else:
                probe.close()
                raise RuntimeError("another daemon is already listening")
            finally:
                probe.close()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        os.chmod(self.socket_path, DEFAULT_SOCKET_MODE)
        if self.socket_group:
            import grp
            try:
                gid = grp.getgrnam(self.socket_group).gr_gid
                os.chown(self.socket_path, -1, gid)
            except KeyError:
                self.log(event="socket_group_unknown", group=self.socket_group)
        server.listen(8)
        server.settimeout(1.0)
        return server

    def stop(self) -> None:
        self._stop = True

    def serve_forever(self) -> int:
        previous_umask = os.umask(0o117)
        server = None
        try:
            self.paths.ensure_dirs()
            server = self._bind()
            self.log(
                event="daemon_start", socket=str(self.socket_path),
                state_dir=str(self.state_dir), code_root=str(self.code_root),
                version_sha256=compute_version_sha256(self.code_root),
                disabled=self.engine.disabled(),
            )
            while not self._stop:
                try:
                    conn, _address = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                try:
                    conn.settimeout(CONNECTION_TIMEOUT_SECONDS)
                    self._session(conn)
                finally:
                    try:
                        conn.close()
                    except OSError:
                        pass
            return 0
        finally:
            if server is not None:
                try:
                    server.close()
                except OSError:
                    pass
            try:
                if self.socket_path.exists() and stat.S_ISSOCK(
                        os.lstat(self.socket_path).st_mode):
                    os.unlink(self.socket_path)
            except OSError:
                pass
            os.umask(previous_umask)
            self.log(event="daemon_stop")


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def compute_version_sha256(code_root: Path) -> Optional[str]:
    """Hash the daemon's code snapshot for receipts/status (no secrets)."""
    names = ("betta_write_boundary.py", "betta_write_daemon.py",
             "betta_corrections.py")
    files = {}
    for name in names:
        path = Path(code_root) / name
        if path.is_file():
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue
            files[name] = digest
    version_file = Path(code_root) / "version.json"
    version = None
    if version_file.is_file():
        try:
            parsed = json.loads(version_file.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                version = parsed.get("code_sha256") or None
        except (OSError, ValueError):
            version = None
    if not files:
        return version
    payload = {"files": files}
    if version:
        payload["version_code_sha256"] = version
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load_boundary_module(code_root: Path) -> Any:
    import importlib.util
    path = Path(code_root) / "betta_write_boundary.py"
    spec = importlib.util.spec_from_file_location(
        "_nta_betta_write_boundary_daemon", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"boundary module unavailable: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="NTA Betta trusted write-boundary daemon (root)")
    parser.add_argument("--socket", required=True, type=Path)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--code-root", required=True, type=Path)
    parser.add_argument(
        "--socket-group", default=None,
        help="optional group that may connect (production: davidlo)")
    return parser.parse_args(argv)


def main(argv: Optional[list] = None) -> int:
    args = parse_args(argv)
    boundary = load_boundary_module(args.code_root)
    daemon = WriteDaemon(
        boundary=boundary,
        socket_path=args.socket,
        state_dir=args.state_dir,
        code_root=args.code_root,
        socket_group=args.socket_group,
    )

    import signal

    def _handle_signal(_signum, _frame):
        daemon.stop()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    return daemon.serve_forever()


if __name__ == "__main__":
    raise SystemExit(main())
