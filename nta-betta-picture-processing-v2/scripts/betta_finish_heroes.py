#!/usr/bin/env python3
"""Complete Grok hero generation for a reconciled Betta batch."""

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from render_betta_label import render

BASE = Path.home() / "Documents/Betta Processing"
HERO_DIR = BASE / "Grok Tests"
RECONCILED = BASE / "betta-labels-reconciled.json"

PYTHON = Path(sys.executable)
GENERATOR = Path(__file__).with_name("grok_hero.py")

HERO_DIR.mkdir(parents=True, exist_ok=True)

MIN_REQUEST_INTERVAL = 30
last_request_start = -float("inf")



def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def process(item):
    tank = item["tank_id"]
    source = Path(item["source_path"])
    date = item["photo_date"]

    clean = HERO_DIR / f"{tank}-clean.png"
    final = HERO_DIR / f"{tank}.png"

    if not source.is_file():
        raise RuntimeError(f"Original missing: {source}")

    if digest(source) != item["source_sha256"]:
        raise RuntimeError(f"Source hash mismatch: {tank}")

    if not clean.exists():
        print(f"{tank}: Generating Grok image...", flush=True)

        delays = [0, 60, 120, 240]

        for attempt, retry_delay in enumerate(delays, 1):
            if retry_delay:
                print(
                    f"{tank}: Rate-limit retry in {retry_delay}s",
                    flush=True,
                )
                time.sleep(retry_delay)

            # Enforce minimum spacing between request starts.
            global last_request_start
            elapsed = time.monotonic() - last_request_start
            wait = max(0, MIN_REQUEST_INTERVAL - elapsed)

            if wait:
                print(
                    f"{tank}: Waiting {wait:.0f}s before Grok request",
                    flush=True,
                )
                time.sleep(wait)

            last_request_start = time.monotonic()

            print(
                f"{tank}: Request attempt {attempt}/{len(delays)}",
                flush=True,
            )

            result = subprocess.run(
                [
                    str(PYTHON),
                    str(GENERATOR),
                    "--source", str(source),
                    "--output", str(clean),
                ],
                capture_output=True,
                text=True,
                timeout=240,
            )

            if result.returncode == 0:
                break

            if "HTTP Error 429" not in result.stderr:
                raise RuntimeError(
                    f"Grok generation failed for {tank}: "
                    f"{result.stderr[-500:]}"
                )
        else:
            raise RuntimeError(
                f"Grok rate limit persisted after {len(delays)} attempts"
            )

        print(f"{tank}: Grok image saved", flush=True)
    else:
        print(f"{tank}: Existing clean image reused", flush=True)

    if not final.exists():
        render(clean, final, tank, date)
        print(f"{tank}: Label added", flush=True)
    else:
        print(f"{tank}: Existing labelled image retained", flush=True)

    return {
        "tank": tank,
        "source_sha256": digest(source),
        "clean_sha256": digest(clean),
        "final_sha256": digest(final),
        "final_path": str(final),
        "status": "GENERATED_QA_PENDING",
    }


def main():
    records = json.loads(RECONCILED.read_text())["items"]
    results = []

    for item in records:
        try:
            result = process(item)
            results.append(result)
            print(f"{item['tank_id']}: COMPLETE", flush=True)
        except Exception as exc:
            print(f"{item['tank_id']}: FAILED — {exc}", flush=True)

    output = BASE / "betta-hero-batch-results.json"
    output.write_text(json.dumps(results, indent=2))

    print(f"\nCompleted: {len(results)}/{len(records)}")
    print("Results:", output)


if __name__ == "__main__":
    main()
