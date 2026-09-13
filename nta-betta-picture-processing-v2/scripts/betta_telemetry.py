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
    onboarding_started_at TEXT,
    shopify_verified_at TEXT,
    onboarding_seconds REAL,
    archive_completed_at TEXT,
    end_to_archive_seconds REAL,
    model_calls INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    grok_calls INTEGER NOT NULL DEFAULT 0,
    grok_cost_unknown_calls INTEGER NOT NULL DEFAULT 0,
    slowest_state TEXT,
    slowest_state_seconds REAL,
    state_durations_json TEXT,
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
    "onboarding_started_at",
    "shopify_verified_at",
    "onboarding_seconds",
    "archive_completed_at",
    "end_to_archive_seconds",
    "model_calls",
    "retry_count",
    "grok_calls",
    "grok_cost_unknown_calls",
    "slowest_state",
    "slowest_state_seconds",
    "state_durations_json",
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

MIGRATIONS = {
    "arrival_date": "ALTER TABLE betta_processing_telemetry ADD COLUMN arrival_date TEXT",
    "grokai_cost_source": "ALTER TABLE betta_processing_telemetry ADD COLUMN grokai_cost_source TEXT",
    "onboarding_started_at": "ALTER TABLE betta_processing_telemetry ADD COLUMN onboarding_started_at TEXT",
    "shopify_verified_at": "ALTER TABLE betta_processing_telemetry ADD COLUMN shopify_verified_at TEXT",
    "onboarding_seconds": "ALTER TABLE betta_processing_telemetry ADD COLUMN onboarding_seconds REAL",
    "archive_completed_at": "ALTER TABLE betta_processing_telemetry ADD COLUMN archive_completed_at TEXT",
    "end_to_archive_seconds": "ALTER TABLE betta_processing_telemetry ADD COLUMN end_to_archive_seconds REAL",
    "model_calls": "ALTER TABLE betta_processing_telemetry ADD COLUMN model_calls INTEGER NOT NULL DEFAULT 0",
    "retry_count": "ALTER TABLE betta_processing_telemetry ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0",
    "grok_calls": "ALTER TABLE betta_processing_telemetry ADD COLUMN grok_calls INTEGER NOT NULL DEFAULT 0",
    "grok_cost_unknown_calls": "ALTER TABLE betta_processing_telemetry ADD COLUMN grok_cost_unknown_calls INTEGER NOT NULL DEFAULT 0",
    "slowest_state": "ALTER TABLE betta_processing_telemetry ADD COLUMN slowest_state TEXT",
    "slowest_state_seconds": "ALTER TABLE betta_processing_telemetry ADD COLUMN slowest_state_seconds REAL",
    "state_durations_json": "ALTER TABLE betta_processing_telemetry ADD COLUMN state_durations_json TEXT",
}


def sydney_now() -> str:
    return datetime.now(SYDNEY).isoformat()


def parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SYDNEY)
    return parsed.astimezone(SYDNEY)


def normalize_to_sydney(value: object) -> str:
    parsed = parse_datetime(value)
    return parsed.isoformat() if parsed else (str(value or "").strip() or sydney_now())


def seconds_between(start: object, end: object) -> float | None:
    start_dt = parse_datetime(start)
    end_dt = parse_datetime(end)
    if start_dt is None or end_dt is None:
        return None
    seconds = (end_dt - start_dt).total_seconds()
    return max(0.0, seconds)


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute(SCHEMA)
    existing = {row[1] for row in con.execute("PRAGMA table_info(betta_processing_telemetry)")}
    for column, statement in MIGRATIONS.items():
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

    values = {
        "batch_id": batch_id,
        "tank_number": tank_number,
        "date_entered": normalize_to_sydney(record.get("date_entered")),
        "arrival_date": str(record.get("arrival_date") or "").strip() or None,
        "onboarding_started_at": normalize_to_sydney(record.get("onboarding_started_at")) if record.get("onboarding_started_at") else None,
        "shopify_verified_at": normalize_to_sydney(record.get("shopify_verified_at")) if record.get("shopify_verified_at") else None,
        "onboarding_seconds": as_optional_nonnegative_float(record.get("onboarding_seconds"), "onboarding_seconds"),
        "archive_completed_at": normalize_to_sydney(record.get("archive_completed_at")) if record.get("archive_completed_at") else None,
        "end_to_archive_seconds": as_optional_nonnegative_float(record.get("end_to_archive_seconds"), "end_to_archive_seconds"),
        "model_calls": as_nonnegative_int(record.get("model_calls"), "model_calls"),
        "retry_count": as_nonnegative_int(record.get("retry_count"), "retry_count"),
        "grok_calls": as_nonnegative_int(record.get("grok_calls"), "grok_calls"),
        "grok_cost_unknown_calls": as_nonnegative_int(record.get("grok_cost_unknown_calls"), "grok_cost_unknown_calls"),
        "slowest_state": str(record.get("slowest_state") or "").strip() or None,
        "slowest_state_seconds": as_optional_nonnegative_float(record.get("slowest_state_seconds"), "slowest_state_seconds"),
        "state_durations_json": record.get("state_durations_json"),
        "tokens_input": as_nonnegative_int(record.get("tokens_input"), "tokens_input"),
        "tokens_output": as_nonnegative_int(record.get("tokens_output"), "tokens_output"),
        "grokai_cost": as_optional_nonnegative_float(record.get("grokai_cost"), "grokai_cost"),
        "grokai_cost_currency": str(record.get("grokai_cost_currency") or "USD").strip().upper(),
        "grokai_cost_source": str(record.get("grokai_cost_source") or "").strip() or None,
        "provider": record.get("provider"),
        "model": record.get("model"),
        "product_id": record.get("product_id"),
        "title": record.get("title"),
        "updated_at": sydney_now(),
    }

    columns = FIELDS
    placeholders = ",".join("?" for _ in columns)
    updates = ",".join(f"{column}=excluded.{column}" for column in columns if column not in ("batch_id", "tank_number"))
    con.execute(
        f"INSERT INTO betta_processing_telemetry ({','.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT(batch_id, tank_number) DO UPDATE SET {updates}",
        tuple(values[column] for column in columns),
    )
    con.commit()


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def usage_from_call(call: dict) -> tuple[int, int, int, int]:
    """Return input tokens, output tokens, call count, retry count."""
    total_in = total_out = 0
    attempts = call.get("attempts", []) or []
    usage_records = []
    if isinstance(call.get("usage"), dict):
        usage_records.append(call["usage"])
    for attempt in attempts:
        if isinstance(attempt, dict) and isinstance(attempt.get("usage"), dict):
            usage_records.append(attempt["usage"])
    for usage in usage_records:
        total_in += as_nonnegative_int(usage.get("tokens_input", usage.get("input_tokens", usage.get("prompt_tokens", 0))), "tokens_input")
        total_out += as_nonnegative_int(usage.get("tokens_output", usage.get("output_tokens", usage.get("completion_tokens", 0))), "tokens_output")
    return total_in, total_out, 1 + len(attempts), len(attempts)


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


def transition_time(item: dict, target: str) -> str | None:
    for entry in item.get("history", []) or []:
        if isinstance(entry, dict) and entry.get("to") == target and entry.get("at"):
            return normalize_to_sydney(entry["at"])
    return None


def state_durations(item: dict) -> dict[str, float]:
    """Approximate wall-clock time spent in each ledger state from transition history."""
    events = []
    for entry in item.get("history", []) or []:
        if not isinstance(entry, dict) or not entry.get("to") or not entry.get("at"):
            continue
        parsed = parse_datetime(entry["at"])
        if parsed:
            events.append((parsed, str(entry["to"])))
    events.sort(key=lambda pair: pair[0])
    durations: dict[str, float] = {}
    for index in range(len(events) - 1):
        started, state = events[index]
        ended = events[index + 1][0]
        durations[state] = durations.get(state, 0.0) + max(0.0, (ended - started).total_seconds())
    return durations


def build_from_ledger(ledger: dict, item_id: str, grok_records: list[dict]) -> dict:
    item = next((entry for entry in ledger.get("items", []) if entry.get("id") == item_id), None)
    if item is None:
        raise ValueError(f"unknown item/tank: {item_id}")

    catalogue = item.get("catalogue", {})
    calls = [catalogue.get("evidence"), item.get("image_qa", {}).get("visual")]
    tokens_input = tokens_output = model_calls = retry_count = 0
    providers: set[str] = set()
    models: set[str] = set()

    for call in calls:
        if not isinstance(call, dict):
            continue
        incoming, outgoing, calls_used, retries = usage_from_call(call)
        tokens_input += incoming
        tokens_output += outgoing
        model_calls += calls_used
        retry_count += retries
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
    unknown_grok_cost_calls = 0
    for record in grok_records:
        tokens_input += as_nonnegative_int(record.get("tokens_input"), "tokens_input")
        tokens_output += as_nonnegative_int(record.get("tokens_output"), "tokens_output")
        model_calls += 1
        if record.get("provider"):
            providers.add(str(record["provider"]))
        if record.get("model"):
            models.add(str(record["model"]))
        cost = as_optional_nonnegative_float(record.get("grokai_cost"), "grokai_cost")
        source = str(record.get("grokai_cost_source") or record.get("usage", {}).get("cost_source") or "unavailable")
        grok_sources.add(source)
        if record.get("grokai_cost_currency"):
            grok_currency = str(record["grokai_cost_currency"]).upper()
        if cost is None:
            unknown_grok_cost_calls += 1
        else:
            known_grok_costs.append(cost)

    if grok_records and unknown_grok_cost_calls:
        grok_cost: float | None = None
        grok_cost_source = "incomplete"
    elif grok_records:
        grok_cost = sum(known_grok_costs)
        known_sources = {source for source in grok_sources if source != "unavailable"}
        grok_cost_source = "mixed" if len(known_sources) > 1 else (next(iter(known_sources)) if known_sources else "unavailable")
    else:
        grok_cost = 0.0
        grok_cost_source = "not_used"

    onboarding_started_at = earliest_entry_timestamp(item)
    verified_at = transition_time(item, "VERIFIED")
    archived_at = transition_time(item, "ARCHIVED")
    durations = state_durations(item)
    slowest_state = max(durations, key=durations.get) if durations else None

    return {
        "batch_id": str(ledger.get("batch_id") or ""),
        "tank_number": item_id,
        "date_entered": onboarding_started_at,
        "arrival_date": catalogue.get("photo_date"),
        "onboarding_started_at": onboarding_started_at,
        "shopify_verified_at": verified_at,
        "onboarding_seconds": seconds_between(onboarding_started_at, verified_at),
        "archive_completed_at": archived_at,
        "end_to_archive_seconds": seconds_between(onboarding_started_at, archived_at),
        "model_calls": model_calls,
        "retry_count": retry_count,
        "grok_calls": len(grok_records),
        "grok_cost_unknown_calls": unknown_grok_cost_calls,
        "slowest_state": slowest_state,
        "slowest_state_seconds": durations.get(slowest_state) if slowest_state else None,
        "state_durations_json": json.dumps(durations, sort_keys=True),
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
