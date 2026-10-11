#!/usr/bin/env python3
"""Resumable, verified archive command for NTA Betta Processing V2.1.

Archives a completed batch only after every fish has independently verified
Shopify completion. Documented, owner-accepted exceptions are preserved and
recorded as exceptions; a failed assertion is never converted into a pass.

Layout produced under the archive root:

    Archived Bettas/YYYY-MM-DD/Betta Processing/   originals + inventory CSV
    Archived Bettas/YYYY-MM-DD/Betta Processed/    <Tank ID>.png heroes
    Archived Bettas/YYYY-MM-DD/Audit/              manifests, receipts, QA, reports

Subcommands: ``plan``, ``execute``, ``status``, ``resume``. The default mode is
dry-run: no file is moved or deleted unless ``--apply`` is given to execute/resume.
Destination files are copied, SHA-256 verified against the source, and only then
are the specific source files removed. Unrelated files, authentication data and
unresolved Shopify mutation state are never touched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

SYDNEY = ZoneInfo("Australia/Sydney")

VERIFIED = "VERIFIED"
PASS_WITH_EXCEPTION = "PASS_WITH_ACCEPTED_EXCEPTION"
NEEDS_REVIEW = "NEEDS_REVIEW"
READBACK_PASS = "FINAL_SHOPIFY_READBACK_PASS"

PLAN_SCHEMA = "nta-betta-archive-plan-v1"
MANIFEST_SCHEMA = "nta-betta-archive-manifest-v1"
STATE_SCHEMA = "nta-betta-archive-state-v1"

MOVE_ROLES = {"original", "hero", "inventory_csv"}


class ArchiveError(ValueError):
    pass


def now_sydney() -> str:
    return datetime.now(SYDNEY).isoformat()


def _safe_id(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]", "_", str(value or "batch"))
    return text or "batch"


def sydney_date(moment: Optional[str] = None) -> str:
    if moment is None:
        return datetime.now(SYDNEY).date().isoformat()
    parsed = datetime.fromisoformat(moment)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SYDNEY)
    return parsed.astimezone(SYDNEY).date().isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_manifest_immutable(path: Path, data: dict) -> str:
    """Write an immutable manifest. Refuse to replace different existing content."""
    path = Path(path)
    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    if path.is_file():
        existing = path.read_text(encoding="utf-8")
        if existing != payload:
            raise ArchiveError(f"refusing to overwrite an existing different manifest: {path}")
        return hashlib.sha256(existing.encode("utf-8")).hexdigest()
    atomic_write_json(path, data)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Verified-completion gate
# --------------------------------------------------------------------------- #
def _report_items(report: dict) -> list:
    return list(report.get("items") or [])


def _manifest_exception(item: dict) -> Optional[dict]:
    qa = item.get("image_qa") or {}
    exception = qa.get("exception") if isinstance(qa, dict) else None
    if isinstance(exception, dict) and exception.get("accepted") is True:
        return exception
    return None


def classify_completion(
    manifest_items: list,
    verification_reports: list,
    external_exceptions: Optional[list] = None,
) -> list:
    """Return one decision per manifest item, never promoting a failure to a pass."""
    external = {entry["tank_id"]: entry for entry in (external_exceptions or [])}
    report_by_tank: dict[str, list] = {}
    for report in verification_reports:
        for entry in _report_items(report):
            report_by_tank.setdefault(entry.get("tank_id"), []).append(entry)

    decisions = []
    for item in manifest_items:
        tank = item.get("tank_id")
        entries = report_by_tank.get(tank, [])
        readback_pass = any(entry.get("status") == READBACK_PASS for entry in entries)

        failed = []
        for entry in entries:
            for name, assertion in (entry.get("assertions") or {}).items():
                if isinstance(assertion, dict) and assertion.get("status") == "FAIL":
                    failed.append(name)

        accepted_assertions: set = set()
        accepted_exceptions = []
        qa_exception = _manifest_exception(item)
        if qa_exception:
            accepted_assertions.update(qa_exception.get("failed_assertions") or [])
            accepted_exceptions.append(qa_exception)
        if tank in external:
            record = external[tank]
            accepted_assertions.update(record.get("assertions") or [])
            accepted_exceptions.append(record)

        unresolved = sorted({name for name in failed if name not in accepted_assertions})

        if not readback_pass or unresolved:
            state = NEEDS_REVIEW
        elif accepted_exceptions:
            state = PASS_WITH_EXCEPTION
        else:
            state = VERIFIED

        decisions.append({
            "tank_id": tank,
            "state": state,
            "readback_pass": readback_pass,
            "failed_assertions": sorted(set(failed)),
            "accepted_assertions": sorted(accepted_assertions),
            "unresolved_assertions": unresolved,
            "accepted_exceptions": accepted_exceptions,
        })
    return decisions


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #
def _file_entry(
    role: str,
    tank: Optional[str],
    source: Path,
    destination: Path,
    move: bool,
    expected_source_sha: Optional[str] = None,
) -> dict:
    source_exists = source.is_file()
    source_sha = sha256_file(source) if source_exists else expected_source_sha
    destination_exists = destination.is_file()
    destination_sha = sha256_file(destination) if destination_exists else None
    already_done = bool(source_sha and destination_sha and source_sha == destination_sha)
    return {
        "role": role,
        "tank_id": tank,
        "source": str(source),
        "destination": str(destination),
        "move": move,
        "source_exists": source_exists,
        "source_sha256": source_sha,
        "destination_exists": destination_exists,
        "destination_sha256": destination_sha,
        "already_done": already_done,
        "conflict": bool(destination_exists and not already_done),
        # A move source that is already archived (source gone, destination verified)
        # is a completed step, not a missing-source blocker.
        "source_resolved_by_destination": bool((not source_exists) and already_done),
    }


def _gather_audit_sources(
    manifest: dict,
    manifest_path: Path,
    report_paths: list,
    exceptions_path: Optional[Path],
    state_root: Optional[Path],
    audit_paths: Optional[list] = None,
) -> list:
    sources = (
        [manifest_path] + [Path(path) for path in report_paths] +
        [Path(path) for path in (audit_paths or [])]
    )
    if exceptions_path is not None:
        sources.append(Path(exceptions_path))
    for item in manifest.get("items", []):
        qa = item.get("image_qa") or {}
        if isinstance(qa, dict) and qa.get("path"):
            sources.append(Path(qa["path"]))
        for receipt in (item.get("completion_evidence") or {}).get("receipts", []):
            if isinstance(receipt, dict) and receipt.get("path"):
                sources.append(Path(receipt["path"]))
    if state_root is not None:
        batch_id = manifest.get("batch_id")
        if batch_id:
            for receipt in sorted((Path(state_root) / str(batch_id)).glob("*/receipts/*.json")):
                sources.append(receipt)
    seen, unique = set(), []
    for source in sources:
        key = str(source)
        if key not in seen:
            seen.add(key)
            unique.append(source)
    return unique


def build_plan(
    manifest_path: Path,
    report_paths: list,
    inventory_csv: Optional[Path],
    archive_root: Path,
    date: Optional[str] = None,
    exceptions_path: Optional[Path] = None,
    state_root: Optional[Path] = None,
    audit_dir_name: str = "Audit",
    audit_paths: Optional[list] = None,
) -> dict:
    manifest_path = Path(manifest_path)
    manifest = load_json(manifest_path)
    reports = [load_json(Path(path)) for path in report_paths]
    external_exceptions = []
    if exceptions_path is not None:
        external_exceptions = load_json(Path(exceptions_path)).get("exceptions", [])

    items = manifest.get("items", [])
    decisions = classify_completion(items, reports, external_exceptions)

    archive_date = date or sydney_date()
    safe_batch = _safe_id(manifest.get("batch_id"))
    root_base = Path(archive_root) / archive_date

    def collect_files(base_dir: Path, prior_by_destination: dict):
        proc = base_dir / "Betta Processing"
        hero_dir = base_dir / "Betta Processed"
        audit = base_dir / audit_dir_name
        entries = []
        for item in items:
            tank = item.get("tank_id")
            original = Path(item["original"]["path"])
            extension = original.suffix
            entries.append(_file_entry(
                "original", tank, original,
                proc / f"{tank} Original {archive_date}{extension}", move=True,
                expected_source_sha=item["original"].get("sha256"),
            ))
            hero = Path(item["hero"]["path"])
            entries.append(_file_entry(
                "hero", tank, hero, hero_dir / f"{tank}.png", move=True,
                expected_source_sha=item["hero"].get("sha256"),
            ))
        if inventory_csv is not None:
            csv_path = Path(inventory_csv)
            csv_destination = proc / csv_path.name
            prior_csv = prior_by_destination.get(str(csv_destination), {})
            entries.append(_file_entry(
                "inventory_csv", None, csv_path, csv_destination, move=True,
                expected_source_sha=prior_csv.get("source_sha256"),
            ))
        audit_sources = _gather_audit_sources(
            manifest, manifest_path, report_paths, exceptions_path,
            state_root, audit_paths,
        )
        used_audit_names: dict[str, Path] = {}
        for source in audit_sources:
            name = source.name
            previous = used_audit_names.get(name)
            if previous is not None and previous != source:
                digest = (
                    sha256_file(source)[:12] if source.is_file()
                    else hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:12]
                )
                name = f"{digest}-{name}"
            used_audit_names[name] = source
            entries.append(_file_entry(
                "audit", None, source, audit / name, move=False,
            ))
        return entries, proc, hero_dir, audit

    # Batch-specific state file so multiple batches on the same date never share state.
    state_path = root_base / f"{safe_batch}-archive-state.json"
    prior_by_destination = {}
    if state_path.is_file():
        for record in load_json(state_path).get("files", []):
            if record.get("destination"):
                prior_by_destination[record["destination"]] = record

    files, processing_dir, processed_dir, audit_dir = collect_files(root_base, prior_by_destination)

    # If any destination would collide with another batch's files, isolate this batch
    # under a batch-specific subdirectory rather than overwrite anything.
    isolated = False
    if any(entry["conflict"] for entry in files):
        isolated = True
        files, processing_dir, processed_dir, audit_dir = collect_files(
            root_base / safe_batch, prior_by_destination)

    blockers = []
    for decision in decisions:
        if decision["state"] == NEEDS_REVIEW:
            blockers.append({
                "tank_id": decision["tank_id"],
                "reason": "no independent readback pass or unresolved failed assertions",
                "unresolved_assertions": decision["unresolved_assertions"],
                "readback_pass": decision["readback_pass"],
            })
    for entry in files:
        if not entry["source_exists"] and not entry["source_resolved_by_destination"]:
            blockers.append({"source": entry["source"], "reason": "source file missing"})
        elif entry["conflict"]:
            blockers.append({"destination": entry["destination"], "reason": "conflicting existing file"})

    return {
        "schema": PLAN_SCHEMA,
        "batch_id": manifest.get("batch_id"),
        "archive_date": archive_date,
        "generated_at": now_sydney(),
        "timezone": "Australia/Sydney",
        "archive_root": str(archive_root),
        "isolated": isolated,
        "state_file": str(state_path),
        "processing_dir": str(processing_dir),
        "processed_dir": str(processed_dir),
        "audit_dir": str(audit_dir),
        "blocked": bool(blockers),
        "blockers": blockers,
        "fish": decisions,
        "files": files,
        "verification_reports": [{"path": str(path), "sha256": sha256_file(Path(path))} for path in report_paths],
        "audit_inputs": [
            {"path": str(path), "sha256": sha256_file(Path(path))}
            for path in (audit_paths or []) if Path(path).is_file()
        ],
        "counts": {
            "verified": sum(1 for d in decisions if d["state"] == VERIFIED),
            "pass_with_accepted_exception": sum(1 for d in decisions if d["state"] == PASS_WITH_EXCEPTION),
            "needs_review": sum(1 for d in decisions if d["state"] == NEEDS_REVIEW),
        },
    }


# --------------------------------------------------------------------------- #
# Execute / resume / status
# --------------------------------------------------------------------------- #
def execute_plan(plan: dict, apply: bool = False) -> dict:
    if plan.get("blocked"):
        raise ArchiveError(
            "archive plan is blocked; resolve every fish before archiving: "
            + json.dumps(plan.get("blockers"), sort_keys=True)
        )
    safe_batch = _safe_id(plan.get("batch_id"))
    if plan.get("state_file"):
        state_path = Path(plan["state_file"])
    else:
        state_path = Path(plan["archive_root"]) / plan["archive_date"] / f"{safe_batch}-archive-state.json"
    manifest_path = state_path.parent / f"{safe_batch}-archive-manifest.json"

    results = []
    for entry in plan["files"]:
        source = Path(entry["source"])
        destination = Path(entry["destination"])
        record = {
            "role": entry["role"],
            "tank_id": entry["tank_id"],
            "source": str(source),
            "destination": str(destination),
            "source_sha256": entry["source_sha256"],
            "move": entry["move"],
        }
        # Re-check the destination live so a file created after planning is never
        # silently overwritten.
        if destination.is_file():
            destination_sha256 = sha256_file(destination)
            if entry["source_sha256"] and destination_sha256 == entry["source_sha256"]:
                record.update({"status": "ALREADY_DONE", "destination_sha256": destination_sha256})
                results.append(record)
                continue
            raise ArchiveError(f"conflicting existing destination, refusing to overwrite: {destination}")
        if not apply:
            record["status"] = "PLANNED"
            results.append(record)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        destination_sha256 = sha256_file(destination)
        if destination_sha256 != entry["source_sha256"]:
            raise ArchiveError(f"destination hash mismatch after copy: {destination}")
        record.update({
            "status": "COPIED",
            "destination_sha256": destination_sha256,
            "verified_at": now_sydney(),
        })
        results.append(record)

    summary = {"mode": "execute" if apply else "dry-run", "batch_id": plan.get("batch_id"),
               "archive_date": plan.get("archive_date"), "results": results}

    if not apply:
        return summary

    # Phase 2: only now that every copy is verified, remove the specific sources.
    for record in results:
        if record["move"] and record["status"] in ("COPIED", "ALREADY_DONE"):
            source = Path(record["source"])
            if source.is_file() and sha256_file(source) == record["source_sha256"]:
                source.unlink()
                record["source_removed"] = True

    move_records = [record for record in results if record["move"]]
    audit_records = [record for record in results if record["role"] == "audit"]
    complete = all(record["status"] in ("COPIED", "ALREADY_DONE") for record in move_records)
    batch_status = "COMPLETE" if complete else "PARTIAL"

    state = {
        "schema": STATE_SCHEMA,
        "batch_id": plan.get("batch_id"),
        "archive_date": plan.get("archive_date"),
        "updated_at": now_sydney(),
        "batch_status": batch_status,
        "files": results,
        "exception_tanks": [d["tank_id"] for d in plan["fish"] if d["state"] == PASS_WITH_EXCEPTION],
        "needs_review_tanks": [d["tank_id"] for d in plan["fish"] if d["state"] == NEEDS_REVIEW],
    }
    atomic_write_json(state_path, state)

    if complete:
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "batch_id": plan.get("batch_id"),
            "archive_date": plan.get("archive_date"),
            "created_at": now_sydney(),
            "timezone": "Australia/Sydney",
            "batch_status": batch_status,
            "archive_root": plan["archive_root"],
            "fish": plan["fish"],
            "files": [
                {
                    "role": record["role"],
                    "tank_id": record["tank_id"],
                    "source_path": record["source"],
                    "source_sha256": record["source_sha256"],
                    "destination_path": record["destination"],
                    "destination_sha256": record.get("destination_sha256"),
                    "verified_at": record.get("verified_at"),
                }
                for record in results
            ],
            "verification_reports": plan.get("verification_reports", []),
            "audit_inputs": plan.get("audit_inputs", []),
        }
        if manifest_path.is_file():
            # Immutable: a resumed run reuses the already-written manifest.
            manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        else:
            manifest_sha256 = write_manifest_immutable(manifest_path, manifest)
        summary["manifest"] = str(manifest_path)
        summary["manifest_sha256"] = manifest_sha256
    summary["batch_status"] = batch_status
    summary["state"] = str(state_path)
    return summary


def report_status(archive_root: Path, date: Optional[str] = None,
                  batch_id: Optional[str] = None) -> dict:
    base = Path(archive_root) / (date or sydney_date())
    if batch_id:
        safe = _safe_id(batch_id)
        candidates = [base, base / safe]
    else:
        candidates = [base] + sorted(p for p in base.glob("*") if p.is_dir())
    found = []
    for directory in candidates:
        for pattern in ("*-archive-manifest.json", "*-archive-state.json",
                        "archive-manifest.json", "archive-state.json"):
            for path in sorted(directory.glob(pattern)):
                is_manifest = "manifest" in path.name
                data = load_json(path)
                record = {
                    "source": "manifest" if is_manifest else "state",
                    "path": str(path),
                    "batch_id": data.get("batch_id"),
                    "archive_date": data.get("archive_date"),
                    "batch_status": data.get("batch_status"),
                }
                if is_manifest:
                    record["file_count"] = len(data.get("files", []))
                else:
                    record["file_count"] = len(data.get("files", []))
                    record["files_done"] = sum(
                        1 for f in data.get("files", []) if f.get("status") in ("COPIED", "ALREADY_DONE"))
                found.append(record)
    preferred = {}
    for record in found:
        key = record.get("batch_id")
        existing = preferred.get(key)
        if existing is None or (existing["source"] == "state" and record["source"] == "manifest"):
            preferred[key] = record
    batches = list(preferred.values())
    if batches:
        return {"archive_date": date or sydney_date(), "batches": batches, "count": len(batches)}
    return {"source": None, "archive_date": date or sydney_date(),
            "batch_status": "NOT_STARTED", "path": str(base)}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
DEFAULT_ARCHIVE_ROOT = Path.home() / "Documents" / "Archived Bettas"


def _plan_from_args(args) -> dict:
    return build_plan(
        manifest_path=args.manifest,
        report_paths=args.verify or [],
        inventory_csv=args.inventory_csv,
        archive_root=args.archive_root,
        date=args.date,
        exceptions_path=args.exceptions,
        state_root=args.state_root,
        audit_dir_name=args.audit_dir_name,
        audit_paths=args.audit_path or [],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verified, resumable Betta batch archive")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_common(p):
        p.add_argument("--manifest", type=Path, required=True, help="Shopify production/batch manifest")
        p.add_argument("--verify", type=Path, action="append", default=[],
                       help="Independent Shopify verification report (repeatable)")
        p.add_argument("--inventory-csv", type=Path, default=None)
        p.add_argument("--exceptions", type=Path, default=None,
                       help="Owner-accepted assertion exceptions JSON")
        p.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
        p.add_argument("--date", default=None, help="Archive date (default: Australia/Sydney today)")
        p.add_argument("--state-root", type=Path, default=None,
                       help="Shopify bridge state root for receipt preservation")
        p.add_argument("--audit-dir-name", default="Audit")
        p.add_argument("--audit-path", type=Path, action="append", default=[],
                       help="Additional evidence file copied and SHA-256 verified (repeatable)")
        p.add_argument("--out", type=Path, default=None, help="Write the plan JSON to this path")

    p = sub.add_parser("plan"); add_common(p)
    p = sub.add_parser("execute"); add_common(p); p.add_argument("--apply", action="store_true")
    p = sub.add_parser("resume"); add_common(p); p.add_argument("--apply", action="store_true")

    p = sub.add_parser("status")
    p.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    p.add_argument("--date", default=None)
    p.add_argument("--batch", default=None, help="Filter to a specific batch id")

    args = parser.parse_args()
    try:
        if args.cmd == "status":
            print(json.dumps(report_status(args.archive_root, args.date, args.batch), indent=2, sort_keys=True))
            return 0

        plan = _plan_from_args(args)
        if args.out is not None:
            atomic_write_json(args.out, plan)

        if args.cmd == "plan":
            print(json.dumps(plan, indent=2, sort_keys=True))
            return 2 if plan["blocked"] else 0

        if plan["blocked"]:
            print(json.dumps({"blocked": True, "blockers": plan["blockers"],
                              "counts": plan["counts"]}, indent=2, sort_keys=True))
            return 2
        result = execute_plan(plan, apply=bool(getattr(args, "apply", False)))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ArchiveError, OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

