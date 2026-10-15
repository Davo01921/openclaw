#!/usr/bin/env python3
"""A5 real pipeline evaluation for the 2BT23 incident (live vision, <=6 calls).

Sandboxes a full strict-batch run of the genuine incident photo:
  intake -> dual identification (REAL catalogue + cropped-label reads)
  -> prepared-image stage (REAL vision preflight + prep QA)
  -> stops at AWAITING_AUTHORISATION (policy.paid_generation_authorised() False).

No Shopify, no Grok, no writes outside the scratch dir.  All evidence is
written under SCRATCH/evidence for verbatim archival.

This driver lives OUTSIDE the scratch root it wipes.
"""

import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# The attested vision CLI (`openclaw`) is a node script; make node reachable for
# route resolution (betta_vision_route.inspect_live does not harden PATH itself).
os.environ["PATH"] = os.pathsep.join(
    ["/opt/homebrew/opt/node/bin", "/opt/homebrew/bin", os.environ.get("PATH", "")])

REPO = Path("/Users/davidlo/openclaw-skills-incident-repair/nta-betta-picture-processing-v2")
FIXTURE = REPO / "tests/fixtures/incident_2bt23/incident-photo.png"
SCRATCH = Path("/private/var/folders/f0/ncwpvltd3_sfbjtbnct70dnm0000gn/T/opencode/incident-eval")
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
    size = source.stat().st_size

    batch = betta_batches.create_batch(batches_root, label="incident-eval-2bt23")
    batch_id = batch["batch_id"]
    batch_dir = Path(batch["path"])

    selected = [{"path": str(source), "sha256": raw_before, "size": size}]
    sources_path = batch_dir / "state" / "sources.json"
    sources_path.write_text(json.dumps({
        "schema": "nta-betta-bau-sources-v1", "dispatcher_owned": True,
        "batch_id": batch_id,
        "selected_at": datetime.now(timezone.utc).isoformat(),
        "selected_sources": selected,
    }, indent=2), encoding="utf-8")
    os.chmod(sources_path, 0o444)

    budget = betta_budget.GenerationBudget(
        batch_dir / "state" / "gen-budget.json", batch_id=batch_id)
    policy = betta_policy.StandingPolicy(betta_policy.default_policy())
    assert policy.paid_generation_authorised() is False

    budget_before = budget.summary()
    adapters = betta_adapters.make_adapters(
        batch_id=batch_id, batch_dir=batch_dir, intake_dir=intake,
        telemetry_db=SCRATCH / "telemetry.sqlite3", policy=policy,
        live_shopify=False, live_generation=False, runners={},
        processed_registry=SCRATCH / "processed-registry.sqlite3",
        budget=budget, selected_sources=selected,
    )

    result = betta_process.process_batch(batch_dir, batch_id, adapters=adapters, policy=policy)

    # -- gather evidence ------------------------------------------------- #
    state = json.loads((batch_dir / "state" / "process.json").read_text())
    shutil.copy2(batch_dir / "state" / "process.json", evidence_dir / "process-state.json")

    entries = []
    receipts = {}
    for key, entry in sorted(state.get("fish", {}).items()):
        record = {
            "key": key,
            "tank_id": entry.get("tank_id"),
            "photo_date": entry.get("photo_date"),
            "status": entry.get("status"),
            "notes": entry.get("notes"),
            "uncertain": entry.get("uncertain"),
            "uncertain_reason": entry.get("uncertain_reason"),
            "identify_reason": entry.get("identify_reason"),
            "label_price_visible": entry.get("label_price_visible"),
            "label_reads": entry.get("label_reads"),
            "source_path": entry.get("source_path"),
            "source_sha256": entry.get("source_sha256"),
            "prep_status": entry.get("prep_status"),
            "working_input_path": entry.get("working_input_path"),
            "working_input_sha256": entry.get("working_input_sha256"),
            "catalogue_evidence_path": entry.get("catalogue_evidence_path"),
            "catalogue_evidence_sha256": entry.get("catalogue_evidence_sha256"),
        }
        entries.append(record)
        for label_name, path_text in (
            ("catalogue", entry.get("catalogue_evidence_path")),
            ("label_corroboration",
             ((entry.get("label_reads") or {}).get("crop") or {}).get("receipt_path")),
        ):
            if path_text and Path(path_text).is_file():
                target = evidence_dir / f"{label_name}-receipt.json"
                shutil.copy2(path_text, target)
                receipts[label_name] = {"source": str(path_text), "copy": str(target),
                                        "sha256": sha256(Path(path_text))}
        crop = ((entry.get("label_reads") or {}).get("crop") or {})
        if crop.get("crop_path") and Path(crop["crop_path"]).is_file():
            shutil.copy2(crop["crop_path"], evidence_dir / "label-crop.png")
            receipts["label_crop"] = {
                "source": crop.get("crop_path"),
                "copy": str(evidence_dir / "label-crop.png"),
                "sha256": sha256(Path(crop["crop_path"])),
            }
        if entry.get("working_receipt_path") and Path(entry["working_receipt_path"]).is_file():
            shutil.copy2(entry["working_receipt_path"], evidence_dir / "preparation-receipt.json")
            receipts["preparation"] = {
                "source": entry["working_receipt_path"],
                "copy": str(evidence_dir / "preparation-receipt.json"),
                "sha256": sha256(Path(entry["working_receipt_path"])),
            }
        working = entry.get("working_input_path")
        if working and Path(working).is_file():
            record["working_dimensions"] = None
            try:
                from PIL import Image
                with Image.open(working) as image:
                    record["working_dimensions"] = list(image.size)
            except Exception as exc:
                record["working_dimensions"] = f"unreadable: {exc}"
            record["working_sha256_recomputed"] = sha256(Path(working))

    summary = {
        "batch_id": batch_id,
        "batch_dir": str(batch_dir),
        "result": result,
        "policy": {
            "enabled": policy.data.get("enabled"),
            "automatic_batch_authorisation": policy.data.get("automatic_batch_authorisation"),
            "paid_generation_authorised": policy.paid_generation_authorised(),
        },
        "live_flags": {"live_shopify": False, "live_generation": False},
        "raw_source": {
            "path": str(source),
            "sha256_before": raw_before,
            "sha256_after": sha256(source),
            "size_bytes": size,
            "unchanged": raw_before == sha256(source),
        },
        "fixture": {"path": str(FIXTURE), "sha256": raw_before,
                    "sha256_after_run": sha256(FIXTURE)},
        "entries": entries,
        "receipt_copies": receipts,
        "budget_before": budget_before,
        "budget_after": budget.summary(),
    }
    (evidence_dir / "eval-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"summary": result, "evidence": str(evidence_dir / 'eval-summary.json'),
                      "entries": [{k: e[k] for k in
                                   ("tank_id", "photo_date", "status", "uncertain_reason")}
                                  for e in entries]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
