#!/usr/bin/env python3
"""A5 real pipeline evaluation v2 — incident photo on POST-REFINEMENT code.

Re-runs the sandbox pipeline against the current worktree (HEAD includes the
gate-aware retry refinement): intake -> REAL catalogue read -> REAL focused
label-crop retry (expected RETRY_ACCEPTED: the below-gate catalogue date cannot
veto the confident crop) -> prepared-image stage (REAL preflight + prep QA) ->
stops at AWAITING_AUTHORISATION (paid generation not authorised).

No Shopify, no Grok, no writes outside the scratch dir.  Bounded live vision
budget: <= 6 calls.  All evidence is written under SCRATCH/evidence for verbatim
archival into docs/incident/incident_eval_v2/.  The v1 archive
(docs/incident/incident_eval/) is never touched.

This driver lives OUTSIDE the scratch root it wipes.
"""

import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# `openclaw` is a node script; keep node reachable for route resolution.
os.environ["PATH"] = os.pathsep.join(
    ["/opt/homebrew/opt/node/bin", "/opt/homebrew/bin", os.environ.get("PATH", "")])

REPO = Path("/Users/davidlo/openclaw-skills-incident-repair/nta-betta-picture-processing-v2")
FIXTURE = REPO / "tests/fixtures/incident_2bt23/incident-photo.png"
SCRATCH = Path("/private/var/folders/f0/ncwpvltd3_sfbjtbnct70dnm0000gn/T/opencode/incident-eval-v2")
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


def main() -> int:
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    intake = SCRATCH / "intake"
    batches_root = SCRATCH / "batches"
    evidence_dir = SCRATCH / "evidence"
    for path in (intake, batches_root, evidence_dir):
        path.mkdir(parents=True, exist_ok=True)

    raw_before = sha256(FIXTURE)
    if raw_before != EXPECTED_RAW_SHA:
        print(json.dumps({"error": "fixture sha mismatch", "observed": raw_before}))
        return 2
    source = intake / FIXTURE.name
    shutil.copy2(FIXTURE, source)

    batch = betta_batches.create_batch(batches_root, label="incident-eval-v2-2bt23")
    batch_id, batch_dir = batch["batch_id"], Path(batch["path"])
    selected = [{"path": str(source), "sha256": raw_before, "size": source.stat().st_size}]
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
    assert policy.paid_generation_authorised() is False
    telemetry_db = SCRATCH / "telemetry.sqlite3"

    adapters = betta_adapters.make_adapters(
        batch_id=batch_id, batch_dir=batch_dir, intake_dir=intake,
        telemetry_db=telemetry_db, policy=policy,
        live_shopify=False, live_generation=False, runners={},
        processed_registry=SCRATCH / "processed-registry.sqlite3",
        budget=budget, selected_sources=selected,
    )
    result = betta_process.process_batch(batch_dir, batch_id, adapters=adapters, policy=policy)

    # -- gather evidence ------------------------------------------------- #
    state = json.loads((batch_dir / "state" / "process.json").read_text())
    shutil.copy2(batch_dir / "state" / "process.json", evidence_dir / "process-state.json")

    entries, receipts = [], {}
    for key, entry in sorted(state.get("fish", {}).items()):
        record = {
            "key": key, "tank_id": entry.get("tank_id"), "photo_date": entry.get("photo_date"),
            "status": entry.get("status"), "notes": entry.get("notes"),
            "uncertain": entry.get("uncertain"), "uncertain_reason": entry.get("uncertain_reason"),
            "identify_reason": entry.get("identify_reason"),
            "catalogue_confidences": entry.get("catalogue_confidences"),
            "label_price_visible": entry.get("label_price_visible"),
            "label_reads": entry.get("label_reads"),
            "source_path": entry.get("source_path"), "source_sha256": entry.get("source_sha256"),
            "prep_status": entry.get("prep_status"),
            "working_input_path": entry.get("working_input_path"),
            "working_input_sha256": entry.get("working_input_sha256"),
            "catalogue_evidence_path": entry.get("catalogue_evidence_path"),
            "catalogue_evidence_sha256": entry.get("catalogue_evidence_sha256"),
        }
        entries.append(record)
        for name, path_text in (
            ("catalogue", entry.get("catalogue_evidence_path")),
            ("label_retry",
             ((entry.get("label_reads") or {}).get("crop") or {}).get("receipt_path")),
            ("preparation", entry.get("working_receipt_path")),
        ):
            if path_text and Path(path_text).is_file():
                target = evidence_dir / f"{name}-receipt.json"
                shutil.copy2(path_text, target)
                receipts[name] = {"source": str(path_text), "copy": str(target),
                                  "sha256": sha256(Path(path_text))}
        crop = ((entry.get("label_reads") or {}).get("crop") or {})
        if crop.get("crop_path") and Path(crop["crop_path"]).is_file():
            shutil.copy2(crop["crop_path"], evidence_dir / "label-crop.png")
            receipts["label_crop"] = {
                "source": crop.get("crop_path"),
                "copy": str(evidence_dir / "label-crop.png"),
                "sha256": sha256(Path(crop["crop_path"])),
            }
        working = entry.get("working_input_path")
        if working and Path(working).is_file():
            record["working_sha256_recomputed"] = sha256(Path(working))
            try:
                from PIL import Image
                with Image.open(working) as image:
                    record["working_dimensions"] = list(image.size)
            except Exception as exc:
                record["working_dimensions"] = f"unreadable: {exc}"

    # Verbatim call inventory (the only live-attestation source beyond receipts).
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
        "code_revision": {
            "head_commit": __import__("subprocess").run(
                ["git", "-C", str(REPO.parent), "rev-parse", "HEAD"],
                capture_output=True, text=True).stdout.strip(),
            "worktree_dirty": bool(__import__("subprocess").run(
                ["git", "-C", str(REPO.parent), "status", "--porcelain"],
                capture_output=True, text=True).stdout.strip()),
        },
        "policy": {
            "enabled": policy.data.get("enabled"),
            "automatic_batch_authorisation": policy.data.get("automatic_batch_authorisation"),
            "paid_generation_authorised": policy.paid_generation_authorised(),
        },
        "live_flags": {"live_shopify": False, "live_generation": False},
        "raw_source": {
            "path": str(source), "sha256_before": raw_before, "sha256_after": sha256(source),
            "size_bytes": source.stat().st_size, "unchanged": raw_before == sha256(source),
        },
        "fixture": {"path": str(FIXTURE), "sha256": raw_before, "sha256_after_run": sha256(FIXTURE)},
        "entries": entries, "receipt_copies": receipts, "calls": calls,
        "budget_after": budget.summary(),
    }
    (evidence_dir / "eval-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    entry = entries[0] if entries else {}
    print(json.dumps({
        "result": result,
        "entry": {k: entry.get(k) for k in
                  ("tank_id", "photo_date", "status", "uncertain_reason", "prep_status")},
        "label_reads_status": (entry.get("label_reads") or {}).get("status"),
        "catalogue_confidences": entry.get("catalogue_confidences"),
        "live_calls": [{k: call.get(k) for k in ("stage", "outcome", "provider", "model")}
                       for call in calls],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
