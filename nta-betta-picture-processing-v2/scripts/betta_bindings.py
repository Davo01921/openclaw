#!/usr/bin/env python3
"""Concrete, fail-closed bindings for the Betta BAU dispatcher.

The bindings delegate Shopify work and archiving to the existing uploader and
archiver. They add boundary checks: exact persisted-manifest hashing, per-fish
result selection, independent read-back verification, and validation of the
archiver's machine-readable result.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

_SCRIPT_DIR = Path(__file__).resolve().parent
SHOPIFY_LIVE = _SCRIPT_DIR / "shopify_live.mjs"
UPLOADER = _SCRIPT_DIR / "betta_shopify_batch.py"
ARCHIVER = _SCRIPT_DIR / "betta_archive.py"
READBACK_PASS = "FINAL_SHOPIFY_READBACK_PASS"
SYDNEY = ZoneInfo("Australia/Sydney")


class BindingError(RuntimeError):
    pass


def _run(
    argv: list, *, runner: Optional[Callable] = None, timeout: int = 180,
    environment: Optional[Mapping[str, str]] = None,
) -> str:
    if runner is not None:
        result = runner(argv)
        return result if isinstance(result, str) else json.dumps(result)
    subprocess_environment = dict(os.environ)
    subprocess_environment.update(environment or {})
    result = subprocess.run(
        [str(a) for a in argv], capture_output=True, text=True, timeout=timeout,
        env=subprocess_environment,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise BindingError(f"command failed ({result.returncode}): {detail[-800:]}")
    return result.stdout


def _json_output(output: str, operation: str) -> dict:
    try:
        data = json.loads(output)
    except (TypeError, json.JSONDecodeError) as exc:
        raise BindingError(f"{operation} returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise BindingError(f"{operation} returned a non-object JSON value")
    return data


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_manifest_digest(
    manifest_path: Path, supplied_digest: Optional[str],
) -> str:
    path = Path(manifest_path).expanduser().resolve()
    if not path.is_file():
        raise BindingError(f"persisted manifest missing: {path}")
    actual = _sha256_file(path)
    if supplied_digest != actual:
        raise BindingError(
            "supplied manifest SHA-256 does not equal the persisted manifest bytes"
        )
    return actual


def _tank_item(report: Mapping[str, Any], tank: str, operation: str) -> dict:
    matches = [
        item for item in (report.get("items") or [])
        if isinstance(item, dict) and item.get("tank_id") == tank
    ]
    if len(matches) != 1:
        raise BindingError(
            f"{operation} expected one result for {tank}; found {len(matches)}"
        )
    return matches[0]


def shopify_resolve_runner(
    *, node: str = "node", env_file: Optional[Path] = None,
    runner: Optional[Callable] = None,
) -> Callable:
    """Return the fresh, read-only exact-product resolver."""

    def resolve(entry: dict) -> dict:
        tank = entry.get("tank_id")
        if not tank:
            return {"status": "AMBIGUOUS"}
        data = _json_output(
            _run(
                [node, str(SHOPIFY_LIVE.resolve()), "resolve", tank],
                runner=runner,
                environment=(
                    {"BETTA_SHOPIFY_ENV": str(Path(env_file).resolve())}
                    if env_file is not None else None
                ),
            ),
            "Shopify resolve",
        )
        if not data.get("ok") or data.get("status") != "RESOLVED":
            return {"status": "AMBIGUOUS"}
        snapshot = data.get("snapshot")
        if not isinstance(snapshot, dict):
            raise BindingError("Shopify resolve omitted its protected snapshot")
        try:
            product = {
                "id": snapshot["id"],
                "variant_id": snapshot["variant_id"],
                "location_id": snapshot["location_id"],
                "inventory_item_id": snapshot["inventory_item_id"],
                "source": snapshot.get("source", "FRESH_SHOPIFY_READ"),
                "tank_id": snapshot.get("tank_id", tank),
                "before": snapshot["before"],
                "raw_snapshot": snapshot.get("raw_product", snapshot),
                "fetched_at": snapshot.get("fetched_at"),
                "query": snapshot.get("query", tank),
            }
        except KeyError as exc:
            raise BindingError(
                f"Shopify resolve snapshot missing {exc.args[0]}"
            ) from exc
        return {"status": "RESOLVED", "product": product}

    return resolve


def shopify_preflight_runner(
    *, python_executable: str = sys.executable,
    node: Optional[str] = None, bridge: Optional[Path] = None,
    env_file: Optional[Path] = None, runner: Optional[Callable] = None,
) -> Callable:
    """Return an uploader preflight bound to the persisted manifest bytes."""

    def preflight(
        manifest_path: Path, manifest_sha256: Optional[str],
        tank_id: Optional[str] = None,
    ) -> dict:
        actual = _validated_manifest_digest(manifest_path, manifest_sha256)
        argv = [
            str(python_executable), str(UPLOADER), "preflight",
            "--manifest", str(Path(manifest_path).resolve()),
        ]
        if bridge is not None:
            argv += ["--bridge", str(Path(bridge).resolve())]
        if node is not None:
            argv += ["--node", str(node)]
        if env_file is not None:
            argv += ["--env-file", str(Path(env_file).resolve())]
        if tank_id:
            argv += ["--tank", tank_id]
        report = _json_output(
            _run(argv, runner=runner), "Shopify uploader preflight",
        )
        if report.get("manifest_sha256") != actual:
            raise BindingError("uploader preflight reported a different manifest digest")
        items = report.get("items") or []
        passed = (
            report.get("shopify_writes_performed") is False and
            bool(items) and
            all(
                isinstance(item, dict) and item.get("status") in {
                    "PREFLIGHTED", "VERIFIED", "COMPLETED_VERIFIED",
                }
                for item in items
            )
        )
        return {
            "status": "PREFLIGHT_PASS" if passed else "BLOCKED",
            "manifest_sha256": actual,
            "report_path": report.get("report_path"),
            "items": items,
        }

    return preflight


def shopify_execute_runner(
    *, live: bool = False,
    python_executable: str = sys.executable,
    node: Optional[str] = None, bridge: Optional[Path] = None,
    env_file: Optional[Path] = None,
    runner: Optional[Callable] = None,
) -> Callable:
    """Return a resumable uploader runner with independent final verification.

    Every invocation hashes the persisted manifest and requires the supplied
    per-batch digest to match. There is no preselected or wildcard authority.
    """

    def call_uploader(
        command: str, manifest_path: Path, tank: str,
        digest: Optional[str] = None,
    ) -> dict:
        argv = [
            str(python_executable), str(UPLOADER), command,
            "--manifest", str(Path(manifest_path).resolve()),
            "--tank", tank,
        ]
        if bridge is not None:
            argv += ["--bridge", str(Path(bridge).resolve())]
        if node is not None:
            argv += ["--node", str(node)]
        if env_file is not None:
            argv += ["--env-file", str(Path(env_file).resolve())]
        if command in {"execute", "resume"}:
            argv += ["--live", "--confirm-manifest-sha256", str(digest)]
        report = _json_output(
            _run(argv, runner=runner), f"Shopify uploader {command}",
        )
        if digest is not None and report.get("manifest_sha256") != digest:
            raise BindingError(
                f"Shopify uploader {command} reported a different manifest digest"
            )
        return report

    def execute(
        entry: dict, manifest_path: Path, manifest_sha256: Optional[str],
    ) -> dict:
        if not live:
            return {"status": "AWAITING_LIVE"}
        actual = _validated_manifest_digest(manifest_path, manifest_sha256)
        tank = entry.get("tank_id")
        if not tank:
            raise BindingError("Shopify execute requires tank_id")

        status_report = call_uploader("status", manifest_path, tank, actual)
        status_item = _tank_item(status_report, tank, "uploader status")
        pending = bool(
            status_item.get("pending_operation") or
            status_item.get("pending_transfer_role")
        )
        stage = status_item.get("stage")
        if pending:
            reconciliation = call_uploader("resume", manifest_path, tank, actual)
            item = _tank_item(reconciliation, tank, "uploader reconciliation")
            return {
                "status": "PENDING_RECONCILIATION",
                "uploader_status": item.get("status"),
                "error": item.get("error"),
                "report_path": reconciliation.get("report_path"),
                "manifest_sha256": actual,
            }
        if stage == "BLOCKED":
            return {
                "status": "FAILED", "error": status_item.get("last_error"),
                "manifest_sha256": actual,
            }

        execution = None
        if stage != "COMPLETED_VERIFIED":
            command = "execute" if stage in {None, "NEW"} else "resume"
            execution = call_uploader(command, manifest_path, tank, actual)
            execute_item = _tank_item(execution, tank, "uploader execution")
            uploader_status = execute_item.get("status")
            if uploader_status not in {
                READBACK_PASS, "SKIPPED_ALREADY_COMPLETED",
            }:
                pending_status = (
                    uploader_status == "PENDING_RECONCILIATION" or
                    "UNCERTAIN" in str(uploader_status) or
                    str(uploader_status).startswith("RECONCILED_") or
                    str(uploader_status).startswith("OPERATOR_CONFIRMED_")
                )
                return {
                    "status": (
                        "PENDING_RECONCILIATION" if pending_status else "FAILED"
                    ),
                    "uploader_status": uploader_status,
                    "error": execute_item.get("error"),
                    "report_path": execution.get("report_path"),
                    "manifest_sha256": actual,
                }

        verification = call_uploader("verify", manifest_path, tank, actual)
        verify_item = _tank_item(verification, tank, "uploader verification")
        verified = verify_item.get("status") == READBACK_PASS
        receipt = {
            "tank_id": tank,
            "verified_at": datetime.now(SYDNEY).isoformat() if verified else None,
            "manifest_sha256": actual,
            "execute_report_path": execution.get("report_path") if execution else None,
            "verify_report_path": verification.get("report_path"),
            "uploader_receipt": (
                _tank_item(execution, tank, "uploader execution").get("receipt")
                if execution else status_item.get("final_receipt")
            ),
            "verification": verify_item,
        }
        return {
            "status": "VERIFIED" if verified else "FAILED",
            "receipt": receipt,
            "report_path": verification.get("report_path"),
            "manifest_sha256": actual,
        }

    return execute


def _paths(value: Any) -> Iterable[Path]:
    if isinstance(value, (str, Path)):
        yield Path(value)
    elif isinstance(value, Mapping):
        for key, nested in value.items():
            if key.endswith("report_path") or key in {"report", "path"}:
                yield from _paths(nested)
            elif isinstance(nested, (Mapping, list, tuple)):
                yield from _paths(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _paths(nested)


def _verified_report_paths(state: dict) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    loaded: dict[Path, dict] = {}
    fish = state.get("fish") or {}
    entries = list(fish.values() if isinstance(fish, dict) else fish)
    eligible = [
        entry for entry in entries if isinstance(entry, dict) and
        entry.get("status") in {"VERIFIED", "PASS_WITH_ACCEPTED_EXCEPTION"}
    ]
    for entry in eligible:
        tank = entry.get("tank_id")
        receipt = entry.get("shopify_receipt")
        candidates = []
        if isinstance(receipt, dict) and receipt.get("verify_report_path"):
            candidates = [Path(receipt["verify_report_path"])]
        else:
            candidates = list(_paths(receipt))
        matched = False
        for path in candidates:
            path = path.expanduser().resolve()
            if not path.is_file() or path.suffix.lower() != ".json":
                continue
            if path not in loaded:
                try:
                    loaded[path] = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
            report = loaded[path]
            if any(
                isinstance(item, dict) and item.get("tank_id") == tank and
                item.get("status") == READBACK_PASS
                for item in (report.get("items") or [])
            ):
                if path not in seen:
                    paths.append(path)
                    seen.add(path)
                matched = True
        if not matched:
            raise BindingError(
                f"{tank or 'fish'}: independent Shopify verify report unavailable"
            )
    if eligible and not paths:
        raise BindingError("archive requires independent Shopify verify reports")
    return paths


def _inventory_csv(state: dict, batch_dir: Path) -> Optional[Path]:
    values = [state.get("inventory_csv"), state.get("inventory_csv_path")]
    manifest = state.get("manifest") or {}
    if isinstance(manifest, dict):
        values += [manifest.get("inventory_csv"), manifest.get("inventory_csv_path")]
    for value in values:
        if isinstance(value, dict):
            value = value.get("path")
        if value and Path(value).expanduser().is_file():
            return Path(value).expanduser().resolve()
    for candidate in (
        batch_dir / "reports" / "betta-inventory.csv",
        batch_dir / "manifest" / "betta-inventory.csv",
        batch_dir / "betta-inventory.csv",
    ):
        if candidate.is_file():
            return candidate.resolve()
    return None


def _state_root(manifest_path: Path) -> Optional[Path]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    configured = manifest.get("state_dir")
    if configured:
        state_dir = Path(configured).expanduser()
        if not state_dir.is_absolute():
            state_dir = (manifest_path.parent / state_dir).resolve()
        if len(state_dir.parents) >= 2:
            return state_dir.parents[1]
        return state_dir.parent
    return (manifest_path.parent / ".betta-shopify-state").resolve()


def _batch_audit_paths(
    state: dict, batch_dir: Path, verification_reports: Iterable[Path],
    inventory_csv: Optional[Path],
) -> list[Path]:
    """Collect non-secret BAU evidence that the archiver must preserve."""
    excluded = {path.resolve() for path in verification_reports}
    if inventory_csv is not None:
        excluded.add(inventory_csv.resolve())
    candidates: list[Path] = []

    reports_dir = batch_dir / "reports"
    if reports_dir.is_dir():
        candidates.extend(path for path in reports_dir.rglob("*") if path.is_file())

    evidence_dir = batch_dir / "evidence"
    if evidence_dir.is_dir():
        candidates.extend(evidence_dir.rglob("*.json"))

    state_dir = batch_dir / "state"
    for name in (
        "authority.json", "gen-budget.json", "process.json", "sources.json",
        "discord-notifications.json",
    ):
        path = state_dir / name
        if path.is_file():
            candidates.append(path)

    for path in _paths(state.get("authorisation")):
        if path.expanduser().is_file():
            candidates.append(path.expanduser())

    result: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if (
            resolved in excluded or resolved in seen or
            "secrets" in {part.lower() for part in resolved.parts}
        ):
            continue
        seen.add(resolved)
        result.append(resolved)
    return sorted(result, key=str)


def archive_runner(
    *, archive_root: Path, date: Optional[str] = None,
    exceptions_path: Optional[Path] = None, live: bool = False,
    python_executable: str = sys.executable,
    runner: Optional[Callable] = None,
) -> Callable:
    def archive(state: dict, batch_dir: Path) -> dict:
        batch_dir = Path(batch_dir).resolve()
        manifest = batch_dir / "manifest" / "shopify-production.json"
        if not manifest.is_file():
            raise BindingError(f"archive manifest missing: {manifest}")
        reports = _verified_report_paths(state)
        inventory_csv = _inventory_csv(state, batch_dir)
        audit_paths = _batch_audit_paths(
            state, batch_dir, reports, inventory_csv,
        )
        manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
        batch_id = manifest_data.get("batch_id") or state.get("batch_id")
        safe_batch = re.sub(r"[^A-Za-z0-9._-]", "_", str(batch_id or "batch"))
        effective_date = date or datetime.now(SYDNEY).date().isoformat()
        state_path = (
            Path(archive_root) / effective_date /
            f"{safe_batch}-archive-state.json"
        )
        command = "resume" if state_path.is_file() else "execute"
        argv = [
            str(python_executable), str(ARCHIVER), command,
            "--manifest", str(manifest),
            "--archive-root", str(Path(archive_root).resolve()),
        ]
        if date:
            argv += ["--date", date]
        for report in reports:
            argv += ["--verify", str(report)]
        for audit_path in audit_paths:
            argv += ["--audit-path", str(audit_path)]
        if inventory_csv is not None:
            argv += ["--inventory-csv", str(inventory_csv)]
        if exceptions_path:
            argv += ["--exceptions", str(Path(exceptions_path).resolve())]
        state_root = _state_root(manifest)
        if state_root is not None:
            argv += ["--state-root", str(state_root)]
        if live:
            argv += ["--apply"]

        result = _json_output(_run(argv, runner=runner), "Betta archive")
        if not live:
            return {"status": "AWAITING_LIVE", "archive": result}
        if result.get("mode") != "execute" or result.get("batch_status") != "COMPLETE":
            raise BindingError("archive did not report a verified COMPLETE result")
        archive_manifest = result.get("manifest")
        reported_digest = result.get("manifest_sha256")
        if not archive_manifest or not Path(archive_manifest).is_file():
            raise BindingError("archive omitted its immutable manifest")
        if _sha256_file(Path(archive_manifest)) != reported_digest:
            raise BindingError("archive manifest SHA-256 validation failed")
        records = result.get("results") or []
        if not records or any(
            record.get("status") not in {"COPIED", "ALREADY_DONE"} or
            record.get("source_sha256") != record.get("destination_sha256")
            for record in records
        ):
            raise BindingError("one or more archive files were not SHA-256 verified")
        archived_sources = {
            Path(record["source"]).resolve()
            for record in records if record.get("source")
        }
        expected_audit_sources = set(reports) | set(audit_paths)
        if any(path not in archived_sources for path in expected_audit_sources):
            raise BindingError("archive omitted one or more required audit files")
        return {
            "status": "ARCHIVED",
            "manifest": str(Path(archive_manifest).resolve()),
            "manifest_sha256": reported_digest,
            "state": result.get("state"),
            "batch_status": result.get("batch_status"),
        }

    return archive


def bind_runners(
    *, archive_root: Path, resolve_runner: Optional[Callable] = None,
    execute_runner: Optional[Callable] = None,
    preflight_runner: Optional[Callable] = None,
    archive: Optional[Callable] = None, node: str = "node",
    python: Optional[str] = None, python_executable: Optional[str] = None,
    bridge: Path = SHOPIFY_LIVE, env_file: Optional[Path] = None,
    live: bool = False,
) -> dict:
    if python and python_executable and str(python) != str(python_executable):
        raise BindingError("python and python_executable configuration disagree")
    configured_python = str(python_executable or python or sys.executable)
    runners = {
        "resolve": resolve_runner or shopify_resolve_runner(
            node=node, env_file=env_file,
        ),
        "execute": execute_runner or shopify_execute_runner(
            live=live, python_executable=configured_python, node=node,
            bridge=bridge, env_file=env_file,
        ),
        "archive": archive or archive_runner(
            archive_root=archive_root, live=live,
            python_executable=configured_python,
        ),
    }
    if live or preflight_runner is not None:
        runners["preflight"] = preflight_runner or shopify_preflight_runner(
            python_executable=configured_python, node=node, bridge=bridge,
            env_file=env_file,
        )
    return runners
