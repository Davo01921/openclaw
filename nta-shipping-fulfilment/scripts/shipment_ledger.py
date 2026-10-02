"""Durable once-only shipment intents. An unfinished intent never authorizes retry."""
import json
import os
import sqlite3
from pathlib import Path

class ShipmentLedger:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path, timeout=30)
        os.chmod(path, 0o600)
        self.db.execute('CREATE TABLE IF NOT EXISTS shipments (key TEXT PRIMARY KEY, state TEXT NOT NULL, request TEXT NOT NULL, receipt TEXT)')
        self.db.commit()
    def prior_status(self, key):
        row = self.db.execute('SELECT state FROM shipments WHERE key=?', (key,)).fetchone()
        return None if row is None else ('DUPLICATE_NOOP' if row[0] == 'VERIFIED' else 'REVIEW_REQUIRED')
    def claim(self, key, request):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            prior = self.db.execute('SELECT state FROM shipments WHERE key=?', (key,)).fetchone()
            if prior:
                return 'DUPLICATE_NOOP' if prior[0] == 'VERIFIED' else 'REVIEW_REQUIRED'
            self.db.execute('INSERT INTO shipments VALUES (?, ?, ?, NULL)', (key, 'INDETERMINATE', json.dumps(request, sort_keys=True)))
        return 'CLAIMED'
    def receipt(self, key, receipt, verified=False):
        if verified and receipt.get('audit', {}).get('status') != 'PASS':
            raise ValueError('independent PASS audit required')
        with self.db:
            changed = self.db.execute('UPDATE shipments SET state=?,receipt=? WHERE key=? AND state=?',
                ('VERIFIED' if verified else 'INDETERMINATE', json.dumps(receipt, sort_keys=True), key, 'INDETERMINATE')).rowcount
            if changed != 1: raise ValueError('exact unfinished intent required')
    def close(self): self.db.close()
