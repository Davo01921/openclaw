#!/usr/bin/env python3
import argparse
import fcntl
import json
import os
import re
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import store_use_order as base

SYDNEY = ZoneInfo("Australia/Sydney")
CUTOFF_HOUR = 18
LIVE_WRITE_GATE = "NTA_SHOPIFY_STORE_USE_BATCH_WRITE_ENABLED"
STATE_DIR = Path("/Users/davidlo/.openclaw/workspace/fred/state/nta-store-use-batches")

def emit(payload, code=0):
    print(json.dumps(payload, indent=2))
    raise SystemExit(code)

def stop(message, **details):
    emit({"status": "BLOCKED", "message": message, **details}, 2)

def logical_date(now=None):
    current = now or datetime.now(SYDNEY)
    if current.time() >= time(CUTOFF_HOUR, 0):
        return (current + timedelta(days=1)).date().isoformat()
    return current.date().isoformat()

def batch_tag(date):
    return "StoreUseBatch-" + date

def queue_path(date):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        stop("Batch date must use YYYY-MM-DD.")
    return STATE_DIR / (date + ".json")

def load_queue(date):
    path = queue_path(date)
    if not path.exists():
        return {"batch_date": date, "status": "OPEN", "items": []}
    return json.loads(path.read_text())

def save_queue(queue):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = queue_path(queue["batch_date"])
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(queue, indent=2) + "\n")
    os.replace(temporary, path)

class QueueLock:
    def __enter__(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.handle = (STATE_DIR / ".lock").open("a+")
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *_):
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()

def one_customer(shop):
    data = shop.gql(base.CUSTOMERS_QUERY, {"query": base.CUSTOMER_NAME})
    matches = [
        customer for customer in data["customers"]["nodes"]
        if customer["displayName"].lower() == base.CUSTOMER_NAME.lower()
    ]
    if len(matches) != 1:
        stop("Expected exactly one NTA StoreUse customer.", matches=len(matches))
    return matches[0]


def validate_add(args):
    if not re.fullmatch(r"gid://shopify/ProductVariant/\d+", args.variant_id or ""):
        stop("A valid exact variant ID is required.")
    if not re.fullmatch(r"[A-Za-z0-9:_-]{8,180}", args.source_ref or ""):
        stop("A stable source reference is required.")
    if args.quantity < 1 or args.quantity > 100:
        stop("Quantity must be from 1 to 100.")
    if not args.reason or len(args.reason) > 160:
        stop("A concise store-use reason is required.")
    if args.evidence and len(args.evidence) > 500:
        stop("Evidence must be 500 characters or fewer.")


def completed_with_tag(shop, tag):
    matches = base.existing_orders(shop, tag)
    if len(matches) > 1:
        stop("Multiple completed orders share an idempotency tag.", orders=[item["name"] for item in matches])
    return matches[0] if matches else None

def intake_details(shop, args):
    current = base.variant(shop, args.variant_id)
    if not current or current["product"]["status"] != "ACTIVE":
        stop("The exact variant is unavailable or inactive.")
    eligible = [
        level for level in current["inventoryItem"]["inventoryLevels"]["nodes"]
        if base.quantities(level).get("available", 0) >= args.quantity
    ]
    level = None
    if args.location_id:
        level = next((item for item in eligible if item["location"]["id"] == args.location_id), None)
    elif len(eligible) == 1:
        level = eligible[0]
    if level is None:
        stop("Inventory location is ambiguous or has insufficient available stock.")
    one_customer(shop)
    return current, level

def add(shop, args):
    validate_add(args)
    date = args.date or logical_date()
    ref_tag = base.reference_tag(args.source_ref)
    existing = completed_with_tag(shop, ref_tag)
    if existing:
        emit({"status": "ALREADY_COMPLETED", "order": existing, "source_ref": args.source_ref})

    queue = load_queue(date)
    queued = next((item for item in queue["items"] if item["source_ref"] == args.source_ref), None)
    if queued:
        emit({"status": "ALREADY_QUEUED", "batch_date": date, "item": queued})
    current, level = intake_details(shop, args)
    item = {
        "source_ref": args.source_ref,
        "reference_tag": ref_tag,
        "variant_id": args.variant_id,
        "product_title": current["product"]["title"],
        "variant_title": current["title"],
        "sku": current.get("sku"),
        "quantity": args.quantity,
        "reason": args.reason,
        "evidence": (args.evidence or "")[:500],
        "location_id": level["location"]["id"],
        "location_name": level["location"]["name"],
        "intake_inventory_quantity": current["inventoryQuantity"],
        "intake_available": base.quantities(level)["available"],
        "queued_at": datetime.now(SYDNEY).isoformat(),
    }

    plan = {
        "status": "READY",
        "batch_date": date,
        "item": item,
        "inventory_timing": "Shopify inventory remains unchanged until the 6 pm batch close.",
    }
    if not args.execute:
        emit(plan)
    with QueueLock():
        queue = load_queue(date)
        queued = next((entry for entry in queue["items"] if entry["source_ref"] == args.source_ref), None)
        if queued:
            emit({"status": "ALREADY_QUEUED", "batch_date": date, "item": queued})
        if queue.get("status") != "OPEN":
            stop("The selected daily batch is already closed.", batch_date=date)
        queue["items"].append(item)
        save_queue(queue)
        confirmed = load_queue(date)
    verified = any(entry["source_ref"] == args.source_ref for entry in confirmed["items"])
    emit({
        "status": "QUEUED_VERIFIED" if verified else "FAILED",
        "batch_date": date,
        "queued_items": len(confirmed["items"]),
        "item": item,
        "inventory_timing": "Shopify inventory will be deducted at the 6 pm batch close.",
    }, 0 if verified else 3)

def aggregate(items):
    grouped = {}
    for item in items:
        grouped[item["variant_id"]] = grouped.get(item["variant_id"], 0) + item["quantity"]
    return grouped

def fresh_preflight(shop, queue):
    grouped = aggregate(queue["items"])
    before = {}
    locations = set()
    for variant_id, quantity in grouped.items():
        current = base.variant(shop, variant_id)
        if not current or current["product"]["status"] != "ACTIVE":
            stop("A queued variant is unavailable or inactive.", variant_id=variant_id)
        level = next(
            (item for item in current["inventoryItem"]["inventoryLevels"]["nodes"]
             if item["location"]["id"] == next(x["location_id"] for x in queue["items"] if x["variant_id"] == variant_id)),
            None,
        )
        if not level or base.quantities(level).get("available", 0) < quantity:
            stop("Insufficient inventory at batch close.", variant_id=variant_id, required=quantity)
        locations.add(level["location"]["id"])
        before[variant_id] = {
            "variant": current,
            "level": level,
            "quantity": quantity,
            "values": base.quantities(level),
        }
    if len(locations) != 1:
        stop("Queued store-use items span multiple Shopify locations.")
    return before, next(iter(locations))

def order_note(queue):
    lines = ["NTA daily store-use batch {}.".format(queue["batch_date"])]
    for index, item in enumerate(queue["items"], 1):
        detail = "{}. {} × {}; reason {}; source {}".format(
            index,
            item["quantity"],
            item["product_title"],
            item["reason"],
            item["source_ref"],
        )
        if item.get("evidence"):
            detail += "; evidence {}".format(item["evidence"])
        lines.append(detail + ".")
    return "\\n".join(lines)


def enable_scoped_live_writes():
    if os.getenv(LIVE_WRITE_GATE) != "true":
        stop("The scheduled store-use batch live write gate is not enabled.", gate=LIVE_WRITE_GATE)
    os.environ["NTA_SHOPIFY_ORDER_WRITE_ENABLED"] = "true"
    os.environ["NTA_SHOPIFY_FULFILMENT_WRITE_ENABLED"] = "true"

def fulfill_remaining(shop, order_id):
    state = shop.gql(base.FULFILLMENT_STATE_QUERY, {"id": order_id})["order"]
    if not state:
        stop("The created order could not be read before fulfilment.")
    if state["displayFulfillmentStatus"] == "FULFILLED":
        return {"status": "ALREADY_FULFILLED", "fulfillment_id": None}
    groups = []
    for fulfillment_order in state["fulfillmentOrders"]["nodes"]:
        lines = [
            {"id": line["id"], "quantity": line["remainingQuantity"]}
            for line in fulfillment_order["lineItems"]["nodes"]
            if line["remainingQuantity"] > 0
        ]
        if lines:
            groups.append({
                "fulfillmentOrderId": fulfillment_order["id"],
                "fulfillmentOrderLineItems": lines,
            })
    if not groups:
        stop("No fulfillable line items were returned for the created order.")
    result = shop.gql(base.CREATE_FULFILLMENT_MUTATION, {
        "fulfillment": {
            "lineItemsByFulfillmentOrder": groups,
            "notifyCustomer": False,
        }
    })["fulfillmentCreate"]
    if result["userErrors"]:
        stop("Shopify rejected the daily store-use fulfilment.", errors=result["userErrors"])
    fulfillment = result.get("fulfillment") or {}
    if not fulfillment.get("id"):
        stop("Shopify did not return a fulfilment ID.")
    return {"status": "FULFILLED", "fulfillment_id": fulfillment["id"]}

def close(shop, args):
    date = args.date or datetime.now(SYDNEY).date().isoformat()
    tag = batch_tag(date)
    existing = completed_with_tag(shop, tag)
    if existing:
        if existing.get("displayFulfillmentStatus") != "FULFILLED":
            stop("An existing daily store-use order is not fulfilled; manual reconciliation is required.", order=existing["name"])
        with QueueLock():
            queue = load_queue(date)
            queue.update({"status": "CLOSED", "order": {"id": existing["id"], "name": existing["name"]}})
            save_queue(queue)
        emit({"status": "ALREADY_CLOSED", "batch_date": date, "order": existing})

    queue = load_queue(date)
    if not queue["items"]:
        emit({"status": "NO_BATCH", "batch_date": date})
    if queue.get("status") != "OPEN":
        emit({"status": "ALREADY_CLOSED", "batch_date": date, "order": queue.get("order")})

    before, location_id = fresh_preflight(shop, queue)
    customer = one_customer(shop)
    grouped = aggregate(queue["items"])
    tags = ["NTA StoreUse", "Store Use", tag] + [item["reference_tag"] for item in queue["items"]]
    variables = {
        "order": {
            "customer": {"toAssociate": {"id": customer["id"]}},
            "lineItems": [{"variantId": variant_id, "quantity": quantity} for variant_id, quantity in grouped.items()],
            "discountCode": {"itemPercentageDiscountCode": {"code": base.DISCOUNT_CODE, "percentage": 100}},
            "financialStatus": "PAID",
            "tags": tags,
            "note": order_note(queue),
            "sourceName": "NTA StoreUse",
        },
        "options": {
            "inventoryBehaviour": "DECREMENT_OBEYING_POLICY",
            "sendReceipt": False,
            "sendFulfillmentReceipt": False,
        },
    }
    plan = {
        "status": "READY_TO_CLOSE",
        "batch_date": date,
        "items": queue["items"],
        "line_items": variables["order"]["lineItems"],
        "expected_total": {"amount": "0.00", "currency": "AUD"},
    }
    if not args.execute:
        emit(plan)
    enable_scoped_live_writes()

    with QueueLock():
        current_queue = load_queue(date)
        if current_queue.get("status") != "OPEN":
            emit({"status": "ALREADY_CLOSED", "batch_date": date, "order": current_queue.get("order")})
        existing = completed_with_tag(shop, tag)
        if existing:
            if existing.get("displayFulfillmentStatus") != "FULFILLED":
                stop("An existing daily store-use order is not fulfilled; manual reconciliation is required.", order=existing["name"])
            current_queue.update({"status": "CLOSED", "order": {"id": existing["id"], "name": existing["name"]}})
            save_queue(current_queue)
            emit({"status": "ALREADY_CLOSED", "batch_date": date, "order": existing})
        try:
            payload = shop.gql(base.CREATE_MUTATION, variables)["orderCreate"]
        except Exception as error:
            recovered = completed_with_tag(shop, tag)
            if recovered:
                if recovered.get("displayFulfillmentStatus") == "FULFILLED":
                    current_queue.update({"status": "CLOSED", "order": {"id": recovered["id"], "name": recovered["name"]}})
                    save_queue(current_queue)
                emit({"status": "INDETERMINATE_EXISTING", "batch_date": date, "order": recovered, "message": str(error)}, 3)
            raise
        if payload["userErrors"]:
            stop("Shopify rejected the daily store-use order.", errors=payload["userErrors"])
        order = payload["order"]
        fulfillment = fulfill_remaining(shop, order["id"])
        refreshed = completed_with_tag(shop, tag)
        if not refreshed or refreshed.get("displayFulfillmentStatus") != "FULFILLED":
            stop("The daily store-use order was not verified as fulfilled after the mutation.", order=order["name"])
        order = refreshed
        current_queue.update({
            "status": "CLOSED",
            "closed_at": datetime.now(SYDNEY).isoformat(),
            "order": {"id": order["id"], "name": order["name"]},
        })
        save_queue(current_queue)

    checks = {
        "zero_aud_total": float(order["currentTotalPriceSet"]["shopMoney"]["amount"]) == 0
            and order["currentTotalPriceSet"]["shopMoney"]["currencyCode"] == "AUD",
        "paid": order["displayFinancialStatus"] == "PAID",
        "fulfilled": order["displayFulfillmentStatus"] == "FULFILLED",
        "customer": (order.get("customer") or {}).get("id") == customer["id"],
        "daily_tag": tag in order["tags"],
        "all_references": all(item["reference_tag"] in order["tags"] and item["source_ref"] in order["note"] for item in queue["items"]),
    }
    inventory = []
    for variant_id, snapshot in before.items():
        current = base.variant(shop, variant_id)
        level = next(item for item in current["inventoryItem"]["inventoryLevels"]["nodes"] if item["location"]["id"] == location_id)
        old = snapshot["values"]
        new = base.quantities(level)
        delta_ok = (
            new["available"] == old["available"] - snapshot["quantity"]
            and current["inventoryQuantity"] == snapshot["variant"]["inventoryQuantity"] - snapshot["quantity"]
        )
        checks["inventory_" + variant_id.rsplit("/", 1)[-1]] = delta_ok
        inventory.append({
            "variant_id": variant_id,
            "product": current["product"]["title"],
            "quantity": snapshot["quantity"],
            "before_available": old["available"],
            "after_available": new["available"],
            "verified": delta_ok,
        })
    ok = all(checks.values())
    emit({
        "status": "CLOSED_VERIFIED" if ok else "FAILED",
        "batch_date": date,
        "order": {"id": order["id"], "name": order["name"]},
        "fulfillment": fulfillment,
        "checks": checks,
        "inventory": inventory,
        "records": queue["items"],
    }, 0 if ok else 3)

def parser():
    root = argparse.ArgumentParser()
    root.add_argument("--env-file", default=base.DEFAULT_ENV_FILE)
    sub = root.add_subparsers(dest="command", required=True)
    add_parser = sub.add_parser("add")
    add_parser.add_argument("--variant-id", required=True)
    add_parser.add_argument("--quantity", required=True, type=int)
    add_parser.add_argument("--source-ref", required=True)
    add_parser.add_argument("--reason", required=True)
    add_parser.add_argument("--evidence")
    add_parser.add_argument("--location-id")
    add_parser.add_argument("--date")
    add_parser.add_argument("--execute", action="store_true")
    close_parser = sub.add_parser("close")
    close_parser.add_argument("--date")
    close_parser.add_argument("--execute", action="store_true")
    return root

def main():
    args = parser().parse_args()
    try:
        shop = base.Shopify(base.load_env(args.env_file))
        if args.command == "add":
            add(shop, args)
        close(shop, args)
    except SystemExit:
        raise
    except Exception as error:
        stop("Shopify batch operation failed.", error=str(error))

if __name__ == "__main__":
    main()
