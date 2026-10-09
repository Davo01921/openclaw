#!/usr/bin/env python3
"""Generic, isolated batch lifecycle for NTA Betta Processing V2.1.

Every new intake is assigned a unique batch id and its own workspace. Historical
batches are immutable and can never block, contaminate, or be replayed into new
work. Nothing about a previous batch (tank numbers, dates, image filenames) is
hardcoded; a batch is described only by its generated id and its own files.

Layout (default root ``~/Documents/Betta Processing/batches``)::

    batches/
      registry.json                 append-only index of all batches
      <batch_id>/
        batch.json                  this batch's identity + status
        intake/                     new source photographs
        evidence/                   catalogue, QA, approvals, snapshots
        manifest/                   approved Shopify manifest(s)
        state/                      uploader/recovery state
        reports/                    dry-run / verify / reconciliation reports
        receipts/                   final per-product receipts
        archive/                    archived evidence for this batch

Commands: ``new``, ``list``, ``status``, ``active``, ``close``,
``register-historical``. All are local and deterministic; no network calls.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

SYDNEY = ZoneInfo("Australia/Sydney")

REGISTRY_SCHEMA = "nta-betta-batch-registry-v1"
BATCH_SCHEMA = "nta-betta-batch-v1"
# Accepts the uploader's manifest batch_id shape and the generated
# ``betta-YYYYMMDD-HHMMSS-token`` form. New ids always use the generated form.
BATCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
NEW_BATCH_RE = re.compile(r"^betta-\d{8}-\d{6}-[a-z0-9]{6}$")

ACTIVE = "ACTIVE"
COMPLETE = "COMPLETE"
ABANDONED = "ABANDONED"
TERMINAL_STATUSES = {COMPLETE, ABANDONED}

SUBDIRS = ("intake", "evidence", "manifest", "state", "reports", "receipts", "archive")

DEFAULT_ROOT = Path.home() / "Documents" / "Betta Processing" / "batches"


class BatchLifecycleError(ValueError):
    pass


def now_sydney() -> str:
    return datetime.now(SYDNEY).isoformat()


def sydney_stamp(moment: Optional[datetime] = None) -> str:
    return (moment or datetime.now(SYDNEY)).strftime("%Y%m%d-%H%M%S")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Registry:
    """Append-only batch registry guarded by an advisory lock.

    The lock is a single-host serializer; two independent ``open()`` calls (even
    from threads) contend for it, so concurrent ``new`` calls cannot mint the same
    id or lose an entry.
    """

    def __init__(self, root: Path, lock_timeout: float = 15.0, poll: float = 0.02):
        self.root = Path(root)
        self.path = self.root / "registry.json"
        self.lock_path = self.root / ".registry.lock"
        self.lock_timeout = lock_timeout
        self.poll = poll

    class _Lock:
        def __init__(self, registry: "Registry"):
            self.registry = registry
            self._fh = None

        def __enter__(self):
            self.registry.root.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.registry.lock_path, "a+")
            deadline = time.monotonic() + self.registry.lock_timeout
            while True:
                try:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return self
                except OSError:
                    if time.monotonic() >= deadline:
                        self._fh.close()
                        raise BatchLifecycleError("timed out acquiring batch registry lock")
                    time.sleep(self.registry.poll)

        def __exit__(self, *exc):
            if self._fh is not None:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                self._fh.close()
            return False

    def load(self) -> dict:
        if not self.path.is_file():
            return {"schema": REGISTRY_SCHEMA, "batches": []}
        with self.path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        if data.get("schema") != REGISTRY_SCHEMA:
            raise BatchLifecycleError("unsupported registry schema")
        return data

    def _save(self, data: dict) -> None:
        _atomic_write(self.path, data)

    def find(self, batch_id: str) -> Optional[dict]:
        for entry in self.load()["batches"]:
            if entry.get("batch_id") == batch_id:
                return entry
        return None

    def all(self) -> list:
        return self.load()["batches"]


def batch_dir(root: Path, batch_id: str) -> Path:
    return Path(root) / batch_id


def _new_batch_id(moment: Optional[datetime], rng) -> str:
    token = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(6))
    return f"betta-{sydney_stamp(moment)}-{token}"


def create_batch(
    root: Path = DEFAULT_ROOT,
    label: Optional[str] = None,
    moment: Optional[datetime] = None,
    rng=None,
) -> dict:
    """Mint a unique batch id and an isolated workspace. Never reuses an id."""
    root = Path(root)
    registry = Registry(root)
    generator = rng or secrets.SystemRandom()
    with Registry._Lock(registry):
        data = registry.load()
        existing = {entry["batch_id"] for entry in data["batches"]}
        for _ in range(100):
            batch_id = _new_batch_id(moment, generator)
            if batch_id not in existing and not batch_dir(root, batch_id).exists():
                break
        else:
            raise BatchLifecycleError("unable to allocate a unique batch id")
        directory = batch_dir(root, batch_id)
        for sub in SUBDIRS:
            (directory / sub).mkdir(parents=True, exist_ok=True)
        entry = {
            "batch_id": batch_id,
            "status": ACTIVE,
            "label": label,
            "created_at": now_sydney(),
            "closed_at": None,
            "manifest_sha256": None,
            "path": str(directory),
        }
        _atomic_write(directory / "batch.json", {
            "schema": BATCH_SCHEMA, "batch_id": batch_id, "status": ACTIVE,
            "label": label, "created_at": entry["created_at"],
        })
        data["batches"].append(entry)
        registry._save(data)
        return entry


def list_batches(root: Path = DEFAULT_ROOT) -> list:
    return Registry(root).all()


def get_batch(root: Path, batch_id: str) -> Optional[dict]:
    return Registry(root).find(batch_id)


def active_batches(root: Path = DEFAULT_ROOT) -> list:
    return [entry for entry in Registry(root).all() if entry.get("status") == ACTIVE]


def assert_batch_writable(root: Path, batch_id: str) -> dict:
    entry = get_batch(root, batch_id)
    if entry is None:
        raise BatchLifecycleError(f"unknown batch: {batch_id}")
    if entry.get("status") in TERMINAL_STATUSES:
        raise BatchLifecycleError(
            f"batch {batch_id} is {entry['status']} and immutable; start a new batch"
        )
    return entry


def close_batch(root: Path, batch_id: str, status: str = COMPLETE) -> dict:
    if status not in TERMINAL_STATUSES:
        raise BatchLifecycleError(f"close status must be one of {sorted(TERMINAL_STATUSES)}")
    registry = Registry(root)
    with Registry._Lock(registry):
        data = registry.load()
        entry = next((e for e in data["batches"] if e.get("batch_id") == batch_id), None)
        if entry is None:
            raise BatchLifecycleError(f"unknown batch: {batch_id}")
        if entry.get("status") in TERMINAL_STATUSES:
            return entry  # idempotent: preserves the original close record
        entry["status"] = status
        entry["closed_at"] = now_sydney()
        registry._save(data)
        batch_file = batch_dir(root, batch_id) / "batch.json"
        if batch_file.is_file():
            record = json.loads(batch_file.read_text(encoding="utf-8"))
            record.update({"status": status, "closed_at": entry["closed_at"]})
            _atomic_write(batch_file, record)
        return entry


def register_historical(root: Path, manifest_path: Path) -> dict:
    """Record an already-completed batch as immutable history, generically.

    Reads the batch id and digest from the manifest; nothing about the historical
    batch (tanks, dates, filenames) is hardcoded. An existing batch directory or
    registry entry is preserved, never overwritten.
    """
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    batch_id = manifest.get("batch_id")
    if not isinstance(batch_id, str) or BATCH_RE.fullmatch(batch_id) is None:
        raise BatchLifecycleError("manifest batch_id is missing or not in the generic format")
    digest = sha256_file(manifest_path)
    registry = Registry(root)
    with Registry._Lock(registry):
        data = registry.load()
        entry = next((e for e in data["batches"] if e.get("batch_id") == batch_id), None)
        if entry is None:
            directory = batch_dir(root, batch_id)
            for sub in SUBDIRS:
                (directory / sub).mkdir(parents=True, exist_ok=True)
            entry = {
                "batch_id": batch_id,
                "status": COMPLETE,
                "label": "historical",
                "created_at": now_sydney(),
                "closed_at": now_sydney(),
                "manifest_sha256": digest,
                "path": str(directory),
            }
            data["batches"].append(entry)
            registry._save(data)
        return entry


def batch_status(root: Path, batch_id: str) -> dict:
    entry = get_batch(root, batch_id)
    if entry is None:
        raise BatchLifecycleError(f"unknown batch: {batch_id}")
    directory = batch_dir(root, batch_id)
    counts = {sub: len(list((directory / sub).glob("*"))) if (directory / sub).is_dir() else 0
              for sub in SUBDIRS}
    return {"batch": entry, "workspace": str(directory), "counts": counts}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description="Generic isolated Betta batch lifecycle")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new"); p.add_argument("--label", default=None)
    p = sub.add_parser("list")
    p = sub.add_parser("active")
    p = sub.add_parser("status"); p.add_argument("batch")
    p = sub.add_parser("close"); p.add_argument("batch")
    p.add_argument("--status", default=COMPLETE, choices=sorted(TERMINAL_STATUSES))
    p = sub.add_parser("register-historical"); p.add_argument("manifest", type=Path)

    args = parser.parse_args()
    try:
        if args.cmd == "new":
            print(json.dumps(create_batch(args.root, args.label), indent=2, sort_keys=True))
        elif args.cmd == "list":
            print(json.dumps(list_batches(args.root), indent=2, sort_keys=True))
        elif args.cmd == "active":
            print(json.dumps(active_batches(args.root), indent=2, sort_keys=True))
        elif args.cmd == "status":
            print(json.dumps(batch_status(args.root, args.batch), indent=2, sort_keys=True))
        elif args.cmd == "close":
            print(json.dumps(close_batch(args.root, args.batch, args.status), indent=2, sort_keys=True))
        elif args.cmd == "register-historical":
            print(json.dumps(register_historical(args.root, args.manifest), indent=2, sort_keys=True))
        return 0
    except (BatchLifecycleError, OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

