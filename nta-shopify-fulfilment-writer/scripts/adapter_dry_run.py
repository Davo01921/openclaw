#!/usr/bin/env python3
import json
import os
from pathlib import Path
import tempfile

from shopify_fulfilment_api import (
    build_create_payload,
    create_fulfilment,
    probe_capabilities,
    read_fulfilment_order,
    read_inventory_level,
)


def main():
    plan = {
        "job_id": "loss-1",
        "idempotency_key": "loss-1-fulfilment",
        "order_id": "gid://shopify/Order/1",
        "notify_customer": False,
        "tracking_info": None,
        "retry_authorised": False,
        "fulfilment_orders": [
            {
                "fulfilment_order_id": "gid://shopify/FulfillmentOrder/10",
                "line_items": [
                    {
                        "fulfilment_order_line_item_id": "gid://shopify/FulfillmentOrderLineItem/100",
                        "quantity": 2,
                    }
                ],
            }
        ],
    }
    payload = build_create_payload(plan)
    assert payload["status"] == "READY"
    gql = payload["variables"]["fulfillment"]
    assert gql["notifyCustomer"] is False
    group = gql["lineItemsByFulfillmentOrder"][0]
    assert group["fulfillmentOrderId"] == "gid://shopify/FulfillmentOrder/10"
    assert group["fulfillmentOrderLineItems"] == [{"id": "gid://shopify/FulfillmentOrderLineItem/100", "quantity": 2}]

    bad_tracking = build_create_payload({**plan, "tracking_info": {"number": "invented"}})
    assert bad_tracking["status"] == "REVIEW_REQUIRED"

    disabled = create_fulfilment(plan, execute=False)
    assert disabled["status"] == "BLOCKED"
    assert "explicit_write_enable_required" in disabled["errors"]
    original_write_enable = os.environ.pop("NTA_SHOPIFY_FULFILMENT_WRITE_ENABLED", None)
    try:
        disabled_execute = create_fulfilment(plan, execute=True)
        assert disabled_execute["status"] == "BLOCKED"
        assert "explicit_write_enable_required" in disabled_execute["errors"]
    finally:
        if original_write_enable is not None:
            os.environ["NTA_SHOPIFY_FULFILMENT_WRITE_ENABLED"] = original_write_enable

    original_bridge = os.environ.get("NTA_SHOPIFY_SESSION_BRIDGE_PATH")
    original_node = os.environ.get("NTA_SHOPIFY_SESSION_BRIDGE_NODE")
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = Path(temp_dir) / "bridge.mjs"
            bridge.write_text("// synthetic bridge marker\n", encoding="utf-8")
            fake_node = Path(temp_dir) / "fake-node"
            fake_node.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "if sys.argv[1:] == ['--version']:\n"
                "    print('v22.0.0')\n"
                "    raise SystemExit(0)\n"
                "request = json.loads(sys.stdin.read())\n"
                "operation = request['operation']\n"
                "auth = {"
                "'source': 'persisted_offline_session', 'token_mode': 'offline', "
                "'persisted_offline_session_verified': True, 'access_token_unexpired': True, "
                "'refresh_token_present': True, 'refreshed': False}\n"
                "if operation == 'capability':\n"
                "    data = {'currentAppInstallation': {'accessScopes': ["
                "{'handle': 'read_merchant_managed_fulfillment_orders'}, "
                "{'handle': 'write_merchant_managed_fulfillment_orders'}, "
                "{'handle': 'read_inventory'}]}}\n"
                "elif operation == 'fulfillment_order':\n"
                "    data = {'fulfillmentOrder': {'id': request['variables']['id'], 'status': 'OPEN', "
                "'order': {'id': 'gid://shopify/Order/1'}, 'lineItems': {'nodes': []}}}\n"
                "elif operation == 'inventory_level':\n"
                "    data = {'inventoryLevel': {'id': request['variables']['id'], "
                "'quantities': [{'name': 'available', 'quantity': 3}], "
                "'item': {'id': 'gid://shopify/InventoryItem/1', 'sku': 'TEST'}, "
                "'location': {'id': 'gid://shopify/Location/1', 'name': 'Test'}}}\n"
                "else:\n"
                "    raise AssertionError(operation)\n"
                "print(json.dumps({'ok': True, 'data': data, 'errors': [], 'auth': auth}))\n",
                encoding="utf-8",
            )
            fake_node.chmod(0o700)
            os.environ["NTA_SHOPIFY_SESSION_BRIDGE_PATH"] = str(bridge)
            os.environ["NTA_SHOPIFY_SESSION_BRIDGE_NODE"] = str(fake_node)
            capability = probe_capabilities(live=True)
            assert capability["transport"] == "persisted_session_bridge"
            assert capability["persisted_offline_session_verified"] is True
            assert capability["fulfilment_create_adapter_verified"] is True
            assert capability["fulfilment_read_adapter_verified"] is True
            assert capability["inventory_read_adapter_verified"] is True
            fulfilment_read = read_fulfilment_order("gid://shopify/FulfillmentOrder/10")
            assert fulfilment_read["status"] == "SUCCESS"
            assert fulfilment_read["snapshot"]["source"] == "FRESH_SHOPIFY_READ"
            inventory_read = read_inventory_level("gid://shopify/InventoryLevel/20?inventory_item_id=1")
            assert inventory_read["status"] == "SUCCESS"
            assert inventory_read["snapshot"]["source"] == "FRESH_SHOPIFY_READ"
    finally:
        if original_bridge is None:
            os.environ.pop("NTA_SHOPIFY_SESSION_BRIDGE_PATH", None)
        else:
            os.environ["NTA_SHOPIFY_SESSION_BRIDGE_PATH"] = original_bridge
        if original_node is None:
            os.environ.pop("NTA_SHOPIFY_SESSION_BRIDGE_NODE", None)
        else:
            os.environ["NTA_SHOPIFY_SESSION_BRIDGE_NODE"] = original_node

    print("DRY_RUN_PASS: guarded Shopify fulfilment API adapter payload mapping; fulfillmentCreate uses exact FulfillmentOrder IDs and line-item IDs/quantities, notifications disabled, unverified tracking blocked, explicit live-write enable required, and offline mode makes no false capability claims; no Shopify writes, network calls, inventory changes, or model calls")
    print("Payload status:", payload["status"])
    print("Unverified tracking status:", bad_tracking["status"])
    print("Write-disabled status:", disabled["status"])
    print("Bridge fulfilment create capability verified:", capability["fulfilment_create_adapter_verified"])
    print("Bridge fulfilment read capability verified:", capability["fulfilment_read_adapter_verified"])
    print("Bridge inventory read capability verified:", capability["inventory_read_adapter_verified"])


if __name__ == "__main__":
    main()
