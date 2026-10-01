#!/usr/bin/env python3
import argparse
import copy
import hashlib
import tempfile
from contextlib import nullcontext
from decimal import Decimal, InvalidOperation
import fcntl
import json
import os
import re
import time as time_module
from datetime import date as calendar_date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import death_loss_order as base

SYDNEY = ZoneInfo("Australia/Sydney")
CUTOFF_HOUR = 18
CUTOFF_MINUTE = 0
LIVE_WRITE_GATE = "NTA_SHOPIFY_DEATH_BATCH_WRITE_ENABLED"
STATE_DIR = None
CUSTOMER_ID = None
LOCATION_ID = None
CHANNEL_ID = None
AUTHORIZED_SENDERS = set()
RECOVERY_STATES = {'ORDER_CREATING', 'ORDER_CREATED', 'FULFILLING', 'VERIFYING', 'RECONCILIATION_REQUIRED'}

def emit(payload, code=0):
    print(json.dumps(payload, indent=2))
    raise SystemExit(code)

def stop(message, **details):
    emit({"status": "BLOCKED", "message": message, **details}, 2)

def logical_date(now=None):
    current = now or datetime.now(SYDNEY)
    if current.tzinfo is None:
        stop('An aware datetime is required.')
    current = current.astimezone(SYDNEY)
    if current.time() >= time(CUTOFF_HOUR, CUTOFF_MINUTE):
        return (current + timedelta(days=1)).date().isoformat()
    return current.date().isoformat()

def batch_tag(date):
    return "DeathBatch-" + date

def queue_path(date):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        stop("Batch date must use YYYY-MM-DD.")
    try:
        calendar_date.fromisoformat(date)
    except ValueError:
        stop('Invalid calendar date.')
    if STATE_DIR is None:
        stop('Queue directory configuration is required.')
    return STATE_DIR / (date + ".json")

def record_id(source_ref):
    return 'loss-' + hashlib.sha256(source_ref.encode()).hexdigest()[:24]

def positive_quantity(value):
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 100

def validate_queue(queue, date):
    if not isinstance(queue, dict) or queue.get('batch_date') != date or not isinstance(queue.get('status'), str) or queue['status'] not in {'OPEN', 'CLOSED', *RECOVERY_STATES} or not isinstance(queue.get('items'), list):
        stop('Invalid queue schema.', batch_date=date)
    sources = set()
    for item in queue['items']:
        if not isinstance(item, dict) or not positive_quantity(item.get('quantity')):
            stop('Invalid queued quantity.', batch_date=date)
        source = item.get('source_ref')
        if not isinstance(source, str) or not re.fullmatch(r'[A-Za-z0-9:_-]{8,180}', source) or source in sources:
            stop('Invalid or duplicate queued source.', batch_date=date)
        sources.add(source)
        for key, kind in [('variant_id', 'ProductVariant'), ('location_id', 'Location')]:
            if not isinstance(item.get(key), str) or not re.fullmatch(r'gid://shopify/' + kind + r'/[1-9]\d*', item[key]):
                stop('Invalid queued identifier.', field=key)
        for key in ['fish', 'tank', 'evidence', 'cause']:
            if not isinstance(item.get(key), str) or not item[key].strip():
                stop('Invalid queued evidence.', field=key)
        if not re.fullmatch(r'[A-Za-z0-9/-]{1,32}', item['tank']) or len(item['evidence']) > 500:
            stop('Invalid queued tank/evidence length.')
        if item.get('reference_tag') != base.reference_tag(source):
            stop('Invalid queued reference tag.')
        expected_id = record_id(source)
        if item.get('record_id', expected_id) != expected_id:
            stop('Invalid record ID.')
        item.setdefault('record_id', expected_id)
        if not isinstance(item.get('history', []), list):
            stop('Invalid amendment history.')
        amendment_ids = set()
        for amendment in item.get('history', []):
            if not isinstance(amendment, dict) or not isinstance(amendment.get('amendment_id'), str) or not re.fullmatch(r'[A-Za-z0-9:_-]{8,180}', amendment['amendment_id']) or amendment['amendment_id'] in amendment_ids or not positive_quantity(amendment.get('from_quantity')) or not positive_quantity(amendment.get('to_quantity')):
                stop('Invalid or duplicate amendment history.')
            amendment_ids.add(amendment['amendment_id'])
    if 'recovery' in queue and not isinstance(queue['recovery'], dict):
        stop('Invalid recovery schema.')
    return queue

def load_queue(date):
    path = queue_path(date)
    if not path.exists():
        return {"batch_date": date, "status": "OPEN", "items": []}
    try:
        queue = json.loads(path.read_text())
    except (OSError, ValueError):
        stop('Queue is unreadable; no changes made.', batch_date=date)
    return validate_queue(queue, date)

def save_queue(queue):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = queue_path(queue["batch_date"])
    validate_queue(queue, queue['batch_date'])
    descriptor, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=STATE_DIR)
    try:
        with os.fdopen(descriptor, 'w') as handle:
            handle.write(json.dumps(queue, indent=2) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        directory = os.open(STATE_DIR, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)

class QueueLock:
    def __enter__(self):
        if STATE_DIR is None:
            stop('Queue directory configuration is required.')
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.handle = (STATE_DIR / ".lock").open("a+")
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *_):
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()

def one_customer(shop):
    if not CUSTOMER_ID:
        stop('Exact customer configuration is required.')
    data = shop.gql(base.CUSTOMERS_QUERY, {"query": base.CUSTOMER_NAME})
    matches = [
        customer for customer in data["customers"]["nodes"]
        if customer['id'] == CUSTOMER_ID and customer["displayName"].casefold() == base.CUSTOMER_NAME.casefold()
    ]
    if len(matches) != 1:
        stop("Expected exactly one NTA Losses customer.", matches=len(matches))
    return matches[0]

def validate_add(args):
    if not re.fullmatch(r"gid://shopify/ProductVariant/\d+", args.variant_id or ""):
        stop("A valid exact variant ID is required.")
    if not re.fullmatch(r"[A-Za-z0-9:_-]{8,180}", args.source_ref or ""):
        stop("A stable source reference is required.")
    if not re.fullmatch(r"[A-Za-z0-9/-]{1,32}", args.tank or ""):
        stop("A valid tank is required.")
    if not isinstance(args.fish, str) or not args.fish.strip() or not isinstance(args.evidence, str) or not args.evidence.strip() or len(args.evidence) > 500:
        stop("Fish and concise evidence are required.")
    if not positive_quantity(args.quantity):
        stop("Quantity must be from 1 to 100.")
    if args.confidence != "HIGH":
        stop("Automatic batching requires HIGH confidence.")
    if args.prior_manual_deduction:
        stop("A prior manual deduction requires David's explicit reconciliation.")

def validate_source(args):
    if not CHANNEL_ID or not AUTHORIZED_SENDERS:
        stop('Authorized Discord source configuration is required.')
    if getattr(args, 'channel_id', None) != CHANNEL_ID or getattr(args, 'sender_id', None) not in AUTHORIZED_SENDERS:
        stop('Discord source is not authorized.')

def find_records(source_ref=None, identifier=None):
    matches = []
    for path in sorted(STATE_DIR.glob('*.json')):
        queue = load_queue(path.stem)
        for entry in queue['items']:
            if (source_ref and entry['source_ref'] == source_ref) or (identifier and entry['record_id'] == identifier):
                matches.append((queue, entry))
    return matches

def completed_with_tag(shop, tag):
    matches = base.existing_orders(shop, tag)
    if len(matches) > 1:
        stop("Multiple completed orders share an idempotency tag.", orders=[item["name"] for item in matches])
    return matches[0] if matches else None

def wait_for_fulfilled(shop, tag, timeout_seconds=45, interval_seconds=2):
    """Poll Shopify after fulfilment creation until its order projection catches up."""
    deadline = time_module.monotonic() + timeout_seconds
    latest = None
    delay = interval_seconds
    while True:
        remaining = deadline - time_module.monotonic()
        if remaining <= 0:
            return latest
        original_timeout = getattr(shop, 'read_timeout', 35)
        shop.read_timeout = max(.01, min(original_timeout, remaining))
        try:
            candidate = completed_with_tag(shop, tag)
            if candidate:
                latest = candidate
        except RuntimeError:
            pass  # Reads may be retried; mutations never are.
        finally:
            shop.read_timeout = original_timeout
        if latest and latest.get("displayFulfillmentStatus") == "FULFILLED":
            return latest
        if time_module.monotonic() >= deadline:
            return latest
        time_module.sleep(min(delay, max(0, deadline - time_module.monotonic())))
        delay = min(delay * 2, 8)

def intake_details(shop, args):
    current = base.variant(shop, args.variant_id)
    if not current or current["product"]["status"] != "ACTIVE":
        stop("The exact variant is unavailable or inactive.")
    if current['id'] != args.variant_id:
        stop('Exact variant read returned another identity.')
    if base.fish_identity(current['product']['title'], current.get('title', ''), args.tank) != base.norm(args.fish):
        stop('The exact variant conflicts with the reported fish; review is required.')
    complete_connection(current['inventoryItem']['inventoryLevels'])
    eligible = [
        level for level in current["inventoryItem"]["inventoryLevels"]["nodes"]
        if base.quantities(level).get("available", 0) >= args.quantity
    ]
    level = None
    selected_location = args.location_id or LOCATION_ID
    if not LOCATION_ID or selected_location != LOCATION_ID:
        stop('The inventory location must match verified configuration.')
    level = next((item for item in eligible if item['location']['id'] == selected_location), None)
    if level is None:
        stop("Inventory location is ambiguous or has insufficient available stock.")
    one_customer(shop)
    return current, level

def complete_connection(connection):
    if not isinstance(connection, dict) or connection.get('pageInfo', {}).get('hasNextPage') is not False or not isinstance(connection.get('nodes'), list):
        stop('A Shopify connection is truncated or lacks completeness evidence.')
    return connection['nodes']


def add(shop, args):
    validate_source(args)
    original_source = args.source_ref
    item_key = getattr(args, 'item_key', None)
    if item_key:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', item_key):
            stop('Invalid stable message item key.')
        args.source_ref = original_source + '-' + item_key
    validate_add(args)
    date = args.date or logical_date()
    ref_tag = base.reference_tag(args.source_ref)
    with QueueLock() if args.execute else nullcontext():
        matches = find_records(source_ref=args.source_ref)
        if len(matches) > 1:
            stop('Source reference occurs in multiple queue records.')
        if matches:
            found_queue, entry = matches[0]
            if entry['variant_id'] != args.variant_id or entry['quantity'] != args.quantity or entry['tank'] != args.tank:
                stop('Duplicate source has conflicting details; use amend or review.', record_id=entry['record_id'])
            emit({'status': 'ALREADY_QUEUED' if found_queue['status'] == 'OPEN' else 'ALREADY_COMPLETED' if found_queue['status'] == 'CLOSED' else 'BLOCKED',
                  'batch_date': found_queue['batch_date'], 'item': entry, 'batch_status': found_queue['status']},
                 2 if found_queue['status'] in RECOVERY_STATES else 0)
        existing = completed_with_tag(shop, ref_tag)
        if existing:
            stop('Source already belongs to a Shopify order; verify the existing batch.', order=existing['name'])
        queue = load_queue(date)
        if queue['status'] != 'OPEN':
            stop('The selected batch no longer accepts intake.', batch_date=date)
        current, level = intake_details(shop, args)
        outstanding = sum(entry['quantity'] for path in STATE_DIR.glob('*.json')
                          for q in [load_queue(path.stem)] if q['status'] != 'CLOSED'
                          for entry in q['items'] if entry['variant_id'] == args.variant_id and entry['location_id'] == level['location']['id'])
        if outstanding + args.quantity > base.quantities(level)['available']:
            stop('Insufficient available stock for all outstanding queued losses.', required=outstanding + args.quantity)
        item = {
            'source_ref': args.source_ref, 'source_event_ref': original_source,
            'record_id': record_id(args.source_ref), 'reference_tag': ref_tag,
            'variant_id': args.variant_id, 'product_title': current['product']['title'],
            'fish': args.fish.strip(), 'quantity': args.quantity, 'tank': args.tank,
            'cause': (args.cause or 'Unknown').strip() or 'Unknown', 'evidence': args.evidence,
            'location_id': level['location']['id'], 'location_name': level['location']['name'],
            'intake_inventory_quantity': current['inventoryQuantity'],
            'intake_available': base.quantities(level)['available'],
            'queued_at': datetime.now(SYDNEY).isoformat(), 'history': [],
        }
        if not args.execute:
            emit({'status': 'READY', 'batch_date': date, 'item': item, 'write_occurred': False})
        queue['items'].append(item)
        save_queue(queue)
        confirmed = load_queue(date)
        saved = next((entry for entry in confirmed['items'] if entry['record_id'] == item['record_id']), None)
        if saved != item:
            stop('Queue read-back mismatch.')
        emit({'status': 'QUEUED_VERIFIED', 'batch_date': date, 'item': saved, 'queued_items': len(confirmed['items']),
              'inventory_timing': 'Shopify inventory remains unchanged until daily close.'})


def amend(shop, args):
    validate_source(args)
    if not positive_quantity(args.quantity):
        stop('Quantity must be an integer from 1 to 100.')
    if not re.fullmatch(r'[A-Za-z0-9:_-]{8,180}', args.amendment_id or ''):
        stop('A stable amendment event ID is required.')
    with QueueLock() if args.execute else nullcontext():
        matches = find_records(source_ref=args.source_ref, identifier=args.record_id)
        if len(matches) != 1:
            stop('Amendment must identify exactly one existing record.', matches=len(matches))
        queue, item = matches[0]
        history = item.get('history', [])
        prior = next((entry for entry in history if entry.get('amendment_id') == args.amendment_id), None)
        if prior:
            if prior['to_quantity'] != args.quantity:
                stop('Amendment ID was reused with a different quantity.')
            emit({'status': 'ALREADY_AMENDED', 'batch_date': queue['batch_date'], 'item': item, 'amendment': prior})
        if queue['status'] != 'OPEN':
            stop('An order-created or closed batch cannot be amended.', batch_status=queue['status'])
        if args.expected_quantity is None or args.expected_quantity != item['quantity']:
            stop('Expected quantity does not match the current record.', current_quantity=item['quantity'])
        current = base.variant(shop, item['variant_id'])
        if not current or current['id'] != item['variant_id'] or current['product']['status'] != 'ACTIVE':
            stop('Amendment variant is unavailable or inactive.')
        level = next((entry for entry in complete_connection(current['inventoryItem']['inventoryLevels'])
                      if entry['location']['id'] == item['location_id']), None)
        outstanding = sum(entry['quantity'] for path in STATE_DIR.glob('*.json')
                          for q in [load_queue(path.stem)] if q['status'] != 'CLOSED'
                          for entry in q['items'] if entry['variant_id'] == item['variant_id'] and entry['location_id'] == item['location_id'])
        required = outstanding - item['quantity'] + args.quantity
        if not level or item['location_id'] != LOCATION_ID or base.quantities(level).get('available', 0) < required:
            stop('Insufficient available stock for the amended outstanding losses.', required=required)
        amendment = {'amendment_id': args.amendment_id, 'from_quantity': item['quantity'], 'to_quantity': args.quantity,
                     'at': datetime.now(SYDNEY).isoformat(), 'sender_id': args.sender_id}
        proposed = copy.deepcopy(item)
        proposed['quantity'] = args.quantity
        proposed.setdefault('history', []).append(amendment)
        if not args.execute:
            emit({'status': 'READY', 'batch_date': queue['batch_date'], 'item': proposed, 'write_occurred': False})
        item.clear()
        item.update(proposed)
        save_queue(queue)
        saved = next(entry for entry in load_queue(queue['batch_date'])['items'] if entry['record_id'] == item['record_id'])
        if saved != proposed:
            stop('Amendment read-back mismatch.')
        emit({'status': 'AMENDED_VERIFIED', 'batch_date': queue['batch_date'], 'item': saved})


def aggregate(items):
    grouped = {}
    for item in items:
        grouped[item["variant_id"]] = grouped.get(item["variant_id"], 0) + item["quantity"]
    return grouped

def fresh_preflight(shop, queue):
    grouped = aggregate(queue["items"])
    before = {}
    locations = {item['location_id'] for item in queue['items']}
    if locations != {LOCATION_ID}:
        stop('Queued losses do not share the configured location.')
    for variant_id, quantity in grouped.items():
        current = base.variant(shop, variant_id)
        if not current or current["product"]["status"] != "ACTIVE":
            stop("A queued variant is unavailable or inactive.", variant_id=variant_id)
        if current['id'] != variant_id:
            stop('Variant read identity mismatch.')
        for item in queue['items']:
            if item['variant_id'] == variant_id and base.fish_identity(current['product']['title'], current.get('title', ''), item['tank']) != base.norm(item['fish']):
                stop('Queued fish identity now conflicts with the variant.', record_id=item['record_id'])
        level = next(
            (item for item in complete_connection(current["inventoryItem"]["inventoryLevels"])
             if item["location"]["id"] == next(x["location_id"] for x in queue["items"] if x["variant_id"] == variant_id)),
            None,
        )
        if not level or base.quantities(level).get("available", 0) < quantity:
            stop("Insufficient inventory at batch close.", variant_id=variant_id, required=quantity)
        before[variant_id] = {
            "variant": current,
            "level": level,
            "quantity": quantity,
            "values": base.quantities(level),
        }
    if len(locations) != 1:
        stop("Queued losses span multiple Shopify locations.")
    return before, next(iter(locations))

def validate_recovery(queue):
    recovery = queue.get('recovery', {})
    grouped = aggregate(queue['items'])
    before = recovery.get('before')
    if not isinstance(before, dict) or set(before) != set(grouped) or recovery.get('order_attempted') is not True:
        stop('Invalid frozen inventory baseline; manual reconciliation is required.')
    for variant_id, snapshot in before.items():
        if not isinstance(snapshot, dict) or snapshot.get('location_id') != LOCATION_ID:
            stop('Invalid frozen inventory location.')
        for field in ['available', 'inventory_quantity', 'quantity']:
            if not isinstance(snapshot.get(field), int) or isinstance(snapshot[field], bool):
                stop('Invalid frozen inventory quantity.')
        if snapshot['quantity'] != grouped[variant_id] or snapshot['available'] < snapshot['quantity']:
            stop('Frozen inventory quantity conflicts with the order.')

def order_note(queue):
    lines = ["NTA daily livestock death batch {}.".format(queue["batch_date"])]
    for index, item in enumerate(queue["items"], 1):
        lines.append(
            "{}. {} × {}; tank {}; cause {}; source {}; evidence {}.".format(
                index, item["quantity"], item["fish"], item["tank"], item["cause"],
                item["source_ref"], item["evidence"],
            )
        )
    return "\n".join(lines)

def authorize_live_writes(shop):
    if os.getenv(LIVE_WRITE_GATE) != 'true':
        stop('The scheduled death-batch live write gate is not enabled.', gate=LIVE_WRITE_GATE)
    scopes = {item['handle'] for item in shop.gql(base.CAPABILITY_QUERY, {})['currentAppInstallation']['accessScopes']}
    required = {'read_orders', 'write_orders', 'read_inventory',
                'read_merchant_managed_fulfillment_orders', 'write_merchant_managed_fulfillment_orders'}
    if not required <= scopes:
        stop('Required Shopify capabilities are missing.', missing_scopes=sorted(required - scopes))
    shop.write_authorized = True


def fulfill_remaining(shop, order_id, expected, location_id):
    state = shop.gql(base.FULFILLMENT_STATE_QUERY, {"id": order_id})["order"]
    if not state:
        stop("The created order could not be read before fulfilment.")
    if state["displayFulfillmentStatus"] == "FULFILLED":
        return {"status": "ALREADY_FULFILLED", "fulfillment_id": None}
    groups = []
    remaining = {}
    for fulfillment_order in complete_connection(state['fulfillmentOrders']):
        if fulfillment_order.get('assignedLocation', {}).get('location', {}).get('id') != location_id:
            stop('Fulfilment routing differs from the verified loss location.')
        if fulfillment_order.get('status') not in {'OPEN', 'IN_PROGRESS'}:
            stop('Fulfilment order is not in a supported executable state.')
        entries = complete_connection(fulfillment_order['lineItems'])
        for line in entries:
            quantity = line.get('remainingQuantity')
            variant_id = (line.get('lineItem', {}).get('variant') or {}).get('id')
            if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0 or not variant_id:
                stop('Invalid exact fulfilment line.')
            if quantity:
                remaining[variant_id] = remaining.get(variant_id, 0) + quantity
        lines = [
            {"id": line["id"], "quantity": line["remainingQuantity"]}
            for line in entries
            if line["remainingQuantity"] > 0
        ]
        if lines:
            groups.append({
                "fulfillmentOrderId": fulfillment_order["id"],
                "fulfillmentOrderLineItems": lines,
            })
    if not groups:
        stop("No fulfillable line items were returned for the created order.")
    if remaining != expected:
        stop('Fulfilment quantities do not match the frozen loss order.')
    result = shop.gql(base.CREATE_FULFILLMENT_MUTATION, {
        "fulfillment": {
            "lineItemsByFulfillmentOrder": groups,
            "notifyCustomer": False,
        }
    })["fulfillmentCreate"]
    if result["userErrors"]:
        raise RuntimeError('fulfillment_rejected')
    fulfillment = result.get("fulfillment") or {}
    if not fulfillment.get("id"):
        raise RuntimeError('fulfillment_identity_missing')
    return {"status": "FULFILLED", "fulfillment_id": fulfillment["id"]}

def zero_money(value):
    try:
        amount = Decimal(value['shopMoney']['amount'])
        return amount.is_finite() and amount == 0 and value['shopMoney']['currencyCode'] == 'AUD'
    except (KeyError, TypeError, InvalidOperation):
        return False


def audit_order(shop, identity, queue):
    order = shop.gql(base.READ_ORDER_QUERY, {'id': identity['id']}).get('order')
    if not order or order.get('id') != identity['id']:
        stop('The exact saved order could not be verified.', order=identity.get('name'))
    lines = complete_connection(order.get('lineItems'))
    actual = {}
    valid_lines = True
    for line in lines:
        variant_id = (line.get('variant') or {}).get('id')
        quantity = line.get('quantity')
        if not variant_id or not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            valid_lines = False
            continue
        actual[variant_id] = actual.get(variant_id, 0) + quantity
    tags = set(order.get('tags') or [])
    note = order.get('note') or ''
    checks = {
        'zero_aud_total': zero_money(order.get('currentTotalPriceSet')),
        'zero_outstanding': zero_money(order.get('totalOutstandingSet')),
        'discount_code': base.DISCOUNT_CODE in (order.get('discountCodes') or []),
        'paid': order.get('displayFinancialStatus') == 'PAID',
        'customer': (order.get('customer') or {}).get('id') == CUSTOMER_ID,
        'base_tags': {'NTA Loss', 'Death', batch_tag(queue['batch_date'])} <= tags,
        'all_references': all(item['reference_tag'] in tags and item['source_ref'] in note for item in queue['items']),
        'exact_lines': valid_lines and actual == aggregate(queue['items']),
        'not_cancelled': 'cancelledAt' in order and order['cancelledAt'] is None,
    }
    return order, checks


def audit_inventory(shop, before):
    checks, inventory = {}, []
    for variant_id, snapshot in before.items():
        current = base.variant(shop, variant_id)
        if not current or current['id'] != variant_id:
            stop('Affected inventory identity could not be verified.')
        level = next((entry for entry in complete_connection(current['inventoryItem']['inventoryLevels'])
                      if entry['location']['id'] == snapshot['location_id']), None)
        if not level:
            stop('Affected inventory location could not be verified.')
        values = base.quantities(level)
        ok = values.get('available') == snapshot['available'] - snapshot['quantity'] and current['inventoryQuantity'] == snapshot['inventory_quantity'] - snapshot['quantity']
        checks['inventory_' + variant_id.rsplit('/', 1)[-1]] = ok
        inventory.append({'variant_id': variant_id, 'quantity': snapshot['quantity'], 'before_available': snapshot['available'],
                          'after_available': values.get('available'), 'before_inventory_quantity': snapshot['inventory_quantity'],
                          'after_inventory_quantity': current['inventoryQuantity'], 'verified': ok})
    return checks, inventory


def mutation_variables(queue):
    grouped = aggregate(queue['items'])
    if len(grouped) > 250:
        stop('Batch exceeds the supported order audit size.')
    return {
        'order': {
            'customer': {'toAssociate': {'id': CUSTOMER_ID}},
            'lineItems': [{'variantId': variant_id, 'quantity': grouped[variant_id]} for variant_id in sorted(grouped)],
            'discountCode': {'itemPercentageDiscountCode': {'code': base.DISCOUNT_CODE, 'percentage': 100}},
            'financialStatus': 'PAID', 'tags': ['NTA Loss', 'Death', batch_tag(queue['batch_date'])] + [item['reference_tag'] for item in queue['items']],
            'note': order_note(queue), 'sourceName': 'NTA Losses',
        },
        'options': {'inventoryBehaviour': 'DECREMENT_OBEYING_POLICY', 'sendReceipt': False, 'sendFulfillmentReceipt': False},
    }


def failure(queue, status, message, execute, **details):
    if execute:
        queue['status'] = 'RECONCILIATION_REQUIRED'
        queue['last_result'] = {'status': status, 'message': message, **details}
        save_queue(queue)
    emit({'status': status, 'batch_date': queue['batch_date'], 'order': queue.get('order'),
          'message': message, **details}, 3)


def close(shop, args):
    date = args.date or datetime.now(SYDNEY).date().isoformat()
    tag = batch_tag(date)
    # Execute holds the lock across plan construction, mutations and all audits.
    # Dry-run only reads; it does not create a directory/lock or reconcile state.
    try:
        with QueueLock() if args.execute else nullcontext():
            queue = load_queue(date)
            if not queue['items']:
                emit({'status': 'NO_BATCH', 'batch_date': date, 'write_occurred': False})
            customer = one_customer(shop)
            existing = completed_with_tag(shop, tag)
            recovery = queue.get('recovery', {})
            if existing and queue.get('order', {}).get('id') not in {None, existing['id']}:
                stop('Existing daily order conflicts with the saved order identity.')
            if not existing and (queue['status'] != 'OPEN' or queue.get('order') or recovery):
                failure(queue, 'INDETERMINATE', 'A prior mutation may have occurred; locate its exact order before reconciliation. No new order was attempted.', args.execute)
            if existing:
                queue['order'] = {'id': existing['id'], 'name': existing['name']}
                order, checks = audit_order(shop, existing, queue)
                if not all(checks.values()):
                    failure(queue, 'FAILED', 'Existing order does not match the frozen batch contract.', args.execute, checks=checks)
                if not args.execute:
                    emit({'status': 'READY_TO_RECONCILE', 'batch_date': date, 'order': existing, 'checks': checks, 'write_occurred': False})
                if queue['status'] == 'CLOSED' and order.get('displayFulfillmentStatus') == 'FULFILLED':
                    previous = queue.get('verification', {})
                    emit({'status': 'ALREADY_CLOSED', 'batch_date': date, 'order': existing, 'checks': checks,
                          'inventory_verified': False,
                          'inventory_verification': 'PREVIOUSLY_VERIFIED' if previous.get('checks') and all(previous['checks'].values()) else 'HISTORICAL_BASELINE_UNAVAILABLE'})
                # Existing fulfilled legacy orders have no durable pre-write snapshot.
                # Preserve their identity and report the historical audit limitation.
                if order.get('displayFulfillmentStatus') == 'FULFILLED' and not recovery.get('before'):
                    queue.update({'status': 'CLOSED', 'order': {'id': order['id'], 'name': order['name']},
                                  'verification': {'order_checks': checks, 'inventory': 'HISTORICAL_BASELINE_UNAVAILABLE'}})
                    save_queue(queue)
                    emit({'status': 'ALREADY_CLOSED', 'batch_date': date, 'order': queue['order'], 'checks': checks,
                          'inventory_verified': False, 'inventory_verification': 'HISTORICAL_BASELINE_UNAVAILABLE'})
                if not recovery.get('before'):
                    failure(queue, 'INDETERMINATE_EXISTING', 'Existing unfulfilled order has no durable inventory baseline; manual reconciliation is required.', True)
                save_queue(queue)
            else:
                before, location_id = fresh_preflight(shop, queue)
                variables = mutation_variables(queue)
                if not args.execute:
                    emit({'status': 'READY_TO_CLOSE', 'batch_date': date, 'items': queue['items'],
                          'line_items': variables['order']['lineItems'], 'write_occurred': False})
                authorize_live_writes(shop)
                # Recheck by daily tag after reads, before recording mutation intent.
                if completed_with_tag(shop, tag):
                    stop('An order appeared during preflight; rerun reconciliation without creating another.')
                recovery = {'before': {vid: {'available': entry['values']['available'],
                             'inventory_quantity': entry['variant']['inventoryQuantity'], 'quantity': entry['quantity'],
                             'location_id': location_id} for vid, entry in before.items()},
                            'customer_id': customer['id'], 'location_id': location_id, 'order_attempted': True,
                            'batch_digest': hashlib.sha256(json.dumps(queue['items'], sort_keys=True).encode()).hexdigest()}
                queue.update({'status': 'ORDER_CREATING', 'recovery': recovery})
                save_queue(queue)  # Crash after this point must never submit another order.
                try:
                    payload = shop.gql(base.CREATE_MUTATION, variables)['orderCreate']
                except Exception as error:
                    recovered = completed_with_tag(shop, tag)
                    if recovered:
                        queue['order'] = {'id': recovered['id'], 'name': recovered['name']}
                    failure(queue, 'INDETERMINATE_EXISTING' if recovered else 'INDETERMINATE',
                            'Order creation result is uncertain. Reconcile the existing order; do not retry creation.', True,
                            **base.bridge_failure_details(error))
                if payload.get('userErrors') or not (payload.get('order') or {}).get('id'):
                    failure(queue, 'FAILED', 'Shopify rejected creation or returned no order identity; review before any retry.', True)
                existing = payload['order']
                queue.update({'status': 'ORDER_CREATED', 'order': {'id': existing['id'], 'name': existing['name']}})
                save_queue(queue)
                # Audit by exact ID, independently of the mutation response.
                order, checks = audit_order(shop, existing, queue)
                if not all(checks.values()):
                    failure(queue, 'FAILED', 'Created order failed independent contract verification.', True, checks=checks)
            digest = hashlib.sha256(json.dumps(queue['items'], sort_keys=True).encode()).hexdigest()
            if recovery.get('batch_digest') != digest or recovery.get('customer_id') != CUSTOMER_ID or recovery.get('location_id') != LOCATION_ID or set(recovery.get('before', {})) != set(aggregate(queue['items'])):
                failure(queue, 'FAILED', 'Frozen recovery state conflicts with current records/configuration; manual reconciliation required.', True)
            validate_recovery(queue)
            fulfillment = {'status': 'ALREADY_FULFILLED'}
            if order.get('displayFulfillmentStatus') != 'FULFILLED':
                if recovery.get('fulfillment_attempted'):
                    refreshed = wait_for_fulfilled(shop, tag)
                    if not refreshed or refreshed.get('displayFulfillmentStatus') != 'FULFILLED':
                        failure(queue, 'INDETERMINATE_EXISTING', 'A previous fulfilment attempt is still unresolved. Inspect the existing order; no fulfilment mutation was repeated.', True, consistency='PENDING')
                else:
                    authorize_live_writes(shop)
                    recovery['fulfillment_attempted'] = True
                    queue['status'] = 'FULFILLING'
                    save_queue(queue)
                    try:
                        fulfillment = fulfill_remaining(shop, order['id'], aggregate(queue['items']), LOCATION_ID)
                    except Exception as error:
                        failure(queue, 'INDETERMINATE_EXISTING', 'Fulfilment result is uncertain. Inspect the existing order; do not blindly repeat fulfilment.', True,
                                **base.bridge_failure_details(error))
                    recovery['fulfillment_result'] = fulfillment
                    queue['status'] = 'VERIFYING'
                    save_queue(queue)
                    refreshed = wait_for_fulfilled(shop, tag)
                    if not refreshed or refreshed.get('displayFulfillmentStatus') != 'FULFILLED':
                        failure(queue, 'INDETERMINATE_EXISTING', 'Fulfilment projection did not converge within 45 seconds. Reconcile this order without repeating the mutation.', True, consistency='PENDING')
            order, checks = audit_order(shop, existing, queue)
            checks['fulfilled'] = order.get('displayFulfillmentStatus') == 'FULFILLED'
            inventory_checks, inventory = audit_inventory(shop, recovery['before'])
            checks.update(inventory_checks)
            if not all(checks.values()):
                failure(queue, 'FAILED', 'Post-write verification failed; order is preserved for reconciliation.', True, checks=checks, inventory=inventory)
            queue.update({'status': 'CLOSED', 'closed_at': datetime.now(SYDNEY).isoformat(),
                          'verification': {'checks': checks, 'inventory': inventory}, 'last_result': {'status': 'CLOSED_VERIFIED'}})
            save_queue(queue)
            confirmed = load_queue(date)
            if confirmed.get('verification') != queue['verification'] or confirmed['status'] != 'CLOSED':
                stop('Closed queue read-back mismatch.', order=queue['order']['name'])
            emit({'status': 'CLOSED_VERIFIED', 'batch_date': date, 'order': queue['order'], 'checks': checks,
                  'inventory': inventory, 'inventory_verified': True, 'fulfillment': fulfillment, 'records': queue['items']})
    except Exception as error:
        if 'queue' in locals() and (queue.get('recovery') or queue.get('order')):
            # A failed read does not invalidate previously persisted successful proof.
            # Preserve CLOSED evidence so later sales cannot turn a read outage into
            # an impossible replay of the original inventory-baseline audit.
            failure(queue, 'FAILED', 'A bridge or verification read failed. Inspect the saved order and recovery state before retrying.',
                    args.execute and queue['status'] != 'CLOSED',
                    **base.bridge_failure_details(error))
        stop('Preflight could not complete; verify configuration, queue, and bridge health.',
             batch_date=date, **base.bridge_failure_details(error))
    finally:
        shop.write_authorized = False


def parser():
    root = argparse.ArgumentParser()
    root.add_argument('--config')
    root.add_argument('--env-file')
    sub = root.add_subparsers(dest='command', required=True)
    intake = sub.add_parser('add')
    for name in ['variant-id', 'quantity', 'tank', 'fish', 'source-ref', 'confidence', 'evidence']:
        intake.add_argument('--' + name, required=True, type=int if name == 'quantity' else str)
    intake.add_argument('--cause', default='Unknown')
    intake.add_argument('--location-id')
    intake.add_argument('--date')
    intake.add_argument('--item-key')
    intake.add_argument('--prior-manual-deduction', action='store_true')
    amendment = sub.add_parser('amend')
    select = amendment.add_mutually_exclusive_group(required=True)
    select.add_argument('--source-ref')
    select.add_argument('--record-id')
    amendment.add_argument('--quantity', required=True, type=int)
    amendment.add_argument('--expected-quantity', required=True, type=int)
    amendment.add_argument('--amendment-id', required=True)
    for command in [intake, amendment]:
        command.add_argument('--channel-id', required=True)
        command.add_argument('--sender-id', required=True)
        command.add_argument('--execute', action='store_true')
    closing = sub.add_parser('close')
    closing.add_argument('--date')
    closing.add_argument('--execute', action='store_true')
    return root


def configure(config):
    global STATE_DIR, CUSTOMER_ID, LOCATION_ID, CHANNEL_ID, AUTHORIZED_SENDERS, SYDNEY, CUTOFF_HOUR, CUTOFF_MINUTE
    STATE_DIR = Path(config['state_dir'])
    CUSTOMER_ID = config['customer_id']
    LOCATION_ID = config['location_id']
    CHANNEL_ID = config['discord_channel_id']
    AUTHORIZED_SENDERS = set(config['authorized_sender_ids'])
    SYDNEY = ZoneInfo(config['timezone'])
    CUTOFF_HOUR, CUTOFF_MINUTE = map(int, config['cutoff'].split(':'))
    base.DEFAULT_SESSION_BRIDGE = config['session_bridge']


def main():
    from configuration import load_config
    args = parser().parse_args()
    try:
        config = load_config(args.config)
        configure(config)
        # Empty close has no authentication/network/model dependency.
        if args.command == 'close':
            date = args.date or datetime.now(SYDNEY).date().isoformat()
            if not load_queue(date)['items']:
                emit({'status': 'NO_BATCH', 'batch_date': date, 'write_occurred': False})
        shop = base.Shopify(base.load_env(args.env_file or config['env_file']))
        {'add': add, 'amend': amend, 'close': close}[args.command](shop, args)
    except SystemExit:
        raise
    except Exception:
        stop('Operation failed; inspect validated configuration and bridge health. No raw exception or secret was logged.')


if __name__ == '__main__':
    main()
