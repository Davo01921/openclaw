#!/usr/bin/env python3
"""Persistent per-Betta telemetry ledger for NTA picture processing.

Primary storage is SQLite so concurrent/repeated batches can be recorded safely.
A CSV export can be generated for GitHub/audit use.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path.home() / "Documents" / "Betta Processing" / "betta-telemetry.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS betta_processing_telemetry (
    batch_id TEXT NOT NULL,
    tank_number TEXT NOT NULL,
    date_entered TEXT NOT NULL,
    tokens_input INTEGER NOT NULL DEFAULT 0,
    tokens_output INTEGER NOT NULL DEFAULT 0,
    grokai_cost REAL NOT NULL DEFAULT 0,
    grokai_cost_currency TEXT NOT NULL DEFAULT 'USD',
    provider TEXT,
    model TEXT,
    product_id TEXT,
    title TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (batch_id, tank_number)
);
"""

FIELDS = [
    "batch_id",
    "tank_number",
    "date_entered",
    "tokens_input",
    "tokens_output",
    "grokai_cost",
    "grokai_cost_currency",
    "provider",
    "model",
    "product_id",
    "title",
    "updated_at",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute(SCHEMA)
    return con


def as_nonnegative_int(value: object, name: str) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"{name} must be >= 0")
    return parsed


def as_nonnegative_float(value: object, name: str) -> float:
    try:
        parsed = float(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if parsed < 0:
        raise ValueError(f"{name} must be >= 0")
    return parsed


def upsert(con: sqlite3.Connection, record: dict) -> None:
    batch_id = str(record.get("batch_id") or "").strip()
    tank_number = str(record.get("tank_number") or "").strip()
    if not batch_id or not tank_number:
        raise ValueError("batch_id and tank_number are required")

    date_entered = str(record.get("date_entered") or utc_now()).strip()
    tokens_input = as_nonnegative_int(record.get("tokens_input"), "tokens_input")
    tokens_output = as_nonnegative_int(record.get("tokens_output"), "tokens_output")
    grokai_cost = as_nonnegative_float(record.get("grokai_cost"), "grokai_cost")
    currency = str(record.get("grokai_cost_currency") or "USD").strip().upper()
    updated_at = utc_now()

    con.execute(
        """
        INSERT INTO betta_processing_telemetry (
            batch_id, tank_number, date_entered, tokens_input, tokens_output,
            grokai_cost, grokai_cost_currency, provider, model, product_id, title, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(batch_id, tank_number) DO UPDATE SET
            date_entered=excluded.date_entered,
            tokens_input=excluded.tokens_input,
            tokens_output=excluded.tokens_output,
            grokai_cost=excluded.grokai_cost,
            grokai_cost_currency=excluded.grokai_cost_currency,
            provider=excluded.provider,
            model=excluded.model,
            product_id=excluded.product_id,
            title=excluded.title,
            updated_at=excluded.updated_at
        """,
        (
            batch_id,
            tank_number,
            date_entered,
            tokens_input,
            tokens_output,
            grokai_cost,
            currency,
            record.get("provider"),
            record.get("model"),
            record.get("product_id"),
            record.get("title"),
            updated_at,
        ),
    )
    con.commit()


def export_csv(con: sqlite3.Connection, output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = con.execute(
        "SELECT " + ",".join(FIELDS) + " FROM betta_processing_telemetry ORDER BY date_entered, tank_number"
    ).fetchall()
    with output.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(FIELDS)
        writer.writerows(rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("record")
    p.add_argument("--json", required=True, help="One JSON object containing the per-tank telemetry record")

    p = sub.add_parser("export")
    p.add_argument("--csv", type=Path, required=True)

    p = sub.add_parser("show")
    p.add_argument("--tank")

    args = parser.parse_args()
    try:
        con = connect(args.db)
        if args.cmd == "record":
            upsert(con, json.loads(args.json))
        elif args.cmd == "export":
            print(json.dumps({"rows": export_csv(con, args.csv), "csv": str(args.csv)}))
        else:
            sql = "SELECT " + ",".join(FIELDS) + " FROM betta_processing_telemetry"
            params: tuple[str, ...] = ()
            if args.tank:
                sql += " WHERE tank_number = ?"
                params = (args.tank,)
            sql += " ORDER BY date_entered DESC, tank_number"
            rows = [dict(zip(FIELDS, row)) for row in con.execute(sql, params).fetchall()]
            print(json.dumps(rows, indent=2, sort_keys=True))
        con.close()
        return 0
    except (ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
