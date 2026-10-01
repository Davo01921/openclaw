"""Model-free scheduler adapter. OpenClaw owns Discord delivery."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from configuration import load_config


def clean(value, limit=140):
    return ' '.join(str(value).replace('@', '＠').split())[:limit]


def notification(result):
    status = result.get('status')
    if status == 'NO_BATCH':
        return 'NO_REPLY'
    order = result.get('order') or {}
    name = clean(order.get('name', 'order identity unavailable'))
    day = clean(result.get('batch_date', 'current Sydney date'))
    if status in {'CLOSED_VERIFIED', 'ALREADY_CLOSED'}:
        lines = [f'NTA deaths {day}: {name} — $0.00 AUD, paid and fulfilled.']
        records = result.get('records', [])
        for record in records[:8]:
            lines.append(f"• {record['quantity']} × {clean(record['fish'], 80)}; tank {clean(record['tank'], 32)}")
        if len(records) > 8:
            lines.append(f'• {len(records) - 8} additional records preserved in the order and queue.')
        if result.get('inventory_verified'):
            for entry in result.get('inventory', [])[:8]:
                lines.append(f"• Inventory {entry['variant_id'].rsplit('/', 1)[-1]}: {entry['before_available']} → {entry['after_available']} (verified).")
        elif result.get('inventory_verification') == 'PREVIOUSLY_VERIFIED':
            lines.append('Existing order verified; inventory proof is from its original close.')
        else:
            lines.append('Existing order verified; historical inventory baseline is unavailable. No additional stock deduction was made.')
        return '\n'.join(lines)[:1900]
    if status in {'READY_TO_CLOSE', 'READY_TO_RECONCILE'}:
        return f'NTA deaths {day}: {status}; preview only, no writes.'
    diagnostic = ''
    if result.get('error_code'):
        diagnostic = (f" [{clean(result.get('operation', 'helper'), 32)}: {clean(result['error_code'], 60)}"
                      f"; attempts {clean(result.get('bridge_attempts', 'unknown'), 8)}]")
    return (f'NTA deaths {day}: {clean(status or "FAILED")} — {name}.{diagnostic} '
            f'{clean(result.get("message", "Inspect the saved queue and recovery state."), 500)} '
            'Review the existing order and local recovery journal before retrying; do not create a replacement order.')[:1900]


def save_result(state_dir, result):
    directory = Path(state_dir) / 'results'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = directory / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex[:8] + '.json')
    descriptor, temporary = tempfile.mkstemp(prefix='.result-', dir=directory)
    try:
        with os.fdopen(descriptor, 'w') as handle:
            json.dump(result, handle, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target


def run(config_path, execute=False, date=None):
    try:
        config = load_config(config_path)
        argv = [sys.executable, '-B', str(Path(__file__).with_name('daily_batch.py')), '--config', str(config_path), 'close']
        if date:
            argv += ['--date', date]
        if execute:
            argv.append('--execute')
        process = subprocess.run(argv, capture_output=True, text=True, timeout=540)
        result = json.loads(process.stdout)
        if not isinstance(result, dict) or not isinstance(result.get('status'), str):
            raise ValueError('invalid_result')
        if result['status'] != 'NO_BATCH' and execute:
            if result.get('status') == 'ALREADY_CLOSED' and not result.get('records'):
                # Read the already-audited record set for the concise confirmation.
                from daily_batch import configure, load_queue
                configure(config)
                result['records'] = load_queue(result['batch_date'])['items']
            save_result(config['state_dir'], result)
        if execute:
            print(notification(result))
        else:
            print(json.dumps(result, indent=2))
        successes = {'NO_BATCH', 'CLOSED_VERIFIED', 'ALREADY_CLOSED', 'READY_TO_CLOSE', 'READY_TO_RECONCILE'}
        return 0 if process.returncode == 0 and result['status'] in successes else 3
    except (Exception, SystemExit):
        # Never echo captured stderr, stdout, credentials, or raw exception text.
        result = {'status': 'INDETERMINATE', 'message': 'Scheduled close did not produce a verified result. Check the saved queue/order and bridge health; no blind retry is safe.'}
        print(notification(result) if execute else json.dumps(result))
        return 3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--date')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    raise SystemExit(run(args.config, execute=args.execute, date=args.date))


if __name__ == '__main__':
    main()
