"""Safe local backup utility for the Gumtree SQLite registry."""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SYDNEY = ZoneInfo("Australia/Sydney")


def backup_registry(db_path: str | Path, backup_dir: str | Path) -> Path:
    source = Path(db_path)
    if not source.exists():
        raise FileNotFoundError(source)

    destination_dir = Path(backup_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(SYDNEY).strftime("%Y%m%d-%H%M%S")
    destination = destination_dir / f"gumtree-{stamp}.db"

    # SQLite's backup API yields a transactionally consistent copy even when the
    # source database is open elsewhere.
    source_conn = sqlite3.connect(source)
    destination_conn = sqlite3.connect(destination)
    try:
        source_conn.backup(destination_conn)
    finally:
        destination_conn.close()
        source_conn.close()

    # Copy file permissions conservatively after the database copy succeeds.
    shutil.copymode(source, destination)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Back up the NTA Gumtree SQLite registry")
    parser.add_argument("--db", default="data/gumtree.db")
    parser.add_argument("--backup-dir", default="data/backups")
    args = parser.parse_args(argv)
    path = backup_registry(args.db, args.backup_dir)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
