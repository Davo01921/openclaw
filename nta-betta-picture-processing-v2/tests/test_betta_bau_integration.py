"""No-network integration: strict production adapters, real policy and processor."""
import json
import unittest
from pathlib import Path
from test_betta_bau_adapters import StrictAdapterTests
import betta_policy
import betta_process


class BAUIntegrationTests(StrictAdapterTests):
    def production_adapters(self):
        data = betta_policy.default_policy()
        data.update(enabled=True, automatic_batch_authorisation=True, paid_generation_authorised=True)
        policy = betta_policy.StandingPolicy(data)
        calls = {'execute': 0, 'archive': 0}
        def execute(entry, path, digest):
            calls['execute'] += 1
            self.assertEqual(digest, __import__('hashlib').sha256(path.read_bytes()).hexdigest())
            self.assertTrue((self.batch/'state/authority.json').is_file())
            return {'status': 'VERIFIED', 'receipt': {'verified_at': '2026-10-11T10:00:00+11:00'}}
        def archive(state, directory):
            calls['archive'] += 1
            self.assertTrue((directory/'reports/betta-inventory.csv').is_file())
            return {'status': 'ARCHIVED', 'batch_status': 'COMPLETE'}
        def vision_preflight(files):
            # An unreadable fixture frame: geometry unusable, no identity conflict.
            return {
                'provider': 'mock-router', 'model': 'mock-vision', 'call_id': 'pf-1',
                'timestamp': now(), 'input_hashes': [sha(files[0])],
                'routing': routing(), 'usage': {},
                'output': {'tank_id': '', 'photo_date': '', 'tank_confidence': 0.0,
                           'date_confidence': 0.0, 'fish_confidence': 0.0,
                           'one_fish_visible': True, 'needs_retake': False,
                           'tank_bounds': None, 'fish_bounds': None, 'debris_boxes': []},
            }

        self.runners.update(
            execute=execute, archive=archive,
            preflight=lambda **kwargs: {'status': 'PREFLIGHT_PASS'},
            vision_preflight=vision_preflight,
            vision_retry_delay_seconds=0)
        adapters, _ = self.make(policy=policy)
        return adapters, policy, calls

    def test_full_pipeline_issues_exact_receipt_and_restart_is_inert(self):
        adapters, policy, calls = self.production_adapters()
        result = betta_process.process_batch(self.batch, 'betta-test-bau', adapters=adapters, policy=policy)
        self.assertEqual(result['status'], 'COMPLETE')
        self.assertEqual(result['published'], 1)
        state = json.loads((self.batch/'state/process.json').read_text())
        self.assertEqual(state['fish'][next(iter(state['fish']))]['title'], '2BT12 - Blue Red Marble Halfmoon Male')
        frozen = dict(calls)
        result2 = betta_process.process_batch(self.batch, 'betta-test-bau', adapters={}, policy=policy)
        self.assertEqual(result2, result)
        self.assertEqual(frozen, calls)

    def test_all_quarantined_never_issues_authority_or_archives(self):
        adapters, policy, calls = self.production_adapters()
        self.runners['qa'] = lambda entry: {'output': {'assertions': {}, 'overall': 'FAIL'}}
        result = betta_process.process_batch(self.batch, 'betta-test-bau', adapters=adapters, policy=policy)
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertEqual(result['published'], 0)
        self.assertEqual(result['quarantined'], 1)
        self.assertEqual(calls, {'execute': 0, 'archive': 0})
        self.assertFalse((self.batch/'state/authority.json').exists())
