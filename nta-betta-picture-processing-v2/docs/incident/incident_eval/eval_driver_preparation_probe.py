#!/usr/bin/env python3
"""A5 preparation-stage probe: REAL vision preflight + prep-QA (2 live calls).

Identification is deliberately mocked to A2's RECORDED label-crop reading
(tank 2BT23, date 14/10/2026, confidences 0.99/0.96) purely to let the pipeline
reach the prepared-image stage on the genuine incident photo; the preflight and
prep-QA calls on the RAW incident bytes are REAL.  The mocked identification is
recorded as such and is never presented as OCR evidence.

Stops at AWAITING_AUTHORISATION (paid generation not authorised).
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
ROOT = Path("/private/var/folders/f0/ncwpvltd3_sfbjtbnct70dnm0000gn/T/opencode/incident-eval/probe")
EXPECTED_RAW_SHA = "6e4a4f573f8cfc829218f798eeb5b45cd08803689d31d7db6fce4920cdca9ca9"

sys.path.insert(0, str(REPO / "scripts"))

import betta_batches  # noqa: E402
import betta_adapters  # noqa: E402
import betta_budget  # noqa: E402
import betta_policy  # noqa: E402
import betta_process  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def routing(provider="mock-router", model="mock-vision"):
    route = f"{provider}/{model}"
    return {
        "class": "STANDARD", "authority": "adaptive-model-router/v2.1",
        "requested_route": route, "eligible_routes": [route],
        "actual_provider": provider, "actual_model": model,
        "fallback_used": False, "execution_attested": True,
    }


def main() -> int:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    intake = ROOT / "intake"
    batches_root = ROOT / "batches"
    evidence_dir = ROOT / "evidence"
    for path in (intake, batches_root, evidence_dir):
        path.mkdir(parents=True, exist_ok=True)

    raw_sha = sha256(FIXTURE)
    assert raw_sha == EXPECTED_RAW_SHA, raw_sha
    source = intake / FIXTURE.name
    shutil.copy2(FIXTURE, source)

    batch = betta_batches.create_batch(batches_root, label="incident-prep-probe")
    batch_id, batch_dir = batch["batch_id"], Path(batch["path"])
    selected = [{"path": str(source), "sha256": raw_sha, "size": source.stat().st_size}]
    sources_path = batch_dir / "state" / "sources.json"
    sources_path.write_text(json.dumps({
        "schema": "nta-betta-bau-sources-v1", "dispatcher_owned": True,
        "batch_id": batch_id, "selected_at": datetime.now(timezone.utc).isoformat(),
        "selected_sources": selected,
    }), encoding="utf-8")
    os.chmod(sources_path, 0o444)

    budget = betta_budget.GenerationBudget(batch_dir / "state" / "gen-budget.json",
                                           batch_id=batch_id)
    policy = betta_policy.StandingPolicy(betta_policy.default_policy())
    assert policy.paid_generation_authorised() is False

    now = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731

    def catalogue(files):
        # MOCKED identification (A2 recorded label-crop values) - plumbing only.
        return {
            "provider": "mock-router", "model": "mock-vision", "call_id": "probe-catalogue",
            "timestamp": now(), "input_hashes": [sha256(files[0])], "routing": routing(),
            "usage": {},
            "output": {"tank_id": "2BT23", "photo_date": "2026-10-14",
                       "tank_confidence": 0.99, "date_confidence": 0.96,
                       "one_fish_visible": True, "fish_name": "Pastel Pink",
                       "tail_type": "Halfmoon", "sex": "Male",
                       "uncertainty_reasons": []},
        }

    def label(files):
        # MOCKED corroboration read (A2 recorded label-crop values).
        return {
            "provider": "mock-router", "model": "mock-vision", "call_id": "probe-label",
            "timestamp": now(), "input_hashes": [sha256(files[0])], "routing": routing(),
            "usage": {},
            "output": {"tank_id": "2BT23", "tank_confidence": 0.99,
                       "photo_date": "14/10/2026", "date_confidence": 0.96,
                       "visible_price": "35", "reasons": []},
        }

    adapters = betta_adapters.make_adapters(
        batch_id=batch_id, batch_dir=batch_dir, intake_dir=intake,
        telemetry_db=ROOT / "telemetry.sqlite3", policy=policy,
        live_shopify=False, live_generation=False,
        runners={"catalogue": catalogue, "label": label},
        processed_registry=ROOT / "processed-registry.sqlite3",
        budget=budget, selected_sources=selected,
    )
    result = betta_process.process_batch(batch_dir, batch_id, adapters=adapters, policy=policy)

    state = json.loads((batch_dir / "state" / "process.json").read_text())
    shutil.copy2(batch_dir / "state" / "process.json", evidence_dir / "process-state.json")
    entry = next(iter(state["fish"].values()))
    copied = {}
    for name, path_text in (
        ("preparation", entry.get("working_receipt_path")),
        ("catalogue", entry.get("catalogue_evidence_path")),
        ("label_corroboration",
         ((entry.get("label_reads") or {}).get("crop") or {}).get("receipt_path")),
    ):
        if path_text and Path(path_text).is_file():
            target = evidence_dir / f"{name}-receipt.json"
            shutil.copy2(path_text, target)
            copied[name] = {"source": str(path_text), "sha256": sha256(Path(path_text))}
    working = entry.get("working_input_path")
    working_sha = entry.get("working_input_sha256")
    dimensions = None
    if working and Path(working).is_file():
        from PIL import Image
        with Image.open(working) as image:
            dimensions = list(image.size)

    summary = {
        "batch_id": batch_id, "batch_dir": str(batch_dir), "result": result,
        "probe_note": ("identification mocked to A2's recorded label-crop values; "
                       "preflight and prep-QA on the raw incident bytes are REAL calls"),
        "raw_source": {"path": str(source), "sha256_before": raw_sha,
                       "sha256_after": sha256(source),
                       "unchanged": raw_sha == sha256(source)},
        "entry": {
            "tank_id": entry.get("tank_id"), "photo_date": entry.get("photo_date"),
            "status": entry.get("status"), "prep_status": entry.get("prep_status"),
            "notes": entry.get("notes"), "label_reads": entry.get("label_reads"),
            "working_input_path": working, "working_input_sha256": working_sha,
            "working_dimensions": dimensions,
            "working_sha256_recomputed": (sha256(Path(working))
                                          if working and Path(working).is_file() else None),
        },
        "receipt_copies": copied,
    }
    (evidence_dir / "probe-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": result, "status": entry.get("status"),
                      "prep_status": entry.get("prep_status"),
                      "notes": entry.get("notes")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
