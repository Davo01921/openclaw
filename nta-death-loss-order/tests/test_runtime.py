"""Offline contract tests: fake Shopify only; every queue is temporary."""
import contextlib
import copy
import io
import json
import multiprocessing
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import daily_batch as daily
import death_loss_order as base
from configuration import load_config
from loss_plan import build_loss_plan

VID = 'gid://shopify/ProductVariant/111'
LOC = 'gid://shopify/Location/222'
CID = 'gid://shopify/Customer/333'
DATE = '2026-01-01'
CHANNEL = '123456789'
SENDER = '987654321'
SCOPES = {'read_orders', 'write_orders', 'read_inventory', 'read_merchant_managed_fulfillment_orders', 'write_merchant_managed_fulfillment_orders'}


def connection(nodes):
    return {'nodes': nodes, 'pageInfo': {'hasNextPage': False}}


def record(source='discord-fixture-111', quantity=1, variant_id=VID):
    return {'source_ref': source, 'reference_tag': base.reference_tag(source), 'variant_id': variant_id,
            'location_id': LOC, 'quantity': quantity, 'tank': 'TT1', 'fish': 'Synthetic Guppy',
            'cause': 'Unknown', 'evidence': 'Synthetic staff report', 'product_title': 'Synthetic Guppy'}


def variant(available=10, inventory=10, title='Synthetic Guppy', vid=VID, committed=0):
    return {'id': vid, 'title': 'Default Title', 'sku': '', 'product': {'id': 'gid://shopify/Product/777', 'title': title, 'status': 'ACTIVE'},
            'inventoryQuantity': inventory, 'inventoryItem': {'inventoryLevels': connection([
                {'location': {'id': LOC, 'name': 'Synthetic location'}, 'quantities': [
                    {'name': 'available', 'quantity': available}, {'name': 'on_hand', 'quantity': available + committed},
                    {'name': 'committed', 'quantity': committed}]}])}}


def capture(fn):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        try:
            fn()
        except SystemExit:
            pass
    return json.loads(output.getvalue())


class SimulatedCrash(BaseException):
    pass


class FakeShop:
    def __init__(self):
        self.variants = {VID: variant()}
        self.orders = []
        self.scopes = set(SCOPES)
        self.create_calls = self.fulfillment_calls = self.read_calls = 0
        self.write_authorized = False
        self.read_timeout = 35
        self.create_error = None
        self.fulfillment_error = False
        self.projection_delay = 0
        self.pending_polls = None
        self.inventory_error = False
        self.product_list = []
        self.on_create = None

    def gql(self, query, variables):
        self.read_calls += 1
        if query == base.PRODUCTS_QUERY:
            return {'products': connection(copy.deepcopy(self.product_list))}
        if query == base.VARIANT_QUERY:
            return {'productVariant': copy.deepcopy(self.variants.get(variables['id']))}
        if query == base.CUSTOMERS_QUERY:
            return {'customers': connection([{'id': CID, 'displayName': 'NTA Losses'}])}
        if query == base.CAPABILITY_QUERY:
            return {'currentAppInstallation': {'accessScopes': [{'handle': s} for s in self.scopes]}}
        if query == base.ORDERS_QUERY:
            tag = variables['query'].split()[0].removeprefix('tag:')
            if self.pending_polls is not None:
                if self.pending_polls <= 0:
                    self.orders[-1]['displayFulfillmentStatus'] = 'FULFILLED'
                else:
                    self.pending_polls -= 1
            return {'orders': connection(copy.deepcopy([o for o in self.orders if tag in o['tags']]))}
        if query == base.READ_ORDER_QUERY:
            return {'order': copy.deepcopy(next((o for o in self.orders if o['id'] == variables['id']), None))}
        if query == base.CREATE_MUTATION:
            assert self.write_authorized, 'fake mutation was not authorized'
            self.create_calls += 1
            if self.create_error == 'no_order':
                raise RuntimeError('synthetic_transport_timeout')
            incoming = variables['order']
            o = {'id': 'gid://shopify/Order/444', 'name': '#SYNTHETIC', 'customer': {'id': CID},
                 'displayFinancialStatus': 'PAID', 'displayFulfillmentStatus': 'UNFULFILLED',
                 'currentTotalPriceSet': {'shopMoney': {'amount': '0.00', 'currencyCode': 'AUD'}},
                 'totalOutstandingSet': {'shopMoney': {'amount': '0.00', 'currencyCode': 'AUD'}},
                 'discountCodes': ['Ntalosses'], 'cancelledAt': None, 'tags': incoming['tags'], 'note': incoming['note'],
                 'lineItems': connection([{'quantity': line['quantity'], 'variant': {'id': line['variantId']}} for line in incoming['lineItems']])}
            self.orders.append(o)
            for line in incoming['lineItems']:
                v = self.variants[line['variantId']]
                amount = line['quantity'] - (1 if self.inventory_error else 0)
                v['inventoryQuantity'] -= amount
                for value in v['inventoryItem']['inventoryLevels']['nodes'][0]['quantities']:
                    if value['name'] in {'available', 'on_hand'}:
                        value['quantity'] -= amount
            if self.on_create:
                self.on_create()
            if self.create_error == 'crash':
                raise SimulatedCrash()
            if self.create_error == 'exists':
                raise RuntimeError('synthetic_transport_timeout')
            return {'orderCreate': {'order': copy.deepcopy(o), 'userErrors': []}}
        if query == base.FULFILLMENT_STATE_QUERY:
            o = self.orders[-1]
            return {'order': {'id': o['id'], 'displayFulfillmentStatus': o['displayFulfillmentStatus'],
                    'fulfillmentOrders': connection([{'id': 'gid://shopify/FulfillmentOrder/555', 'status': 'OPEN',
                     'assignedLocation': {'location': {'id': LOC}}, 'lineItems': connection([
                      {'id': 'gid://shopify/FulfillmentOrderLineItem/' + str(i + 1), 'remainingQuantity': line['quantity'],
                       'lineItem': {'variant': line['variant']}} for i, line in enumerate(o['lineItems']['nodes'])])}])}}
        if query == base.CREATE_FULFILLMENT_MUTATION:
            assert self.write_authorized
            self.fulfillment_calls += 1
            if self.fulfillment_error:
                raise RuntimeError('synthetic_fulfillment_timeout')
            self.pending_polls = self.projection_delay
            return {'fulfillmentCreate': {'fulfillment': {'id': 'gid://shopify/Fulfillment/666'}, 'userErrors': []}}
        raise AssertionError('Unexpected fake operation')


def lock_worker(directory, index):
    daily.STATE_DIR = Path(directory)
    with daily.QueueLock():
        q = daily.load_queue(DATE)
        q['items'].append(record(source=f'discord-concurrent-{index}'))
        daily.save_queue(q)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        daily.STATE_DIR = Path(self.temp.name)
        daily.CUSTOMER_ID = CID
        daily.LOCATION_ID = LOC
        daily.CHANNEL_ID = CHANNEL
        daily.AUTHORIZED_SENDERS = {SENDER}
        daily.CUTOFF_HOUR, daily.CUTOFF_MINUTE = 18, 0
        self.shop = FakeShop()
        self.gate = patch.dict(os.environ, {daily.LIVE_WRITE_GATE: 'true'})
        self.gate.start()
        self.addCleanup(self.gate.stop)
        self.clock = patch.object(daily.time_module, 'sleep', lambda _: None)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def seed(self, items=None):
        daily.save_queue({'batch_date': DATE, 'status': 'OPEN', 'items': items or [record()]})

    def add_args(self, **changes):
        return SimpleNamespace(**({'variant_id': VID, 'quantity': 1, 'tank': 'TT1', 'fish': 'Synthetic Guppy',
            'source_ref': 'discord-fixture-111', 'confidence': 'HIGH', 'evidence': 'Synthetic report', 'cause': 'Unknown',
            'location_id': None, 'date': DATE, 'prior_manual_deduction': False, 'execute': True,
            'channel_id': CHANNEL, 'sender_id': SENDER, 'item_key': None} | changes))

    def close(self, execute=True):
        return capture(lambda: daily.close(self.shop, SimpleNamespace(date=DATE, execute=execute)))

    def product(self, title, vid=VID):
        return {'id': 'gid://shopify/Product/' + vid.rsplit('/', 1)[-1], 'title': title, 'status': 'ACTIVE',
                'variants': connection([{'id': vid, 'title': 'Default Title', 'sku': '', 'inventoryQuantity': 10,
                                        'inventoryItem': {'inventoryLevels': connection([])}}])}

    def test_stale_tank_cannot_identify_another_fish(self):
        self.shop.product_list = [self.product('TT21 - Betta')]
        result = capture(lambda: base.resolve(self.shop, 'Black Emperor Tetra', 'TT21'))
        self.assertEqual(result['status'], 'REVIEW_REQUIRED')
        self.assertIsNone(result['confidence'])
        self.assertIn('FISH_MISMATCH', result['reasons'])
        self.assertLess(result['candidates'][0]['score'], 100)

    def test_exact_fish_overrides_stale_tank_context(self):
        self.shop.product_list = [self.product('TT21 - Betta'), self.product('Black Emperor Tetra', 'gid://shopify/ProductVariant/112')]
        result = capture(lambda: base.resolve(self.shop, 'black-emperor tetra', 'TT21'))
        self.assertEqual(result['status'], 'RESOLVED')
        self.assertEqual(result['resolved_variant']['variant_id'], 'gid://shopify/ProductVariant/112')
        self.assertIn('STALE_OR_UNVERIFIED_TANK_CONTEXT', result['reasons'])

    def test_ambiguous_fish_requires_review_even_with_unique_tank(self):
        self.shop.product_list = [self.product('TT21 - Betta'), self.product('Betta', 'gid://shopify/ProductVariant/112')]
        self.assertEqual(capture(lambda: base.resolve(self.shop, 'Betta', 'TT21'))['status'], 'REVIEW_REQUIRED')

    def test_duplicate_delivery_across_dates(self):
        self.assertEqual(capture(lambda: daily.add(self.shop, self.add_args()))['status'], 'QUEUED_VERIFIED')
        self.assertEqual(capture(lambda: daily.add(self.shop, self.add_args(date='2026-01-02')))['status'], 'ALREADY_QUEUED')
        self.assertFalse(daily.queue_path('2026-01-02').exists())

    def test_duplicate_conflicting_quantity_requires_amend(self):
        capture(lambda: daily.add(self.shop, self.add_args()))
        self.assertEqual(capture(lambda: daily.add(self.shop, self.add_args(quantity=2)))['status'], 'BLOCKED')
        self.assertEqual(daily.load_queue(DATE)['items'][0]['quantity'], 1)

    def test_multi_item_same_tank_has_distinct_keys(self):
        a = capture(lambda: daily.add(self.shop, self.add_args(item_key='item1')))
        b = capture(lambda: daily.add(self.shop, self.add_args(item_key='item2')))
        self.assertNotEqual(a['item']['record_id'], b['item']['record_id'])
        self.assertNotEqual(a['item']['reference_tag'], b['item']['reference_tag'])
        self.assertEqual(a['item']['source_event_ref'], b['item']['source_event_ref'])

    def test_amend_dry_run_and_retry(self):
        self.seed()
        args = SimpleNamespace(source_ref='discord-fixture-111', record_id=None, quantity=2, expected_quantity=1,
                               amendment_id='discord-amend-222', execute=False, channel_id=CHANNEL, sender_id=SENDER)
        original = daily.queue_path(DATE).read_bytes()
        self.assertEqual(capture(lambda: daily.amend(self.shop, args))['status'], 'READY')
        self.assertEqual(original, daily.queue_path(DATE).read_bytes())
        args.execute = True
        result = capture(lambda: daily.amend(self.shop, args))
        self.assertEqual(result['status'], 'AMENDED_VERIFIED')
        self.assertEqual(result['item']['source_ref'], args.source_ref)
        self.assertEqual(capture(lambda: daily.amend(self.shop, args))['status'], 'ALREADY_AMENDED')
        self.assertEqual(len(daily.load_queue(DATE)['items'][0]['history']), 1)
        args.quantity = 3
        self.assertEqual(capture(lambda: daily.amend(self.shop, args))['status'], 'BLOCKED')

    def test_insufficient_stock_uses_aggregate_queue_demand(self):
        self.shop.variants[VID] = variant(available=1, inventory=1)
        capture(lambda: daily.add(self.shop, self.add_args(item_key='item1')))
        self.assertEqual(capture(lambda: daily.add(self.shop, self.add_args(item_key='item2')))['status'], 'BLOCKED')
        self.assertEqual(len(daily.load_queue(DATE)['items']), 1)

    def test_committed_stock_is_not_available(self):
        self.shop.variants[VID] = variant(available=0, inventory=100, committed=100)
        self.assertEqual(capture(lambda: daily.add(self.shop, self.add_args()))['status'], 'BLOCKED')
        self.assertEqual(self.shop.create_calls, 0)

    def test_empty_batch_has_no_network_or_queue_writes(self):
        self.assertEqual(self.close(execute=False)['status'], 'NO_BATCH')
        self.assertEqual(self.shop.read_calls, 0)
        self.assertEqual(list(daily.STATE_DIR.iterdir()), [])

    def test_close_dry_run_is_byte_exact(self):
        self.seed()
        before = daily.queue_path(DATE).read_bytes()
        self.assertEqual(self.close(False)['status'], 'READY_TO_CLOSE')
        self.assertEqual(before, daily.queue_path(DATE).read_bytes())
        self.assertFalse((daily.STATE_DIR / '.lock').exists())
        self.assertEqual(self.shop.create_calls, 0)

    def test_delayed_fulfillment_then_verified_close(self):
        self.seed()
        self.shop.projection_delay = 3
        result = self.close()
        self.assertEqual(result['status'], 'CLOSED_VERIFIED')
        self.assertTrue(all(result['checks'].values()))
        self.assertEqual(self.shop.create_calls, 1)
        self.assertEqual(self.shop.fulfillment_calls, 1)
        self.assertFalse(self.shop.write_authorized)

    def test_failed_inventory_does_not_close(self):
        self.seed(items=[record(quantity=2)])
        self.shop.inventory_error = True
        self.assertEqual(self.close()['status'], 'FAILED')
        self.assertEqual(daily.load_queue(DATE)['status'], 'RECONCILIATION_REQUIRED')
        self.assertEqual(self.close()['status'], 'FAILED')
        self.assertEqual(self.shop.create_calls, 1)

    def test_uncertain_creation_recovers_exact_existing_order(self):
        self.seed()
        self.shop.create_error = 'exists'
        self.assertEqual(self.close()['status'], 'INDETERMINATE_EXISTING')
        self.assertEqual(self.close()['status'], 'CLOSED_VERIFIED')
        self.assertEqual(self.shop.create_calls, 1)
        self.assertEqual(self.shop.fulfillment_calls, 1)

    def test_unknown_creation_without_order_never_retries(self):
        self.seed()
        self.shop.create_error = 'no_order'
        self.assertEqual(self.close()['status'], 'INDETERMINATE')
        self.assertEqual(self.close()['status'], 'INDETERMINATE')
        self.assertEqual(self.shop.create_calls, 1)

    def test_process_crash_leaves_mutation_intent_and_recovers(self):
        self.seed()
        self.shop.create_error = 'crash'
        with self.assertRaises(SimulatedCrash):
            self.close()
        self.assertEqual(daily.load_queue(DATE)['status'], 'ORDER_CREATING')
        self.assertEqual(self.close()['status'], 'CLOSED_VERIFIED')
        self.assertEqual(self.shop.create_calls, 1)

    def test_uncertain_fulfillment_is_not_repeated(self):
        self.seed()
        self.shop.fulfillment_error = True
        self.assertEqual(self.close()['status'], 'INDETERMINATE_EXISTING')
        with patch.object(daily, 'wait_for_fulfilled', lambda *a, **k: None):
            self.assertEqual(self.close()['status'], 'INDETERMINATE_EXISTING')
        self.assertEqual(self.shop.fulfillment_calls, 1)

    def test_existing_order_adoption_and_no_duplicate(self):
        self.seed()
        self.assertEqual(self.close()['status'], 'CLOSED_VERIFIED')
        # Historical sales after closure must not invalidate previously verified deltas.
        self.shop.variants[VID]['inventoryQuantity'] -= 1
        self.assertEqual(self.close()['status'], 'ALREADY_CLOSED')
        self.assertEqual(self.shop.create_calls, 1)

    def test_existing_nonzero_order_is_rejected(self):
        self.seed()
        self.close()
        self.shop.orders[0]['currentTotalPriceSet']['shopMoney']['amount'] = '1.00'
        self.assertEqual(self.close()['status'], 'FAILED')

    def test_exact_lines_discount_and_balance_are_independent_checks(self):
        for field in ['discountCodes', 'totalOutstandingSet', 'lineItems']:
            with self.subTest(field=field):
                self.shop = FakeShop()
                self.seed()
                self.close()
                if field == 'discountCodes':
                    self.shop.orders[0][field] = []
                elif field == 'totalOutstandingSet':
                    self.shop.orders[0][field]['shopMoney']['amount'] = '1.00'
                else:
                    self.shop.orders[0][field]['nodes'][0]['quantity'] = 2
                self.assertEqual(self.close()['status'], 'FAILED')
                self.assertEqual(self.shop.create_calls, 1)

    def test_legacy_queue_adopts_fulfilled_order_without_inventing_baseline(self):
        self.seed()
        self.close()
        legacy = {'batch_date': DATE, 'status': 'OPEN', 'items': [record()]}
        daily.queue_path(DATE).write_text(json.dumps(legacy))
        result = self.close()
        self.assertEqual(result['status'], 'ALREADY_CLOSED')
        self.assertFalse(result['inventory_verified'])
        self.assertEqual(result['inventory_verification'], 'HISTORICAL_BASELINE_UNAVAILABLE')
        self.assertEqual(self.shop.create_calls, 1)

    def test_missing_gate_and_scopes_fail_before_intent(self):
        self.seed()
        with patch.dict(os.environ, {daily.LIVE_WRITE_GATE: 'false'}):
            self.assertEqual(self.close()['status'], 'BLOCKED')
        self.shop.scopes.clear()
        self.assertEqual(self.close()['status'], 'BLOCKED')
        self.assertEqual(daily.load_queue(DATE)['status'], 'OPEN')
        self.assertEqual(self.shop.create_calls, 0)

    def test_sydney_cutoff_and_dst_boundaries(self):
        cases = [('2026-10-03T07:59:59+00:00', '2026-10-03'), ('2026-10-03T08:00:00+00:00', '2026-10-04'),
                 ('2026-10-04T06:59:59+00:00', '2026-10-04'), ('2026-10-04T07:00:00+00:00', '2026-10-05'),
                 ('2026-04-05T07:59:59+00:00', '2026-04-05'), ('2026-04-05T08:00:00+00:00', '2026-04-06')]
        for timestamp, expected in cases:
            self.assertEqual(daily.logical_date(datetime.fromisoformat(timestamp)), expected)

    def test_concurrent_queue_writes_are_serialized(self):
        context = multiprocessing.get_context('spawn')
        workers = [context.Process(target=lock_worker, args=(self.temp.name, i)) for i in range(6)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            self.assertEqual(worker.exitcode, 0)
        queue = daily.load_queue(DATE)
        self.assertEqual(len(queue['items']), 6)
        self.assertEqual(len({i['source_ref'] for i in queue['items']}), 6)

    def test_intake_waits_for_close_lock_and_cannot_be_lost(self):
        self.seed()
        original_lock = daily.QueueLock
        class IntakeBeforeAcquire(original_lock):
            def __enter__(inner):
                with original_lock():
                    queue = daily.load_queue(DATE)
                    queue['items'].append(record(source='discord-second-222', quantity=2))
                    daily.save_queue(queue)
                return super().__enter__()
        with patch.object(daily, 'QueueLock', IntakeBeforeAcquire):
            result = self.close()
        self.assertEqual(result['status'], 'CLOSED_VERIFIED')
        self.assertEqual(self.shop.orders[0]['lineItems']['nodes'][0]['quantity'], 3)
        self.assertEqual(len(daily.load_queue(DATE)['items']), 2)

    def test_invalid_dates_and_corrupt_queue_fail_closed(self):
        self.assertEqual(capture(lambda: daily.load_queue('2026-02-30'))['status'], 'BLOCKED')
        daily.queue_path(DATE).write_text('{invalid')
        before = daily.queue_path(DATE).read_bytes()
        self.assertEqual(self.close()['status'], 'BLOCKED')
        self.assertEqual(before, daily.queue_path(DATE).read_bytes())

    def test_unauthorized_source_and_boolean_quantities_rejected(self):
        self.assertEqual(capture(lambda: daily.add(self.shop, self.add_args(sender_id='111111111')))['status'], 'BLOCKED')
        self.assertEqual(capture(lambda: daily.add(self.shop, self.add_args(quantity=True)))['status'], 'BLOCKED')

    def test_unbounded_or_incomplete_search_never_authorizes(self):
        self.shop.product_list = [self.product('Synthetic Guppy')]
        self.shop.product_list[0]['variants']['pageInfo']['hasNextPage'] = True
        self.assertEqual(capture(lambda: base.resolve(self.shop, 'Synthetic Guppy', 'TT1'))['status'], 'REVIEW_REQUIRED')

    def test_mixed_locations_for_one_variant_are_rejected(self):
        a, b = record(), record(source='discord-other-222')
        b['location_id'] = 'gid://shopify/Location/999'
        self.seed([a, b])
        self.assertEqual(self.close()['status'], 'BLOCKED')
        self.assertEqual(self.shop.create_calls, 0)

    def test_no_individual_loss_order_entrypoint(self):
        self.assertEqual(capture(lambda: base.create(self.shop, SimpleNamespace()))['status'], 'BLOCKED')
        self.assertEqual(self.shop.create_calls, 0)

    def test_config_requires_verified_values(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'configuration_required'):
                load_config()
        example = Path(__file__).parents[1] / 'config.example.json'
        with self.assertRaises(ValueError):
            load_config(example)
        valid = json.loads(example.read_text())
        valid.update(state_dir=self.temp.name, env_file='/tmp/synthetic.env', session_bridge='/tmp/synthetic.mjs',
                     customer_id=CID, location_id=LOC, discord_channel_id=CHANNEL, authorized_sender_ids=[SENDER])
        path = Path(self.temp.name) / 'config-synthetic.txt'
        path.write_text(json.dumps(valid))
        self.assertEqual(load_config(path)['location_id'], LOC)

    def test_planner_rejects_malformed_types_and_non_exact_variants(self):
        request = {'mode': 'dry_run', 'source_event_id': 'discord-fixture-111',
                   'prior_loss_order_found': False, 'prior_manual_deduction_found': False,
                   'manual_reversal_verified': False,
                   'loss_items': [{'resolution_status': 'RESOLVED', 'shopify_variant_id': VID, 'quantity': 1}]}
        for malformed in [None, [], {'mode': []}]:
            self.assertEqual(build_loss_plan(malformed)['status'], 'REVIEW_REQUIRED')
        for changes in [{'quantity': True}, {'quantity': 101}, {'shopify_variant_id': '111'},
                        {'resolution_status': []}, {'identification_confidence': 'MEDIUM'}, {'evidence': [None]}]:
            bad = {**request, 'loss_items': [{**request['loss_items'][0], **changes}]}
            self.assertEqual(build_loss_plan(bad)['status'], 'REVIEW_REQUIRED')
        a = build_loss_plan(request)['order_plan']['idempotency_key']
        b = build_loss_plan({**request, 'loss_items': [{**request['loss_items'][0], 'quantity': 2}]})['order_plan']['idempotency_key']
        self.assertEqual(a, b)

    def test_repeated_amendment_after_later_amendment_does_not_revert(self):
        self.seed()
        args = SimpleNamespace(source_ref='discord-fixture-111', record_id=None, quantity=2, expected_quantity=1,
                               amendment_id='discord-amend-222', execute=True, channel_id=CHANNEL, sender_id=SENDER)
        capture(lambda: daily.amend(self.shop, args))
        later = SimpleNamespace(**(vars(args) | {'quantity': 3, 'expected_quantity': 2, 'amendment_id': 'discord-amend-333'}))
        capture(lambda: daily.amend(self.shop, later))
        result = capture(lambda: daily.amend(self.shop, args))
        self.assertEqual(result['status'], 'ALREADY_AMENDED')
        self.assertEqual(result['item']['quantity'], 3)

    def test_amend_closed_batch_and_insufficient_aggregate_stock(self):
        self.seed([record(), record(source='discord-other-222')])
        args = SimpleNamespace(source_ref='discord-fixture-111', record_id=None, quantity=3, expected_quantity=1,
                               amendment_id='discord-amend-222', execute=True, channel_id=CHANNEL, sender_id=SENDER)
        self.shop.variants[VID] = variant(available=3, inventory=3)
        self.assertEqual(capture(lambda: daily.amend(self.shop, args))['status'], 'BLOCKED')
        self.assertEqual(daily.load_queue(DATE)['items'][0]['quantity'], 1)
        self.close()
        args.quantity = 1
        self.assertEqual(capture(lambda: daily.amend(self.shop, args))['status'], 'BLOCKED')

    def test_fulfillment_backoff_has_a_bounded_deadline(self):
        class Clock:
            now = 0
            delays = []
            def monotonic(inner):
                return inner.now
            def sleep(inner, delay):
                inner.delays.append(delay)
                inner.now += delay
        clock = Clock()
        with patch.object(daily.time_module, 'monotonic', clock.monotonic), patch.object(daily.time_module, 'sleep', clock.sleep):
            self.assertIsNone(daily.wait_for_fulfilled(self.shop, 'DeathBatch-' + DATE))
        self.assertEqual(clock.now, 45)
        self.assertEqual(clock.delays[:3], [2, 4, 8])
        self.assertEqual(self.shop.read_timeout, 35)

    def test_existing_order_dry_run_never_reconciles_files(self):
        self.seed()
        self.close()
        original = daily.queue_path(DATE).read_bytes()
        self.assertEqual(self.close(False)['status'], 'READY_TO_RECONCILE')
        self.assertEqual(original, daily.queue_path(DATE).read_bytes())
        self.assertEqual(self.shop.create_calls, 1)

    def test_child_write_gates_ignore_ambient_environment(self):
        shop = object.__new__(base.Shopify)
        shop.env = {'SHOPIFY_STORE': 'example.myshopify.com', 'SHOPIFY_CLIENT_ID': 'synthetic-client', 'SHOPIFY_CLIENT_SECRET': 'synthetic-secret'}
        shop.bridge = Path('/tmp/synthetic.mjs')
        shop.node = 'synthetic-node'
        shop.read_timeout = 35
        shop.write_authorized = False
        with patch.dict(os.environ, {'NTA_SHOPIFY_ORDER_WRITE_ENABLED': 'true', 'NTA_SHOPIFY_FULFILMENT_WRITE_ENABLED': 'true'}):
            with self.assertRaisesRegex(RuntimeError, 'authorization_required'):
                shop.gql(base.CREATE_MUTATION, {})
            response = {'ok': True, 'data': {}, 'auth': {'source': 'persisted_offline_session', 'token_mode': 'offline',
                        'persisted_offline_session_verified': True, 'access_token_unexpired': True}}
            with patch.object(base.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(response))) as run:
                shop.gql(base.CAPABILITY_QUERY, {})
                child_env = run.call_args.kwargs['env']
                self.assertNotIn('NTA_SHOPIFY_ORDER_WRITE_ENABLED', child_env)
                self.assertNotIn('NTA_SHOPIFY_FULFILMENT_WRITE_ENABLED', child_env)

    def test_raw_exception_is_not_logged(self):
        self.seed()
        with patch.object(self.shop, 'gql', side_effect=RuntimeError('synthetic-secret-value')):
            result = self.close()
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertNotIn('synthetic-secret-value', json.dumps(result))

    def test_saved_order_is_audited_not_mutation_response(self):
        self.seed()
        self.shop.on_create = lambda: self.shop.orders[0].update(discountCodes=['OTHER'])
        result = self.close()
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(self.shop.fulfillment_calls, 0)
        self.assertEqual(daily.load_queue(DATE)['status'], 'RECONCILIATION_REQUIRED')

    def test_concurrent_closers_create_exactly_one_order(self):
        self.seed()
        results = []
        barrier = threading.Barrier(2)
        class Output(BaseException):
            def __init__(inner, payload):
                inner.payload = payload
        def emit(payload, code=0):
            raise Output(payload)
        def worker():
            barrier.wait()
            try:
                daily.close(self.shop, SimpleNamespace(date=DATE, execute=True))
            except Output as output:
                results.append(output.payload['status'])
        with patch.object(daily, 'emit', emit):
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(5)
                self.assertFalse(thread.is_alive())
        self.assertEqual(sorted(results), ['ALREADY_CLOSED', 'CLOSED_VERIFIED'])
        self.assertEqual(self.shop.create_calls, 1)
        self.assertEqual(self.shop.fulfillment_calls, 1)

    def test_corrupt_recovery_baseline_blocks_fulfillment(self):
        self.seed()
        self.shop.create_error = 'exists'
        self.close()
        queue = daily.load_queue(DATE)
        queue['recovery']['before'][VID]['quantity'] = True
        daily.save_queue(queue)
        self.assertEqual(self.close()['status'], 'BLOCKED')
        self.assertEqual(self.shop.fulfillment_calls, 0)
        self.assertEqual(self.shop.create_calls, 1)

    def test_inventory_and_order_pagination_fail_closed(self):
        self.seed()
        self.shop.variants[VID]['inventoryItem']['inventoryLevels']['pageInfo']['hasNextPage'] = True
        self.assertEqual(self.close()['status'], 'BLOCKED')
        self.assertEqual(self.shop.create_calls, 0)

    def test_broad_tank_search_does_not_block_complete_exact_fish_search(self):
        product = self.product('Synthetic Guppy')
        def query(q, variables):
            result = connection([product])
            if variables['query'] == 'Tropical':
                result['pageInfo']['hasNextPage'] = True
            return {'products': result}
        with patch.object(self.shop, 'gql', query):
            result = capture(lambda: base.resolve(self.shop, 'Synthetic Guppy', 'Tropical'))
        self.assertEqual(result['status'], 'RESOLVED')
        self.assertIn('SUPPORTING_TANK_SEARCH_TRUNCATED', result['reasons'])

    def test_truncated_fish_search_still_requires_review(self):
        product = self.product('Synthetic Guppy')
        def query(q, variables):
            result = connection([product])
            if variables['query'] == 'Synthetic Guppy':
                result['pageInfo']['hasNextPage'] = True
            return {'products': result}
        with patch.object(self.shop, 'gql', query):
            result = capture(lambda: base.resolve(self.shop, 'Synthetic Guppy', 'Tropical'))
        self.assertEqual(result['status'], 'REVIEW_REQUIRED')

    def test_cli_empty_batch_with_placeholder_auth_makes_no_bridge_call(self):
        import subprocess
        example = json.loads((Path(__file__).parents[1] / 'config.example.json').read_text())
        queue_dir = Path(self.temp.name) / 'missing-queue'
        example.update(state_dir=str(queue_dir), env_file='/tmp/nonexistent-synthetic.env', session_bridge='/tmp/nonexistent-synthetic.mjs',
                       customer_id=CID, location_id=LOC, discord_channel_id=CHANNEL, authorized_sender_ids=[SENDER])
        config = Path(self.temp.name) / 'cli-config.txt'
        config.write_text(json.dumps(example))
        result = subprocess.run([sys.executable, '-B', str(Path(daily.__file__)), '--config', str(config), 'close'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)['status'], 'NO_BATCH')
        self.assertFalse(queue_dir.exists())


if __name__ == '__main__':
    unittest.main()
