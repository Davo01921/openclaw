#!/usr/bin/env python3
"""Batch-independent Grok hero completion for NTA Betta Processing V2.1.

Works against any batch workspace (see ``betta_batches.py``) regardless of tank
numbers, photograph dates or batch size. Nothing about a previous batch is
hardcoded. Sources are only ever read, never modified.

Pipeline per item:

    source (unchanged) -> clean hero (paid Grok/xAI generation) -> labelled hero

Paid image generation is disabled unless ``--authorise-paid-generation`` is given
by the owner. Without it, an item whose clean hero does not already exist fails
closed and is reported, and no Grok request is made.

Credential: ``grok_hero.py`` resolves the xAI credential from the ``XAI_API_KEY``
environment variable first, then the macOS Keychain item ``nta-betta-xai``. The
credential is never stored, logged or printed here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

_SELF = Path(__file__).resolve()
GENERATOR = _SELF.with_name("grok_hero.py")
MIN_REQUEST_INTERVAL = 30.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------- #
# Batch-independent path resolution
# --------------------------------------------------------------------------- #
def resolve_paths(batch_dir: Path, reconciled: Path | None = None,
                  output: Path | None = None) -> dict:
    batch_dir = Path(batch_dir)
    if not batch_dir.is_dir():
        raise ValueError(f"batch workspace not found: {batch_dir}")
    evidence = batch_dir / "evidence"
    return {
        "batch_dir": batch_dir,
        "reconciled": Path(reconciled) if reconciled else evidence / "betta-labels-reconciled.json",
        "hero_dir": evidence / "heroes",
        "results": Path(output) if output else batch_dir / "reports" / "betta-hero-batch-results.json",
    }


def _default_generate(source: Path, clean: Path) -> None:
    """Run the fixed Grok/xAI specialist generator (paid). Rate-limited."""
    clean.parent.mkdir(parents=True, exist_ok=True)
    delays = [0, 60, 120, 240]
    last_start = getattr(_default_generate, "_last_start", -1_000_000.0)
    for retry_delay in delays:
        if retry_delay:
            time.sleep(retry_delay)
        wait = max(0.0, MIN_REQUEST_INTERVAL - (time.monotonic() - last_start))
        if wait:
            time.sleep(wait)
        _default_generate._last_start = time.monotonic()
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--source", str(source), "--output", str(clean)],
            capture_output=True, text=True, timeout=240,
        )
        if result.returncode == 0:
            return
        if "HTTP Error 429" not in result.stderr:
            raise RuntimeError(f"Grok generation failed: {result.stderr[-500:]}")
    raise RuntimeError("Grok rate limit persisted after all attempts")


def _default_render(clean: Path, final: Path, tank: str, photo_date: str) -> None:
    from render_betta_label import render  # lazy: only needed for real rendering
    render(clean, final, tank, photo_date)


def process_item(item: dict, hero_dir: Path, *, authorise_paid_generation: bool,
                 generate=_default_generate, render=_default_render) -> dict:
    """Process one reconciled item. Returns a result record; failed items never abort the batch."""
    tank = item["tank_id"]
    source = Path(item["source_path"])
    photo_date = item["photo_date"]
    clean = Path(hero_dir) / f"{tank}-clean.png"
    final = Path(hero_dir) / f"{tank}.png"

    if not source.is_file():
        raise RuntimeError(f"original source missing for {tank}: {source}")
    if item.get("source_sha256") and sha256_file(source) != item["source_sha256"]:
        raise RuntimeError(f"source hash mismatch for {tank}")

    generated = False
    if not clean.is_file():
        if not authorise_paid_generation:
            return {"tank": tank, "status": "PAID_GENERATION_NOT_AUTHORISED",
                    "clean_path": str(clean), "final_path": str(final)}
        generate(source, clean)
        generated = True
        if not clean.is_file():
            raise RuntimeError(f"generator produced no clean hero for {tank}")

    if not final.is_file():
        render(clean, final, tank, photo_date)

    return {
        "tank": tank,
        "source_sha256": sha256_file(source),
        "clean_sha256": sha256_file(clean),
        "final_sha256": sha256_file(final),
        "clean_path": str(clean),
        "final_path": str(final),
        "generated": generated,
        "status": "GENERATED_QA_PENDING" if generated else "READY_QA_PENDING",
    }


def finish_heroes(batch_dir: Path, *, authorise_paid_generation: bool,
                  reconciled: Path | None = None, output: Path | None = None,
                  generate=_default_generate, render=_default_render) -> dict:
    paths = resolve_paths(batch_dir, reconciled, output)
    items = json.loads(Path(paths["reconciled"]).read_text(encoding="utf-8"))
    if isinstance(items, dict):
        items = items.get("items", [])
    if not isinstance(items, list):
        raise ValueError("reconciled labels file must contain a list of items")

    results = []
    for item in items:
        try:
            results.append(process_item(
                item, paths["hero_dir"],
                authorise_paid_generation=authorise_paid_generation,
                generate=generate, render=render,
            ))
        except Exception as exc:  # one bad fish must not abort the batch
            results.append({"tank": item.get("tank_id"), "status": "FAILED", "error": str(exc)})

    output_path = Path(paths["results"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    completed = sum(1 for r in results if r["status"] in ("GENERATED_QA_PENDING", "READY_QA_PENDING"))
    return {"batch_dir": str(paths["batch_dir"]), "results_path": str(output_path),
            "total": len(items), "completed": completed, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-dir", type=Path, required=True,
                        help="Batch workspace created by betta_batches.py new")
    parser.add_argument("--reconciled", type=Path, default=None,
                        help="Default: <batch-dir>/evidence/betta-labels-reconciled.json")
    parser.add_argument("--output", type=Path, default=None,
                        help="Default: <batch-dir>/reports/betta-hero-batch-results.json")
    parser.add_argument("--authorise-paid-generation", action="store_true",
                        help="Owner approval required before any paid Grok/xAI generation")
    args = parser.parse_args()
    try:
        summary = finish_heroes(
            args.batch_dir,
            authorise_paid_generation=args.authorise_paid_generation,
            reconciled=args.reconciled, output=args.output,
        )
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
