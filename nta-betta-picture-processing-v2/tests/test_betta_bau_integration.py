"""No-network integration: strict production adapters, real policy and processor."""
import json
import unittest
from pathlib import Path

try:  # tests-dir invocation: python -m unittest test_betta_bau_integration
    from test_betta_bau_adapters import StrictAdapterTests, now, routing, sha
except ImportError:  # repo-root invocation: python -m unittest ...tests.test_betta_bau_integration
    from .test_betta_bau_adapters import StrictAdapterTests, now, routing, sha
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

        def vision_prepqa(files):
            # Mocked minimises the pipeline to deterministic local work: the
            # integration suite is documented as no-network.
            return {
                'provider': 'mock-router', 'model': 'mock-vision', 'call_id': 'pq-1',
                'timestamp': now(), 'input_hashes': [sha(files[0]), sha(files[1])],
                'routing': routing(), 'usage': {},
                'output': {'overall': 'PASS', 'same_fish': True, 'full_fins': True,
                           'faithful_colours': True, 'tank_only': True,
                           'lighting_usable': True, 'no_identity_alteration': True,
                           'reason': ''},
            }

        self.runners.update(
            execute=execute, archive=archive,
            preflight=lambda **kwargs: {'status': 'PREFLIGHT_PASS'},
            vision_preflight=vision_preflight,
            vision_prepqa=vision_prepqa,
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

    def test_label_read_disagreement_never_reaches_authority_or_archive(self):
        adapters, policy, calls = self.production_adapters()
        self.runners['label'] = lambda files: {
            'provider': 'mock-router', 'model': 'mock-vision', 'call_id': 'label-conflict',
            'timestamp': now(), 'input_hashes': [sha(files[0])],
            'routing': routing(), 'usage': {},
            'output': {'tank_id': '5 BT 43', 'tank_confidence': 0.98,
                       'photo_date': '9/10/2026', 'date_confidence': 0.97, 'reasons': []},
        }
        result = betta_process.process_batch(self.batch, 'betta-test-bau',
                                             adapters=adapters, policy=policy)
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertEqual(result['published'], 0)
        self.assertEqual(result['quarantined'], 1)
        self.assertEqual(calls, {'execute': 0, 'archive': 0})
        self.assertFalse((self.batch/'state/authority.json').exists())
        state = json.loads((self.batch/'state/process.json').read_text())
        entry = next(iter(state['fish'].values()))
        self.assertEqual(entry['status'], 'QUARANTINED')
        self.assertEqual(entry['notes'][0],
                         'label read disagreement: full=2BT12, crop=5BT43')
        self.assertEqual(entry['identify_reason'],
                         'label read disagreement: full=2BT12, crop=5BT43')
        reads = entry['label_reads']
        self.assertEqual(reads['status'], 'DISAGREE')
        self.assertEqual(reads['full']['tank_id'], '2BT12')
        self.assertEqual(reads['crop']['tank_id'], '5BT43')
        for side in ('full', 'crop'):
            self.assertTrue(Path(reads[side]['receipt_path']).is_file())
        events = [item for item in state['log']
                  if item.get('event') == 'label_read_disagreement']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['note'],
                         'label read disagreement: full=2BT12, crop=5BT43')
        self.assertEqual(events[0]['label_reads']['crop']['tank_id'], '5BT43')
        # A confident-confident contradiction is never re-evaluated by the
        # bounded retry that exists for genuine uncertainty.
        self.assertEqual(list((self.batch/'evidence/catalogue').glob('*-label-retry.json')), [])

    def test_uncertain_identification_recovers_through_the_bounded_label_retry(self):
        adapters, policy, calls = self.production_adapters()
        original = self.runners['catalogue']
        self.runners['catalogue'] = lambda files: {
            **original(files),
            'output': {**original(files)['output'],
                       'confidence': {name: (0.88 if name == 'tank_id' else 0.99)
                                      for name in original(files)['output']['confidence']}},
        }
        result = betta_process.process_batch(self.batch, 'betta-test-bau',
                                             adapters=adapters, policy=policy)
        self.assertEqual(result['status'], 'COMPLETE')
        self.assertEqual(result['published'], 1)
        state = json.loads((self.batch/'state/process.json').read_text())
        entry = next(iter(state['fish'].values()))
        self.assertEqual(entry['notes'], ['focused label retry accepted'])
        self.assertEqual(entry['label_reads']['status'], 'RETRY_ACCEPTED')
        self.assertEqual(entry['label_price_visible'], '35')
        frozen = dict(calls)
        result2 = betta_process.process_batch(self.batch, 'betta-test-bau',
                                              adapters={}, policy=policy)
        self.assertEqual(result2, result)
        self.assertEqual(frozen, calls)

    def test_below_gate_catalogue_date_recovers_via_the_focused_label_read(self):
        # Real evaluation shape: confident catalogue tank, below-gate catalogue
        # date with a different value; the confident focused read establishes
        # the date and the fish is published with the label's date.
        adapters, policy, calls = self.production_adapters()
        original = self.runners['catalogue']
        self.runners['catalogue'] = lambda files: {
            **original(files),
            'output': {**original(files)['output'], 'photo_date': '2026-04-10',
                       'confidence': {name: (0.88 if name == 'photo_date' else 0.99)
                                      for name in original(files)['output']['confidence']}},
        }
        self.runners['label'] = lambda files: {
            'provider': 'mock-router', 'model': 'mock-vision', 'call_id': 'label-shape',
            'timestamp': now(), 'input_hashes': [sha(files[0])],
            'routing': routing(), 'usage': {},
            'output': {'tank_id': '2 BT 12', 'tank_confidence': 0.99,
                       'photo_date': '14/10/2026', 'date_confidence': 0.95, 'reasons': []},
        }
        result = betta_process.process_batch(self.batch, 'betta-test-bau',
                                             adapters=adapters, policy=policy)
        self.assertEqual(result['status'], 'COMPLETE')
        self.assertEqual(result['published'], 1)
        state = json.loads((self.batch/'state/process.json').read_text())
        entry = next(iter(state['fish'].values()))
        self.assertEqual(entry['notes'], ['focused label retry accepted'])
        self.assertEqual(entry['photo_date'], '2026-10-14')
        self.assertEqual(entry['label_reads']['status'], 'RETRY_ACCEPTED')
        self.assertEqual(entry['catalogue_confidences'],
                         {'tank_id': 0.99, 'photo_date': None})
        manifest = json.loads(Path(state['manifest_path']).read_text())
        self.assertEqual(manifest['items'][0]['arrival_date'], '2026-10-14')
        self.assertEqual(manifest['items'][0]['identity']['accepted_tank'], '2BT12')
