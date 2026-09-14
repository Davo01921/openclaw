#!/usr/bin/env python3
"""Run independent Betta vision jobs concurrently with bounded workers."""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from vision_review import run_review


def process(job: dict, agent: str, models: list[str]) -> dict:
    job_id = job.get("id")
    mode = job.get("mode")
    files = [Path(value) for value in job.get("files", [])]
    expected = 1 if mode == "catalogue" else 3 if mode == "qa" else 0
    if not job_id or len(files) != expected or not all(path.is_file() for path in files):
        return {"id": job_id, "ok": False, "error": "invalid job or files"}
    try:
        return {"id": job_id, "ok": True, "evidence": run_review(files, mode, agent, models)}
    except Exception as exc:
        return {"id": job_id, "ok": False, "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--agent", default="fred")
    parser.add_argument("--models", default=os.getenv("BETTA_VISION_MODELS", ""))
    args = parser.parse_args()
    jobs = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(jobs, list) or not jobs:
        print("manifest must be a non-empty JSON array", file=sys.stderr)
        return 2
    workers = max(1, min(args.workers, 4))
    models = [value.strip() for value in args.models.split(",") if value.strip()]
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(process, job, args.agent, models): index for index, job in enumerate(jobs)}
        for future in as_completed(futures):
            results.append((futures[future], future.result()))
    ordered = [result for _, result in sorted(results)]
    print(json.dumps(ordered, sort_keys=True))
    return 0 if all(result["ok"] for result in ordered) else 2


if __name__ == "__main__":
    raise SystemExit(main())
