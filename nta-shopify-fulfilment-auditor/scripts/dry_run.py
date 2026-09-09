from fulfilment_audit import audit_fulfilment


def expect(condition, message):
    if not condition:
        raise AssertionError(message)


expected = {
    "order_id": "gid://shopify/Order/100",
    "notify_customer": False,
    "fulfilled_lines": [
        {"fulfilment_order_line_item_id": "gid://shopify/FulfillmentOrderLineItem/300", "quantity": 2}
    ],
}
actual = {
    "source": "FRESH_SHOPIFY_READ",
    "order_id": "gid://shopify/Order/100",
    "status": "SUCCESS",
    "fulfilled_lines": [
        {"fulfilment_order_line_item_id": "gid://shopify/FulfillmentOrderLineItem/300", "quantity": 2}
    ],
}

expect(audit_fulfilment(expected, actual)["status"] == "PASS", "matching fresh fulfilment should pass")
expect(audit_fulfilment(expected, {**actual, "source": "WRITER_RESPONSE"})["status"] == "FAIL", "writer response must not count as audit evidence")
expect(audit_fulfilment(expected, {**actual, "order_id": "gid://shopify/Order/999"})["status"] == "FAIL", "wrong order must fail")
expect(audit_fulfilment(expected, {**actual, "fulfilled_lines": [{"fulfilment_order_line_item_id": "gid://shopify/FulfillmentOrderLineItem/300", "quantity": 1}]})["status"] == "FAIL", "wrong quantity must fail")

print("DRY_RUN_PASS: deterministic Shopify fulfilment audit comparator; fresh-read source gate, exact order identity, exact fulfilment-line IDs and quantities, mismatch failure; no Shopify writes, network calls, inventory changes, or model calls")
print("Matching fresh read:", audit_fulfilment(expected, actual)["status"])
print("Writer-response evidence:", audit_fulfilment(expected, {**actual, "source": "WRITER_RESPONSE"})["status"])
