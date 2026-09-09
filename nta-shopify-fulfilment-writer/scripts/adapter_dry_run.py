#!/usr/bin/env python3
from shopify_fulfilment_api import build_create_payload, probe_capabilities, create_fulfilment


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

    capability = probe_capabilities(live=False)
    assert capability["fulfilment_create_adapter_verified"] is False
    assert capability["fulfilment_read_adapter_verified"] is False
    assert capability["inventory_read_adapter_verified"] is False

    print("DRY_RUN_PASS: guarded Shopify fulfilment API adapter payload mapping; fulfillmentCreate uses exact FulfillmentOrder IDs and line-item IDs/quantities, notifications disabled, unverified tracking blocked, explicit live-write enable required, and offline mode makes no false capability claims; no Shopify writes, network calls, inventory changes, or model calls")
    print("Payload status:", payload["status"])
    print("Unverified tracking status:", bad_tracking["status"])
    print("Write-disabled status:", disabled["status"])
    print("Offline fulfilment create capability verified:", capability["fulfilment_create_adapter_verified"])
    print("Offline fulfilment read capability verified:", capability["fulfilment_read_adapter_verified"])
    print("Offline inventory read capability verified:", capability["inventory_read_adapter_verified"])


if __name__ == "__main__":
    main()
