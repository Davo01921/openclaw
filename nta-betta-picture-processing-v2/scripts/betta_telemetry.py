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
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_DB = Path.home() / "Documents" / "Betta Processing" / "betta-telemetry.sqlite3"
SYDNEY = ZoneInfo("Australia/Sydney")

SCHEMA = """
CREATE TABLE IF NOT EXISTS betta_processing_telemetry (
    batch_id TEXT NOT NULL,
    tank_number TEXT NOT NULL,
    date_entered TEXT NOT NULL,
    arrival_date TEXT,
    tokens_input INTEGER NOT NULL DEFAULT 0,
    tokens_output INTEGER NOT NULL DEFAULT 0,
    grokai_cost REAL,
    grokai_cost_currency TEXT NOT NULL DEFAULT 'USD',
    grokai_cost_source TEXT,
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
    "arrival_date",
    "tokens_input",
    "tokens_output",
    "grokai_cost",
    "grokai_cost_currency",
    "grokai_cost_source",
    "provider",
    "model",
    "product_id",
    "title",
    "updated_at",
]


def sydney_now() -> str:
    return datetime.now(SYDNEY).isoformat()


def normalize_to_sydney(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return sydney_now()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=SYDNEY)
        return parsed.astimezone(SYDNEY).isoformat()
    except ValueError:
        return text


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute(SCHEMA)
    existing = {row[1] for row in con.execute("PRAGMA table_info(betta_processing_telemetry)")}
    migrations = {
        "arrival_date": "ALTER TABLE betta_processing_telemetry ADD COLUMN arrival_date TEXT",
        "grokai_cost_source": "ALTER TABLE betta_processing_telemetry ADD COLUMN grokai_cost_source TEXT",
    }
    for column, statement in migrations.items():
        if column not in existing:
            con.execute(statement)
    con.commit()
    return con


def as_nonnegative_int(value: object, name: str) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"{name} must be >= 0")
    return parsed


def as_optional_nonnegative_float(value: object, name: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric or null") from exc
    if parsed < 0:
        raise ValueError(f"{name} must be >= 0")
    return parsed


def upsert(con: sqlite3.Connection, record: dict) -> None:
    batch_id = str(record.get("batch_id") or "").strip()
    tank_number = str(record.get("tank_number") or "").strip()
    if not batch_id or not tank_number:
        raise ValueError("batch_id and tank_number are required")

    date_entered = normalize_to_sydney(record.get("date_entered"))
    arrival_date = str(record.get("arrival_date") or "").strip() or None
    tokens_input = as_nonnegative_int(record.get("tokens_input"), "tokens_input")
    tokens_output = as_nonnegative_int(record.get("tokens_output"), "tokens_output")
    grokai_cost = as_optional_nonnegative_float(record.get("grokai_cost"), "grokai_cost")
    currency = str(record.get("grokai_cost_currency") or "USD").strip().upper()
    cost_source = str(record.get("grokai_cost_source") or "").strip() or None
    updated_at = sydney_now()

    con.execute(
        """
        INSERT INTO betta_processing_telemetry (
            batch_id, tank_number, date_entered, arrival_date, tokens_input, tokens_output,
            grokai_cost, grokai_cost_currency, grokai_cost_source, provider, model,
            product_id, title, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(batch_id, tank_number) DO UPDATE SET
            date_entered=excluded.date_entered,
            arrival_date=excluded.arrival_date,
            tokens_input=excluded.tokens_input,
            tokens_output=excluded.tokens_output,
            grokai_cost=excluded.grokai_cost,
            grokai_cost_currency=excluded.grokai_cost_currency,
            grokai_cost_source=excluded.grokai_cost_source,
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
            arrival_date,
            tokens_input,
            tokens_output,
            grokai_cost,
            currency,
            cost_source,
            record.get("provider"),
            record.get("model"),
            record.get("product_id"),
            record.get("title"),
            updated_at,
        ),
    )
    con.commit()


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def usage_from_call(call: dict) -> tuple[int, int]:
    total_in = total_out = 0
    usage_records = []
    if isinstance(call.get("usage"), dict):
        usage_records.append(call["usage"])
    for attempt in call.get("attempts", []) or []:
        if isinstance(attempt, dict) and isinstance(attempt.get("usage"), dict):
            usage_records.append(attempt["usage"])
    for usage in usage_records:
        total_in += as_nonnegative_int(usage.get("tokens_input", usage.get("input_tokens", usage.get("prompt_tokens", 0))), "tokens_input")
        total_out += as_nonnegative_int(usage.get("tokens_output", usage.get("output_tokens", usage.get("completion_tokens", 0))), "tokens_output")
    return total_in, total_out


def earliest_entry_timestamp(item: dict) -> str:
    for candidate in (
        item.get("date_entered"),
        item.get("source", {}).get("date_entered"),
        item.get("source", {}).get("saved_at"),
    ):
        if candidate:
            return normalize_to_sydney(candidate)
    history = item.get("history") or []
    timestamps = [entry.get("at") for entry in history if isinstance(entry, dict) and entry.get("at")]
    if timestamps:
        return normalize_to_sydney(timestamps[0])
    return sydney_now()


def build_from_ledger(ledger: dict, item_id: str, grok_records: list[dict]) -> dict:
    item = next((entry for entry in ledger.get("items", []) if entry.get("id") == item_id), None)
    if item is None:
        raise ValueError(f"unknown item/tank: {item_id}")

    catalogue = item.get("catalogue", {})
    calls = [catalogue.get("evidence"), item.get("image_qa", {}).get("visual")]
    tokens_input = tokens_output = 0
    providers: set[str] = set()
    models: set[str] = set()

    for call in calls:
        if not isinstance(call, dict):
            continue
        incoming, outgoing = usage_from_call(call)
        tokens_input += incoming
        tokens_output += outgoing
        if call.get("provider"):
            providers.add(str(call["provider"]))
        if call.get("model"):
            models.add(str(call["model"]))
        for attempt in call.get("attempts", []) or []:
            model = attempt.get("model") if isinstance(attempt, dict) else None
            if model:
                models.add(str(model))

    known_grok_costs: list[float] = []
    grok_sources: set[str] = set()
    grok_currency = "USD"
    for record in grok_records:
        tokens_input += as_nonnegative_int(record.get("tokens_input"), "tokens_input")
        tokens_output += as_nonnegative_int(record.get("tokens_output"), "tokens_output")
        if record.get("provider"):
            providers.add(str(record["provider"]))
        if record.get("model"):
            models.add(str(record["model"]))
        cost = as_optional_nonnegative_float(record.get("grokai_cost"), "grokai_cost")
        source = str(record.get("grokai_cost_source") or record.get("usage", {}).get("cost_source") or "unavailable")
        grok_sources.add(source)
        if record.get("grokai_cost_currency"):
            grok_currency = str(record["grokai_cost_currency"]).upper()
        if cost is not None:
            known_grok_costs.append(cost)

    if known_grok_costs:
        grok_cost: float | None = sum(known_grok_costs)
        known_sources = {source for source in grok_sources if source != "unavailable"}
        if len(known_sources) > 1:
            grok_cost_source = "mixed"
        elif known_sources:
            grok_cost_source = next(iter(known_sources))
        else:
            grok_cost_source = "unavailable"
    else:
        grok_cost = None
        grok_cost_source = "unavailable"

    return {
        "batch_id": str(ledger.get("batch_id") or ""),
        "tank_number": item_id,
        "date_entered": earliest_entry_timestamp(item),
        "arrival_date": catalogue.get("photo_date"),
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "grokai_cost": grok_cost,
        "grokai_cost_currency": grok_currency,
        "grokai_cost_source": grok_cost_source,
        "provider": ",".join(sorted(providers)) or None,
        "model": ",".join(sorted(models)) or None,
        "product_id": item.get("product", {}).get("id"),
        "title": catalogue.get("title"),
    }


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

    p = sub.add_parser("from-ledger")
    p.add_argument("--ledger", type=Path, required=True)
    p.add_argument("--item", required=True, help="Tank/item id")
    p.add_argument("--grok-record", action="append", type=Path, default=[])

    p = sub.add_parser("export")
    p.add_argument("--csv", type=Path, required=True)

    p = sub.add_parser("show")
    p.add_argument("--tank")

    args = parser.parse_args()
    try:
        con = connect(args.db)
        if args.cmd == "record":
            record = json.loads(args.json)
            upsert(con, record)
            print(json.dumps(record, sort_keys=True))
        elif args.cmd == "from-ledger":
            record = build_from_ledger(load_json(args.ledger), args.item, [load_json(path) for path in args.grok_record])
            upsert(con, record)
            print(json.dumps(record, sort_keys=True))
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
    except (ValueError, json.JSONDecodeError, sqlite3.Error, OSError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
