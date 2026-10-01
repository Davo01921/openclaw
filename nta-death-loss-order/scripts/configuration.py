"""Non-secret deployment configuration. Importing this module has no side effects."""
import json
import os
import re
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo


def load_config(path=None):
    source = path or os.getenv('NTA_DEATH_LOSS_CONFIG')
    if not source:
        raise ValueError('configuration_required')
    try:
        data = json.loads(Path(source).read_text())
    except (OSError, ValueError):
        raise ValueError('configuration_unreadable') from None
    required = {'state_dir', 'env_file', 'session_bridge', 'customer_id', 'location_id',
                'discord_channel_id', 'authorized_sender_ids', 'timezone', 'cutoff'}
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError('configuration_fields_invalid')
    for key in ['state_dir', 'env_file', 'session_bridge']:
        if not isinstance(data[key], str) or not Path(data[key]).is_absolute() or '<' in data[key]:
            raise ValueError('configuration_path_invalid:' + key)
    for key, resource in [('customer_id', 'Customer'), ('location_id', 'Location')]:
        if not isinstance(data[key], str) or not re.fullmatch(r'gid://shopify/' + resource + r'/[1-9]\d*', data[key]):
            raise ValueError('configuration_id_invalid:' + key)
    ids = data['authorized_sender_ids']
    if not isinstance(ids, list) or not ids or len(set(map(str, ids))) != len(ids):
        raise ValueError('configuration_senders_invalid')
    for value in [data['discord_channel_id'], *ids]:
        if not isinstance(value, str) or not re.fullmatch(r'[1-9]\d{5,24}', value):
            raise ValueError('configuration_discord_id_invalid')
    if data['timezone'] != 'Australia/Sydney':
        raise ValueError('configuration_timezone_invalid')
    ZoneInfo(data['timezone'])
    if not isinstance(data['cutoff'], str) or not re.fullmatch(r'\d{2}:\d{2}', data['cutoff']):
        raise ValueError('configuration_cutoff_invalid')
    try:
        time.fromisoformat(data['cutoff'])
    except ValueError:
        raise ValueError('configuration_cutoff_invalid') from None
    return data
