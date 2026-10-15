#!/usr/bin/env python3
"""A5 v2 live identification probe #2 (bounded: at most 2 live vision calls).

Same sandbox method as the v2 identification run, but the prepared-image stage
is mocked so the total live budget stays within the <=6 bound:
  live catalogue read -> live focused crop read (retry or corroboration,
  whichever the current code path requires) -> mocked prepare -> stop at
  AWAITING_AUTHORISATION.

Purpose: try to observe the post-refinement below-gate retry acceptance on a
fresh genuine sample; archive whatever is observed VERBATIM.
"""

import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ["PATH"] = os.pathsep.join(
    ["/opt/homebrew/opt/node/bin", "/opt/homebrew/bin", os.environ.get("PATH", "")])

REPO = Path("/Users/davidlo/openclaw-skills-incident-repair/nta-betta-picture-processing-v2")
FIXTURE = REPO / "tests/fixtures/incident_2bt23/incident-photo.png"
SCRATCH = Path("/private/var/folders/f0/ncwpvltd3_sfbjtbnct70dnm0000gn/T/opencode/incident-eval-v2/probe2")
EXPECTED_RAW_SHA = "6e4a4f573f8cfc829218f798eeb5b45cd08803689d31d7db6fce4920cdca9ca9"

sys.path.insert(0, str(REPO / "scripts"))

import betta_batches  # noqa: E402
import betta_adapters  # noqa: E402
import betta_budget  # noqa: E402
import betta_policy  # noqa: E402
import betta_process  # noqa: E402


def sha256(path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def routing() -> dict:
    return {
        "class": "STANDARD", "authority": "adaptive-model-router/v2.1",
        "requested_route": "mock-router/mock-vision",
        "eligible_routes": ["mock-router/mock-vision"],
        "actual_provider": "mock-router", "actual_model": "mock-vision",
        "fallback_used": False, "execution_attested": True,
    }


def mock_evidence(files, output, call_id) -> dict:
    return {
        "provider": "mock-router", "model": "mock-vision", "call_id": call_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "input_hashes": [sha256(f) for f in files],
        "routing": routing(), "usage": {}, "output": output,
    }


def main() -> int:
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    intake, batches_root, evidence_dir = (SCRATCH / part for part in
                                          ("intake", "batches", "evidence"))
    for path in (intake, batches_root, evidence_dir):
        path.mkdir(parents=True, exist_ok=True)

    raw_sha = sha256(FIXTURE)
    assert raw_sha == EXPECTED_RAW_SHA
    source = intake / FIXTURE.name
    shutil.copy2(FIXTURE, source)

    batch = betta_batches.create_batch(batches_root, label="incident-eval-v2-probe2")
    batch_id, batch_dir = batch["batch_id"], Path(batch["path"])
    selected = [{"path": str(source), "sha256": raw_sha, "size": source.stat().st_size}]
    sources_path = batch_dir / "state" / "sources.json"
    sources_path.write_text(json.dumps({
        "schema": "nta-betta-bau-sources-v1", "dispatcher_owned": True,
        "batch_id": batch_id, "selected_at": datetime.now(timezone.utc).isoformat(),
        "selected_sources": selected,
    }), encoding="utf-8")
    os.chmod(sources_path, 0o444)

    budget = betta_budget.GenerationBudget(
        batch_dir / "state" / "gen-budget.json", batch_id=batch_id)
    policy = betta_policy.StandingPolicy(betta_policy.default_policy())
    telemetry_db = SCRATCH / "telemetry.sqlite3"

    # Only the prepared-image stage is mocked (documented); identification runs
    # live through the strict adapters.
    runners = {
        "vision_preflight": lambda files: mock_evidence(
            files, {"tank_id": "2BT23", "photo_date": "2026-10-14",
                    "tank_confidence": 0.99, "date_confidence": 0.93,
                    "fish_confidence": 0.95, "one_fish_visible": True,
                    "needs_retake": False, "tank_bounds": [0.0, 0.0, 1.0, 1.0],
                    "fish_bounds": [0.25, 0.15, 0.75, 0.85], "debris_boxes": [],
                    "reason": ""}, "probe2-preflight"),
        "vision_prepqa": lambda files: mock_evidence(
            files, {"overall": "PASS", "same_fish": True, "full_fins": True,
                    "faithful_colours": True, "tank_only": True,
                    "lighting_usable": True, "no_identity_alteration": True,
                    "reason": ""}, "probe2-prepqa"),
        "vision_retry_delay_seconds": 0,
    }
    adapters = betta_adapters.make_adapters(
        batch_id=batch_id, batch_dir=batch_dir, intake_dir=intake,
        telemetry_db=telemetry_db, policy=policy,
        live_shopify=False, live_generation=False, runners=runners,
        processed_registry=SCRATCH / "processed-registry.sqlite3",
        budget=budget, selected_sources=selected,
    )
    result = betta_process.process_batch(batch_dir, batch_id, adapters=adapters, policy=policy)

    state = json.loads((batch_dir / "state" / "process.json").read_text())
    shutil.copy2(batch_dir / "state" / "process.json", evidence_dir / "process-state.json")
    entries, receipts = [], {}
    for key, entry in sorted(state.get("fish", {}).items()):
        record = {
            "key": key, "tank_id": entry.get("tank_id"),
            "photo_date": entry.get("photo_date"), "status": entry.get("status"),
            "notes": entry.get("notes"), "uncertain": entry.get("uncertain"),
            "uncertain_reason": entry.get("uncertain_reason"),
            "identify_reason": entry.get("identify_reason"),
            "catalogue_confidences": entry.get("catalogue_confidences"),
            "label_price_visible": entry.get("label_price_visible"),
            "label_reads": entry.get("label_reads"),
            "source_sha256": entry.get("source_sha256"),
            "prep_status": entry.get("prep_status"),
            "catalogue_evidence_path": entry.get("catalogue_evidence_path"),
        }
        entries.append(record)
        for name, path_text in (
            ("catalogue", entry.get("catalogue_evidence_path")),
            ("label", ((entry.get("label_reads") or {}).get("crop") or {}).get("receipt_path")),
        ):
            if path_text and Path(path_text).is_file():
                target = evidence_dir / f"{name}-receipt.json"
                shutil.copy2(path_text, target)
                receipts[name] = {"source": str(path_text), "copy": str(target),
                                  "sha256": sha256(Path(path_text))}
        crop = ((entry.get("label_reads") or {}).get("crop") or {})
        if crop.get("crop_path") and Path(crop["crop_path"]).is_file():
            shutil.copy2(crop["crop_path"], evidence_dir / "label-crop.png")
            receipts["label_crop"] = {"source": crop["crop_path"],
                                      "sha256": sha256(Path(crop["crop_path"]))}

    import sqlite3
    calls = []
    con = sqlite3.connect(telemetry_db)
    try:
        for row in con.execute(
                "SELECT stage, outcome, provider, model, timestamp, detail_json, error "
                "FROM betta_call_telemetry ORDER BY id"):
            calls.append(dict(zip(
                ["stage", "outcome", "provider", "model", "timestamp", "detail_json", "error"],
                row)))
    finally:
        con.close()
    (evidence_dir / "call-inventory.json").write_text(
        json.dumps(calls, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary = {
        "batch_id": batch_id, "batch_dir": str(batch_dir), "result": result,
        "probe_note": ("identification runs LIVE; only the prepared-image stage is "
                       "mocked (probe2-preflight/probe2-prepqa) to stay inside the "
                       "<=6 live-call bound"),
        "raw_source": {"path": str(source), "sha256_before": raw_sha,
                       "sha256_after": sha256(source),
                       "unchanged": raw_sha == sha256(source)},
        "entries": entries, "receipt_copies": receipts, "calls": calls,
        "budget_after": budget.summary(),
    }
    (evidence_dir / "eval-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    entry = entries[0] if entries else {}
    print(json.dumps({
        "result": result,
        "entry": {k: entry.get(k) for k in ("tank_id", "photo_date", "status", "uncertain_reason")},
        "label_reads_status": (entry.get("label_reads") or {}).get("status"),
        "catalogue_confidences": entry.get("catalogue_confidences"),
        "live_calls": [c for c in calls if c.get("provider") == "openai"],
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
