#!/usr/bin/env python3
"""Summarise NTA Betta onboarding efficiency from the telemetry SQLite database."""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

DEFAULT_DB = Path.home() / "Documents" / "Betta Processing" / "betta-telemetry.sqlite3"


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--last", type=int, default=20, help="Most recent rows to include; 0 means all")
    args = parser.parse_args()

    if not args.db.is_file():
        print(json.dumps({"error": f"telemetry database not found: {args.db}"}))
        return 2

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    sql = "SELECT * FROM betta_processing_telemetry ORDER BY date_entered DESC"
    params: tuple[int, ...] = ()
    if args.last > 0:
        sql += " LIMIT ?"
        params = (args.last,)
    rows = list(con.execute(sql, params))
    con.close()

    durations = [float(row["onboarding_seconds"]) for row in rows if row["onboarding_seconds"] is not None]
    model_calls = [int(row["model_calls"] or 0) for row in rows]
    retries = [int(row["retry_count"] or 0) for row in rows]
    tokens_in = [int(row["tokens_input"] or 0) for row in rows]
    tokens_out = [int(row["tokens_output"] or 0) for row in rows]
    known_costs = [float(row["grokai_cost"]) for row in rows if row["grokai_cost"] is not None]
    unknown_cost_rows = sum(1 for row in rows if row["grokai_cost_source"] in ("incomplete", "unavailable"))

    state_totals: defaultdict[str, list[float]] = defaultdict(list)
    for row in rows:
        raw = row["state_durations_json"]
        if not raw:
            continue
        try:
            durations_by_state = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(durations_by_state, dict):
            continue
        for state, seconds in durations_by_state.items():
            try:
                state_totals[str(state)].append(float(seconds))
            except (TypeError, ValueError):
                continue

    state_summary = sorted(
        (
            {
                "state": state,
                "samples": len(values),
                "average_seconds": round(statistics.mean(values), 2),
                "total_seconds": round(sum(values), 2),
            }
            for state, values in state_totals.items()
        ),
        key=lambda item: item["total_seconds"],
        reverse=True,
    )

    result = {
        "sample_size": len(rows),
        "verified_duration_samples": len(durations),
        "onboarding_seconds": {
            "average": round(statistics.mean(durations), 2) if durations else None,
            "median": round(statistics.median(durations), 2) if durations else None,
            "p90": round(percentile(durations, 0.90), 2) if durations else None,
            "fastest": round(min(durations), 2) if durations else None,
            "slowest": round(max(durations), 2) if durations else None,
        },
        "average_model_calls": round(statistics.mean(model_calls), 2) if model_calls else 0,
        "average_retries": round(statistics.mean(retries), 2) if retries else 0,
        "fish_with_retries": sum(1 for value in retries if value > 0),
        "average_tokens_input": round(statistics.mean(tokens_in), 2) if tokens_in else 0,
        "average_tokens_output": round(statistics.mean(tokens_out), 2) if tokens_out else 0,
        "known_grok_cost_total": round(sum(known_costs), 6),
        "unknown_or_incomplete_grok_cost_rows": unknown_cost_rows,
        "top_time_states": state_summary[:5],
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
