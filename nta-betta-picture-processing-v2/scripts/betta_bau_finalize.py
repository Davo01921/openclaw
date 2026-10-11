"""Idempotent, SHA-verified final audit after the image archive completes.

No models, Shopify writes or notification sends. The image archive is immutable;
a separate completion receipt binds final telemetry, process and outcome bytes.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import tempfile
from pathlib import Path

import betta_telemetry as telemetry


class FinalizationError(RuntimeError):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def immutable(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != content:
            raise FinalizationError(f"final audit bytes differ: {path.name}")
        return path
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".final-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o444)
        try:
            os.link(temporary, path)
        except FileExistsError:
            return immutable(path, content)
    finally:
        os.unlink(temporary)
    return path


def contained(path, root):
    path = Path(path)
    if path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()):
        raise FinalizationError("audit destination is outside configured archive")
    return path.resolve()


def verify_receipt(receipt, config):
    for record in receipt.get("files", []):
        destination = contained(record["destination"], config["paths"]["archive"])
        if not destination.is_file() or sha(destination) != record["sha256"]:
            raise FinalizationError("final archived audit hash mismatch")
    if not receipt.get("files"):
        raise FinalizationError("final audit receipt has no files")


def clean_intake(config, batch_dir, state, archive, receipt_path):
    """Delete only dispatcher-selected bytes already verified in the archive."""
    sources = json.loads((batch_dir / "state" / "sources.json").read_text())
    if sources.get("dispatcher_owned") is not True or sources.get("batch_id") != state["batch_id"]:
        raise FinalizationError("intake cleanup requires dispatcher-owned sources")
    originals = {record["source_sha256"] for record in archive["files"] if record.get("role") == "original"}
    decisions = []
    for selected in sources["selected_sources"]:
        if selected["sha256"] not in originals:
            continue  # quarantined originals are retained
        path = Path(selected["path"])
        if path.is_symlink() or path.parent.resolve() != Path(config["paths"]["intake"]).resolve():
            raise FinalizationError("unsafe selected original path")
        if not path.exists():
            decision = "REMOVED_OR_ALREADY_ABSENT"
        elif sha(path) != selected["sha256"]:
            decision = "RETAINED_CHANGED_SOURCE"
        else:
            path.unlink()
            decision = "REMOVED_OR_ALREADY_ABSENT"
        decisions.append({"path": str(path), "sha256": selected["sha256"], "status": decision})
    immutable(receipt_path, json_bytes({"schema": "nta-betta-intake-cleanup-v1",
                                      "batch_id": state["batch_id"], "sources": decisions}))


def finalize(config, batch_dir, summary):
    batch_dir = Path(batch_dir).resolve()
    input_path = batch_dir / "state" / "finalization-input.json"
    if input_path.is_file():
        inputs = json.loads(input_path.read_text())
        state = inputs["process"]
        summary = inputs["summary"]
    else:
        state = json.loads((batch_dir / "state" / "process.json").read_text())
        inputs = {"process": state, "summary": summary}
    if state.get("status") not in {"COMPLETE", "PARTIAL"} or state.get("stage") != "ARCHIVED":
        raise FinalizationError("finalization requires an archived terminal process")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", str(state.get("batch_id", ""))):
        raise FinalizationError("unsafe finalization batch ID")
    if summary.get("batch_id") != state["batch_id"] or summary.get("status") != state["status"]:
        raise FinalizationError("terminal summary identity mismatch")
    archived = state.get("archive_receipt") or {}
    if archived.get("status") != "ARCHIVED" or archived.get("batch_status") != "COMPLETE":
        raise FinalizationError("verified archive receipt required")
    archive_path = contained(archived["manifest"], config["paths"]["archive"])
    if sha(archive_path) != archived.get("manifest_sha256"):
        raise FinalizationError("asset archive manifest changed")
    archive = json.loads(archive_path.read_text())
    if archive.get("batch_id") != state["batch_id"] or archive.get("batch_status") != "COMPLETE":
        raise FinalizationError("asset archive batch mismatch")
    for record in archive.get("files", []):
        destination = contained(record["destination_path"], config["paths"]["archive"])
        if (record.get("destination_sha256") != record.get("source_sha256")
                or not destination.is_file() or sha(destination) != record["source_sha256"]):
            raise FinalizationError("asset archive bytes no longer match")
    if not archive.get("files"):
        raise FinalizationError("empty asset archive")
    if not any(record.get("source_path") == state["manifest_path"]
               and record.get("source_sha256") == state["manifest_sha256"] for record in archive["files"]):
        raise FinalizationError("asset archive lacks the hash-bound production manifest")
    completed_at = archive["created_at"]
    parsed = telemetry.parse_datetime(completed_at)
    if parsed is None or parsed.utcoffset() is None:
        raise FinalizationError("archive completion timestamp is invalid")
    immutable(input_path, json_bytes(inputs))
    destination_root = archive_path.parent / "Audit" / state["batch_id"] / "Final"
    contained(destination_root, config["paths"]["archive"])
    receipt_path = destination_root / "completion-receipt.json"
    cleanup_path = destination_root / "intake-cleanup.json"
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text())
        if receipt.get("asset_archive_sha256") != archived["manifest_sha256"]:
            raise FinalizationError("completion receipt archive mismatch")
        verify_receipt(receipt, config)
        immutable(batch_dir / "state" / "completion-receipt.json", receipt_path.read_bytes())
        if not cleanup_path.is_file():
            clean_intake(config, batch_dir, state, archive, cleanup_path)
        return {"status": "FINALIZED", "receipt_path": str(batch_dir / "state" / "completion-receipt.json"),
                "archive_receipt_path": str(receipt_path), "receipt_sha256": sha(receipt_path), "archive_completed_at": completed_at}

    con = telemetry.connect(Path(config["paths"]["telemetry"]))
    try:
        for key in state.get("executed", []):
            fish = state["fish"][key]
            row = con.execute("SELECT date_entered,shopify_verified_at FROM betta_processing_telemetry "
                              "WHERE batch_id=? AND tank_number=?", (state["batch_id"], fish["tank_id"])).fetchone()
            if row is None or not row[1]:
                raise FinalizationError("verified fish telemetry is missing")
            con.execute("UPDATE betta_processing_telemetry SET archive_completed_at=?,end_to_archive_seconds=?,"
                        "onboarding_seconds=?,updated_at=? WHERE batch_id=? AND tank_number=?",
                        (completed_at, telemetry.seconds_between(row[0], completed_at),
                         telemetry.seconds_between(row[0], row[1]), completed_at, state["batch_id"], fish["tank_id"]))
        con.commit()
        rows = con.execute("SELECT " + ",".join(telemetry.FIELDS) + " FROM betta_processing_telemetry "
                           "WHERE batch_id=? ORDER BY tank_number", (state["batch_id"],)).fetchall()
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(telemetry.FIELDS)
        writer.writerows(rows)
        final_process = {**state, "archive_completed_at": completed_at}
        final_outcome = {"schema": "nta-betta-bau-final-outcome-v1", "summary": summary,
                         "archive_completed_at": completed_at,
                         "asset_archive_sha256": archived["manifest_sha256"]}
        payloads = {"final-process.json": json_bytes(final_process),
                    "final-bau-outcome.json": json_bytes(final_outcome),
                    "final-betta-telemetry.csv": stream.getvalue().encode(),
                    "finalization-input.json": input_path.read_bytes()}
        call_path = batch_dir / "reports" / "betta-call-telemetry.csv"
        if call_path.is_file():
            payloads[call_path.name] = call_path.read_bytes()
        records = []
        for name, content in payloads.items():
            local = immutable(batch_dir / "state" / "final-audit" / name, content)
            destination = immutable(destination_root / name, local.read_bytes())
            if sha(local) != sha(destination):
                raise FinalizationError("final audit copy mismatch")
            records.append({"source": str(local), "destination": str(destination), "sha256": sha(destination)})
        receipt = {"schema": "nta-betta-bau-completion-v1", "batch_id": state["batch_id"],
                   "status": state["status"], "archive_completed_at": completed_at,
                   "asset_archive_sha256": archived["manifest_sha256"], "files": records}
        verify_receipt(receipt, config)
        immutable(receipt_path, json_bytes(receipt))
        immutable(batch_dir / "state" / "completion-receipt.json", receipt_path.read_bytes())
        clean_intake(config, batch_dir, state, archive, cleanup_path)
        return {"status": "FINALIZED", "receipt_path": str(batch_dir / "state" / "completion-receipt.json"),
                "archive_receipt_path": str(receipt_path), "receipt_sha256": sha(receipt_path), "archive_completed_at": completed_at}
    finally:
        con.close()
