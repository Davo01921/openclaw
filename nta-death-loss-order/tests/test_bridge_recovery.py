"""Read transport resilience; subprocess responses are synthetic and offline."""
import json
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_runtime import base
from scheduled_close import notification


def response(error=None, data=None):
    payload = {'ok': error is None, 'data': data or {}, 'errors': [error] if error else [],
               'auth': {'source': 'persisted_offline_session', 'token_mode': 'offline',
                        'persisted_offline_session_verified': True, 'access_token_unexpired': True}}
    return SimpleNamespace(returncode=1 if error else 0, stdout=json.dumps(payload))


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.shop = object.__new__(base.Shopify)
        self.shop.env = {'SHOPIFY_STORE': 'example.myshopify.com', 'SHOPIFY_CLIENT_ID': 'fixture',
                         'SHOPIFY_CLIENT_SECRET': 'synthetic-secret'}
        self.shop.bridge = Path('/tmp/synthetic-bridge.mjs')
        self.shop.node = 'synthetic-node'
        self.shop.read_timeout = 35
        self.shop.write_authorized = False

    def test_transient_read_recovers_without_changing_request(self):
        with patch.object(base.subprocess, 'run', side_effect=[response('http:503'), response(data={'verified': True})]) as run, \
             patch.object(base.time, 'sleep') as sleep:
            self.assertEqual(self.shop.gql(base.CAPABILITY_QUERY, {}), {'verified': True})
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].kwargs['input'], run.call_args_list[1].kwargs['input'])
        sleep.assert_called_once_with(1)
        self.assertNotIn('NTA_SHOPIFY_ORDER_WRITE_ENABLED', run.call_args.kwargs['env'])
        self.assertEqual(run.call_args.kwargs['env']['NTA_AUTH_BRIDGE_SAFE_DIAGNOSTICS'], 'true')

    def test_transient_read_retries_are_bounded(self):
        with patch.object(base.subprocess, 'run', return_value=response('bridge_internal_error:TimeoutError:23')) as run, \
             patch.object(base.time, 'sleep') as sleep:
            with self.assertRaises(base.BridgeError) as caught:
                self.shop.gql(base.CAPABILITY_QUERY, {})
        self.assertEqual(run.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])
        self.assertEqual(caught.exception.details, {'operation': 'capability', 'error_code': 'bridge_internal_error',
                         'bridge_attempts': 3, 'bridge_error_type': 'TimeoutError', 'transport_code': '23'})

    def test_terminal_auth_and_permission_errors_are_not_retried(self):
        for error in ['graphql_access_denied', 'http:401', 'offline_refresh_reauthorization_required']:
            with self.subTest(error=error), patch.object(base.subprocess, 'run', return_value=response(error)) as run, \
                 patch.object(base.time, 'sleep') as sleep:
                with self.assertRaises(base.BridgeError):
                    self.shop.gql(base.CAPABILITY_QUERY, {})
                self.assertEqual(run.call_count, 1)
                sleep.assert_not_called()

    def test_database_configuration_error_is_not_retried(self):
        with patch.object(base.subprocess, 'run', return_value=response('bridge_internal_error:PrismaClientKnownRequestError:P2021')) as run:
            with self.assertRaises(base.BridgeError):
                self.shop.gql(base.CAPABILITY_QUERY, {})
        self.assertEqual(run.call_count, 1)

    def test_order_and_fulfillment_mutations_are_never_retried(self):
        self.shop.write_authorized = True
        for query in [base.CREATE_MUTATION, base.CREATE_FULFILLMENT_MUTATION]:
            with self.subTest(query=query), patch.object(base.subprocess, 'run', return_value=response('http:503')) as run, \
                 patch.object(base.time, 'sleep') as sleep:
                with self.assertRaises(base.BridgeError):
                    self.shop.gql(query, {})
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run.call_args.kwargs['timeout'], 35)
                sleep.assert_not_called()

    def test_retry_timeout_includes_backoff_in_callers_deadline(self):
        clock = [0]
        def read(*args, **kwargs):
            if clock[0] == 0:
                clock[0] = 20
                return response('bridge_internal_error:TimeoutError:23')
            self.assertEqual(kwargs['timeout'], 14)
            clock[0] += 1
            return response()
        def sleep(delay):
            clock[0] += delay
        with patch.object(base.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(base.time, 'sleep', side_effect=sleep), patch.object(base.subprocess, 'run', side_effect=read) as run:
            self.shop.gql(base.CAPABILITY_QUERY, {})
        self.assertEqual(run.call_count, 2)
        self.assertLessEqual(clock[0], 35)

    def test_poll_remaining_deadline_cannot_be_extended_by_retry(self):
        self.shop.read_timeout = 2
        clock = [0]
        def read(*args, **kwargs):
            clock[0] += 1.5
            return response('http:503')
        with patch.object(base.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(base.time, 'sleep') as sleep, patch.object(base.subprocess, 'run', side_effect=read) as run:
            with self.assertRaises(base.BridgeError):
                self.shop.gql(base.CAPABILITY_QUERY, {})
        self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()

    def test_subprocess_timeout_never_retries_mutation(self):
        self.shop.write_authorized = True
        with patch.object(base.subprocess, 'run', side_effect=subprocess.TimeoutExpired('synthetic-secret', 35)) as run:
            with self.assertRaises(base.BridgeError) as caught:
                self.shop.gql(base.CREATE_MUTATION, {})
        self.assertEqual(run.call_count, 1)
        self.assertNotIn('synthetic-secret', json.dumps(caught.exception.details))

    def test_raw_bridge_error_is_redacted(self):
        with patch.object(base.subprocess, 'run', return_value=response('synthetic-secret-value')):
            with self.assertRaises(base.BridgeError) as caught:
                self.shop.gql(base.CAPABILITY_QUERY, {})
        self.assertEqual(caught.exception.details['error_code'], 'bridge_request_failed')
        self.assertNotIn('synthetic-secret-value', json.dumps(caught.exception.details))

    def test_failure_alert_identifies_batch_and_read_without_secret(self):
        result = {'status': 'BLOCKED', 'batch_date': '2026-10-01', 'message': 'Read failed.',
                  'operation': 'existing_orders', 'error_code': 'bridge_internal_error', 'bridge_attempts': 3}
        message = notification(result)
        self.assertIn('2026-10-01', message)
        self.assertIn('existing_orders: bridge_internal_error', message)
        self.assertIn('attempts 3', message)


if __name__ == '__main__':
    unittest.main()
