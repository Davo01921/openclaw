#!/usr/bin/env python3
"""Deterministic shipment-event validation and verifier-request construction."""

from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime
from typing import Any, Dict, List


def _review(*problems: str) -> Dict[str, Any]:
    return {"status": "REVIEW_REQUIRED", "problems": list(problems)}


def _iso_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.tzinfo is not None
    except ValueError:
        return False


def validate_event(event: Any) -> Dict[str, Any]:
    if not isinstance(event, dict):
        return _review("event must be an object")

    problems: List[str] = []
    for key in ("job_id", "order_id"):
        if not isinstance(event.get(key), str) or not event[key].strip():
            problems.append(f"{key} is required")
    if event.get("authorised") is not True:
        problems.append("explicit authorisation is required")
    if not _iso_timestamp(event.get("shipped_at")):
        problems.append("shipped_at must be an offset-aware ISO-8601 timestamp")
    if not isinstance(event.get("notify_customer"), bool):
        problems.append("notify_customer must be explicit")

    if not re.fullmatch(r"gid://shopify/Order/[1-9]\d*", str(event.get("order_id", ""))):
        problems.append("exact Shopify Order GID is required")

    carrier = event.get("carrier")
    tracking = event.get("tracking_number")
    if carrier is not None and (not isinstance(carrier, str) or not carrier.strip()):
        problems.append("carrier must be a non-empty string or null")
    if tracking is not None and (not isinstance(tracking, str) or not tracking.strip()):
        problems.append("tracking_number must be a non-empty string or null")
    if (carrier is None) != (tracking is None):
        problems.append("carrier and tracking_number must either both be supplied or both be null")

    fos = event.get("fulfilment_orders")
    if not isinstance(fos, list) or not fos:
        problems.append("at least one fulfilment_order is required")
    else:
        seen = set()
        seen_orders = set()
        for i, fo in enumerate(fos):
            if not isinstance(fo, dict) or not isinstance(fo.get("fulfilment_order_id"), str) or not fo["fulfilment_order_id"].strip():
                problems.append(f"fulfilment_orders[{i}].fulfilment_order_id is required")
                continue
            if not re.fullmatch(r"gid://shopify/FulfillmentOrder/[1-9]\d*", fo["fulfilment_order_id"]):
                problems.append("exact FulfillmentOrder GID is required")
            if fo["fulfilment_order_id"] in seen_orders:
                problems.append("duplicate fulfilment order ID")
            seen_orders.add(fo["fulfilment_order_id"])
            lines = fo.get("line_items")
            if not isinstance(lines, list) or not lines:
                problems.append(f"fulfilment_orders[{i}] requires line_items")
                continue
            for j, line in enumerate(lines):
                if not isinstance(line, dict):
                    problems.append(f"fulfilment_orders[{i}].line_items[{j}] must be an object")
                    continue
                lid = line.get("fulfilment_order_line_item_id")
                qty = line.get("quantity")
                if not re.fullmatch(r"gid://shopify/FulfillmentOrderLineItem/[1-9]\d*", str(lid)):
                    problems.append("exact FulfillmentOrderLineItem GID is required")
                if not isinstance(lid, str) or not lid.strip():
                    problems.append(f"fulfilment_orders[{i}].line_items[{j}] requires exact line id")
                elif lid in seen:
                    problems.append(f"duplicate fulfilment line id: {lid}")
                else:
                    seen.add(lid)
                if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
                    problems.append(f"fulfilment_orders[{i}].line_items[{j}] quantity must be a positive integer")

    return _review(*problems) if problems else {"status": "VALID"}


def canonical_identity(event: Dict[str, Any]) -> Dict[str, Any]:
    fos = []
    for fo in event["fulfilment_orders"]:
        lines = sorted(
            [{"id": x["fulfilment_order_line_item_id"].strip(), "quantity": x["quantity"]} for x in fo["line_items"]],
            key=lambda x: x["id"],
        )
        fos.append({"id": fo["fulfilment_order_id"].strip(), "lines": lines})
    fos.sort(key=lambda x: x["id"])
    return {
        "order_id": event["order_id"].strip(),
        "carrier": event.get("carrier").strip() if event.get("carrier") else None,
        "tracking_number": event.get("tracking_number").strip() if event.get("tracking_number") else None,

        "fulfilment_orders": fos,
    }


def idempotency_key(event: Dict[str, Any]) -> str:
    raw = json.dumps(canonical_identity(event), sort_keys=True, separators=(",", ":")).encode()
    return "nta-ship-" + hashlib.sha256(raw).hexdigest()


def build_verifier_request(event: Dict[str, Any]) -> Dict[str, Any]:
    checked = validate_event(event)
    if checked["status"] != "VALID":
        return checked
    key = idempotency_key(event)
    return {
        "status": "READY",
        "write_request": {
            "job_id": event["job_id"].strip(),
            "idempotency_key": key,
            "entity": "fulfilment",
            "authorised": True,
            "resolved_identity": {
                "order_id": event["order_id"].strip(),
                "fulfilment_order_ids": [x["fulfilment_order_id"].strip() for x in event["fulfilment_orders"]],
            },
            "authorised_changes": [{
                "notify_customer": event["notify_customer"],
                "carrier": event.get("carrier"),
                "tracking_number": event.get("tracking_number"),
                "shipped_at": event["shipped_at"],
                "fulfilment_orders": event["fulfilment_orders"],
            }],
            "protected_fields": ["inventory_adjustment"],
            "expected_result": {
                "tracking_info": {"company": event["carrier"].strip(), "number": event["tracking_number"].strip()} if event.get("carrier") else None,
                "order_id": event["order_id"].strip(),
                "notify_customer": event["notify_customer"],
                "fulfilled_lines": [
                    {"fulfilment_order_line_item_id": line["fulfilment_order_line_item_id"], "quantity": line["quantity"]}
                    for fo in event["fulfilment_orders"] for line in fo["line_items"]
                ],
            },
            "retry_authorised": False,
        },
    }


if __name__ == "__main__":
    import sys
    event = json.load(sys.stdin)
    print(json.dumps(build_verifier_request(event), indent=2, sort_keys=True))
