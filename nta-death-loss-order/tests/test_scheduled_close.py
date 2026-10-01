import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import scheduled_close as scheduled


class SchedulerTests(unittest.TestCase):
    def test_empty_is_exact_silence_token(self):
        self.assertEqual(scheduled.notification({'status': 'NO_BATCH'}), 'NO_REPLY')

    def test_verified_confirmation_has_records_and_inventory(self):
        text = scheduled.notification({'status': 'CLOSED_VERIFIED', 'batch_date': '2026-01-01', 'order': {'name': '#SYNTHETIC'},
              'records': [{'fish': 'Guppy', 'tank': 'TT1', 'quantity': 2}], 'inventory_verified': True,
              'inventory': [{'variant_id': 'gid://shopify/ProductVariant/111', 'before_available': 4, 'after_available': 2}]})
        self.assertIn('2 × Guppy', text)
        self.assertIn('4 → 2', text)
        self.assertIn('$0.00 AUD, paid and fulfilled', text)

    def test_adoption_does_not_claim_fresh_inventory_verification(self):
        text = scheduled.notification({'status': 'ALREADY_CLOSED', 'order': {'name': '#SYNTHETIC'}, 'inventory_verified': False})
        self.assertIn('baseline is unavailable', text)
        self.assertNotIn('(verified)', text)

    def test_failure_is_actionable_and_does_not_ping_everyone(self):
        text = scheduled.notification({'status': 'BLOCKED', 'order': {'name': '#SYNTHETIC'}, 'message': '@everyone stock conflict'})
        self.assertIn('BLOCKED', text)
        self.assertIn('before retrying', text)
        self.assertNotIn('@everyone', text)

    def test_result_journal_is_machine_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            result = {'status': 'FAILED', 'message': 'Synthetic inventory conflict'}
            target = scheduled.save_result(directory, result)
            self.assertEqual(json.loads(target.read_text()), result)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(target.parent.glob('.result-*')), [])

    def test_dry_run_does_not_persist_or_enable_execute(self):
        process = SimpleNamespace(returncode=0, stdout=json.dumps({'status': 'READY_TO_CLOSE'}))
        with patch.object(scheduled, 'load_config', return_value={'state_dir': '/synthetic'}), patch.object(scheduled.subprocess, 'run', return_value=process) as child, patch.object(scheduled, 'save_result') as save, redirect_stdout(io.StringIO()):
            self.assertEqual(scheduled.run('/synthetic/config'), 0)
            self.assertNotIn('--execute', child.call_args.args[0])
            save.assert_not_called()

    def test_invalid_child_output_is_not_disclosed(self):
        process = SimpleNamespace(returncode=1, stdout='synthetic-secret-value')
        output = io.StringIO()
        with patch.object(scheduled, 'load_config', return_value={'state_dir': '/synthetic'}), patch.object(scheduled.subprocess, 'run', return_value=process), redirect_stdout(output):
            self.assertEqual(scheduled.run('/synthetic/config', execute=True), 3)
        self.assertNotIn('synthetic-secret-value', output.getvalue())
        self.assertIn('INDETERMINATE', output.getvalue())

    def test_empty_execute_does_not_create_journal(self):
        process = SimpleNamespace(returncode=0, stdout=json.dumps({'status': 'NO_BATCH'}))
        output = io.StringIO()
        with patch.object(scheduled, 'load_config', return_value={'state_dir': '/synthetic'}), patch.object(scheduled.subprocess, 'run', return_value=process), patch.object(scheduled, 'save_result') as save, redirect_stdout(output):
            self.assertEqual(scheduled.run('/synthetic/config', execute=True), 0)
            save.assert_not_called()
        self.assertEqual(output.getvalue(), 'NO_REPLY\n')


if __name__ == '__main__':
    unittest.main()
