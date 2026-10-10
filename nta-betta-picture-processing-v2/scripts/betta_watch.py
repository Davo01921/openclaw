#!/usr/bin/env python3
"""Automatic intake watcher for Betta V2.2 (DISABLED by default).

Polls the intake folder for newly received original photographs, waits until each
file has settled, excludes generated/transient/archive files and any source that
was already processed (by SHA-256), and hands stable files to the orchestrator.

Nothing is ever moved, renamed or deleted. The watcher performs no processing
itself; the orchestrator's intake adapter does the copying. The watcher will not
run at all unless explicitly enabled.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".heic", ".webp", ".bmp"}
TRANSIENT_SUFFIXES = (".tmp", ".part", ".crdownload", ".download", ".partial")
DEFAULT_INTAKE = Path.home() / "Documents" / "Betta Processing"
DEFAULT_SETTLE_SECONDS = 20.0


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def is_transient(path: Path) -> bool:
    name = path.name
    if name.startswith("."):
        return True
    if name.lower().endswith(TRANSIENT_SUFFIXES):
        return True
    parts = {p.lower() for p in path.parts}
    # Never treat generated, archived or batch-internal files as new intake.
    if parts & {"batches", "archived bettas", "grok tests", "audit"}:
        return True
    if "-clean" in name or "-labelled" in name or name == "test-hero.png":
        return True
    return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan(intake_dir: Path, *, now: float, settle_seconds: float = DEFAULT_SETTLE_SECONDS,
         known_hashes: set | None = None) -> list:
    """Return stable, new original photographs (no side effects)."""
    intake_dir = Path(intake_dir)
    known = known_hashes or set()
    stable = []
    if not intake_dir.is_dir():
        return stable
    for path in sorted(intake_dir.iterdir()):
        if not path.is_file() or is_transient(path) or not is_image(path):
            continue
        stat = path.stat()
        if (now - stat.st_mtime) < settle_seconds:
            continue  # still transferring
        digest = sha256_file(path)
        if digest in known:
            continue  # already processed -> prevent duplicate batches
        stable.append({"path": str(path), "sha256": digest, "size": stat.st_size,
                       "mtime": stat.st_mtime})
    return stable


class ProcessedRegistry:
    """Persistent record of processed source hashes so restarts never re-intake."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path)
        con.execute("CREATE TABLE IF NOT EXISTS processed (source_sha256 TEXT PRIMARY KEY, "
                    "batch_id TEXT, processed_at TEXT)")
        con.commit()
        con.close()

    def hashes(self) -> set:
        con = sqlite3.connect(self.path)
        try:
            return {row[0] for row in con.execute("SELECT source_sha256 FROM processed")}
        finally:
            con.close()

    def record(self, source_sha256: str, batch_id: str) -> None:
        con = sqlite3.connect(self.path)
        try:
            con.execute("INSERT OR IGNORE INTO processed (source_sha256, batch_id, processed_at) "
                        "VALUES (?,?,?)", (source_sha256, batch_id, time.strftime("%Y-%m-%dT%H:%M:%S")))
            con.commit()
        finally:
            con.close()


def wait_until_stable(intake_dir: Path, *, settle_seconds: float, poll_seconds: float = 2.0,
                      timeout: float = 600.0, known_hashes: set | None = None) -> list:
    """Poll until the candidate set is non-empty and unchanged between two scans."""
    deadline = time.monotonic() + timeout
    previous = None
    while time.monotonic() < deadline:
        current = scan(intake_dir, now=time.time(), settle_seconds=settle_seconds,
                       known_hashes=known_hashes)
        if current and previous is not None:
            keys = lambda items: sorted((i["path"], i["size"]) for i in items)
            if keys(current) == keys(previous):
                return current
        previous = current
        time.sleep(poll_seconds)
    return scan(intake_dir, now=time.time(), settle_seconds=settle_seconds, known_hashes=known_hashes)


def main() -> int:
    parser = argparse.ArgumentParser(description="Betta automatic intake watcher (disabled by default)")
    parser.add_argument("--intake-dir", type=Path, default=DEFAULT_INTAKE)
    parser.add_argument("--settle-seconds", type=float, default=DEFAULT_SETTLE_SECONDS)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--enable", action="store_true",
                        help="Explicitly enable the watcher (owner approval required)")
    args = parser.parse_args()

    if not args.enable:
        print(json.dumps({"enabled": False,
                          "message": "watcher disabled; pass --enable after owner approval"}))
        return 0

    registry = ProcessedRegistry(args.registry) if args.registry else None
    known = registry.hashes() if registry else set()
    files = wait_until_stable(args.intake_dir, settle_seconds=args.settle_seconds,
                              poll_seconds=args.poll_seconds, known_hashes=known)
    print(json.dumps({"enabled": True, "stable_sources": files}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
