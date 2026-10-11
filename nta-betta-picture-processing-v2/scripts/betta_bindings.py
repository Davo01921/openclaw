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
from datetime import datetime, timezone
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
    allowed_returncodes: frozenset[int] = frozenset({0}),
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
    if result.returncode not in allowed_returncodes:
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


def _aware_timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise BindingError(f"{field} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BindingError(f"{field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BindingError(f"{field} must include a timezone")
    return value


def _verified_report(
    path: Path, *, tank: str, batch_id: str, manifest_sha256: str,
    expected_sha256: Optional[str] = None,
    expected_created_at: Optional[str] = None,
) -> tuple[dict, str]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise BindingError(f"independent Shopify verify report missing: {path}")
    digest = _sha256_file(path)
    if expected_sha256 is not None and digest != expected_sha256:
        raise BindingError("independent Shopify verify report was replaced")
    report = _json_output(
        path.read_text(encoding="utf-8"), "independent Shopify verify report",
    )
    created_at = _aware_timestamp(
        report.get("created_at"), "Shopify verify report created_at",
    )
    if expected_created_at is not None and created_at != expected_created_at:
        raise BindingError("independent Shopify verify report timestamp changed")
    if report.get("command") != "verify":
        raise BindingError("independent Shopify report command is not verify")
    if report.get("batch_id") != batch_id:
        raise BindingError("independent Shopify verify report batch mismatch")
    if report.get("manifest_sha256") != manifest_sha256:
        raise BindingError("independent Shopify verify report manifest mismatch")
    item = _tank_item(report, tank, "independent Shopify verify report")
    if len(report.get("items") or []) != 1 or item.get("status") != READBACK_PASS:
        raise BindingError(
            f"independent Shopify verify report is not one exact PASS for {tank}"
        )
    return report, digest


def _manifest_data(manifest_path: Path) -> dict:
    try:
        data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BindingError("persisted manifest is unreadable") from exc
    if not isinstance(data, dict) or not isinstance(data.get("batch_id"), str):
        raise BindingError("persisted manifest batch_id is missing")
    return data


def _uploader_state_path(
    manifest_path: Path, manifest_sha256: str, manifest: Mapping[str, Any],
) -> Path:
    configured = manifest.get("state_dir")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = Path(manifest_path).parent / path
        return path.resolve() / "state.json"
    return (
        Path(manifest_path).parent / ".betta-shopify-state" /
        str(manifest["batch_id"]) / manifest_sha256[:12] / "state.json"
    ).resolve()


def _local_uploader_item(
    manifest_path: Path, manifest_sha256: str, tank: str,
) -> Optional[dict]:
    manifest = _manifest_data(manifest_path)
    state_path = _uploader_state_path(manifest_path, manifest_sha256, manifest)
    if not state_path.is_file():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BindingError("uploader state is unreadable") from exc
    if (
        state.get("batch_id") != manifest["batch_id"] or
        state.get("manifest_sha256") != manifest_sha256
    ):
        raise BindingError("uploader state identity mismatch")
    item = (state.get("items") or {}).get(tank)
    if not isinstance(item, dict):
        raise BindingError(f"uploader state missing {tank}")
    return item


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
            raw_product = snapshot["raw_product"]
            before = snapshot["before"]
            location = snapshot["location"]
            fetched_at = _aware_timestamp(
                snapshot["fetched_at"], "Shopify resolve fetched_at",
            )
            if (
                snapshot["tank_id"] != tank or snapshot["query"] != tank or
                snapshot["source"] != "FRESH_SHOPIFY_READ"
            ):
                raise BindingError("Shopify resolve identity evidence mismatch")
            if not isinstance(raw_product, dict) or not isinstance(before, dict):
                raise BindingError("Shopify resolve snapshot is incomplete")
            quantities = [before[name] for name in ("inventory", "on_hand", "committed")]
            if any(isinstance(value, bool) or not isinstance(value, int) for value in quantities):
                raise BindingError("Shopify resolve inventory quantities are incomplete")
            variants = raw_product["variants"]
            media = raw_product["media"]
            variant_nodes = variants["nodes"]
            if (
                variants["pageInfo"].get("hasNextPage") is not False or
                media["pageInfo"].get("hasNextPage") is not False or
                len(variant_nodes) != 1
            ):
                raise BindingError("Shopify resolve raw product is truncated or ambiguous")
            variant = variant_nodes[0]
            levels = variant["inventoryItem"]["inventoryLevels"]
            level_nodes = levels["nodes"]
            if levels["pageInfo"].get("hasNextPage") is not False or len(level_nodes) != 1:
                raise BindingError("Shopify resolve inventory locations are truncated or ambiguous")
            level = level_nodes[0]
            if (
                raw_product["id"] != snapshot["id"] or
                variant["id"] != snapshot["variant_id"] or
                variant["inventoryItem"]["id"] != snapshot["inventory_item_id"] or
                level["location"]["id"] != snapshot["location_id"] or
                not isinstance(location, dict) or location.get("id") != snapshot["location_id"]
            ):
                raise BindingError("Shopify resolve raw product identifiers mismatch")
            product = {
                "id": snapshot["id"],
                "variant_id": snapshot["variant_id"],
                "location_id": snapshot["location_id"],
                "inventory_item_id": snapshot["inventory_item_id"],
                "source": snapshot["source"],
                "tank_id": snapshot["tank_id"],
                "before": before,
                "raw_snapshot": raw_product,
                "fetched_at": fetched_at,
                "query": snapshot["query"],
            }
        except (KeyError, TypeError) as exc:
            raise BindingError(
                "Shopify resolve snapshot is missing required protected detail"
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
        *, live_command: bool = True,
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
        if command in {"execute", "resume"} and live_command:
            argv += ["--live", "--confirm-manifest-sha256", str(digest)]
        report = _json_output(
            _run(
                argv, runner=runner,
                allowed_returncodes=(
                    frozenset({0, 3}) if command == "verify"
                    else frozenset({0})
                ),
            ),
            f"Shopify uploader {command}",
        )
        if digest is not None and report.get("manifest_sha256") != digest:
            raise BindingError(
                f"Shopify uploader {command} reported a different manifest digest"
            )
        return report

    def finish_verification(
        *, tank: str, manifest_path: Path, actual: str,
        manifest: Mapping[str, Any], execution: Optional[dict],
        status_item: Mapping[str, Any], pending_status: str = "FAILED",
    ) -> dict:
        verification = call_uploader("verify", manifest_path, tank, actual)
        verify_item = _tank_item(verification, tank, "uploader verification")
        if verify_item.get("status") != READBACK_PASS:
            return {
                "status": pending_status,
                "uploader_status": verify_item.get("status"),
                "report_path": verification.get("report_path"),
                "manifest_sha256": actual,
            }
        report_path = verification.get("report_path")
        report, report_sha256 = _verified_report(
            Path(report_path), tank=tank, batch_id=str(manifest["batch_id"]),
            manifest_sha256=actual,
        )
        local = _local_uploader_item(manifest_path, actual, tank)
        if local and (local.get("pending_mutation") or local.get("pending_transfer")):
            return {
                "status": "PENDING_RECONCILIATION",
                "uploader_status": "LOCAL_INTENT_STILL_PENDING",
                "report_path": report_path,
                "manifest_sha256": actual,
            }
        receipt = {
            "tank_id": tank,
            "batch_id": manifest["batch_id"],
            "verified_at": datetime.now(SYDNEY).isoformat(),
            "manifest_sha256": actual,
            "execute_report_path": execution.get("report_path") if execution else None,
            "verify_report_path": str(Path(report_path).resolve()),
            "verify_report_sha256": report_sha256,
            "verify_report_created_at": report["created_at"],
            "uploader_receipt": (
                _tank_item(execution, tank, "uploader execution").get("receipt")
                if execution else (
                    local.get("final_receipt") if local
                    else status_item.get("final_receipt")
                )
            ),
            "verification": verify_item,
        }
        return {
            "status": "VERIFIED",
            "receipt": receipt,
            "report_path": str(Path(report_path).resolve()),
            "manifest_sha256": actual,
        }

    def execute(
        entry: dict, manifest_path: Path, manifest_sha256: Optional[str],
        *, reconcile_only: bool = False,
    ) -> dict:
        if not live and not reconcile_only:
            return {"status": "AWAITING_LIVE"}
        actual = _validated_manifest_digest(manifest_path, manifest_sha256)
        manifest = _manifest_data(manifest_path)
        tank = entry.get("tank_id")
        if not tank:
            raise BindingError("Shopify execute requires tank_id")

        status_report = call_uploader("status", manifest_path, tank, actual)
        status_item = _tank_item(status_report, tank, "uploader status")
        pending = bool(
            status_item.get("pending_operation") or
            status_item.get("pending_transfer_role")
        )
        local_item = _local_uploader_item(manifest_path, actual, tank)
        pending = pending or bool(
            local_item and (
                local_item.get("pending_mutation") or
                local_item.get("pending_transfer")
            )
        )
        stage = status_item.get("stage")
        if pending or reconcile_only:
            if pending:
                reconciliation = call_uploader(
                    "resume", manifest_path, tank, actual, live_command=False,
                )
                item = _tank_item(
                    reconciliation, tank, "uploader reconciliation",
                )
                local_after = _local_uploader_item(manifest_path, actual, tank)
                if local_after and (
                    local_after.get("pending_mutation") or
                    local_after.get("pending_transfer")
                ):
                    return {
                        "status": "PENDING_RECONCILIATION",
                        "uploader_status": item.get("status"),
                        "error": item.get("error"),
                        "report_path": reconciliation.get("report_path"),
                        "manifest_sha256": actual,
                    }
            return finish_verification(
                tank=tank, manifest_path=manifest_path, actual=actual,
                manifest=manifest, execution=None, status_item=status_item,
                pending_status="PENDING_RECONCILIATION",
            )
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

        return finish_verification(
            tank=tank, manifest_path=manifest_path, actual=actual,
            manifest=manifest, execution=execution, status_item=status_item,
        )

    return execute


def shopify_reconcile_runner(
    *, python_executable: str = sys.executable,
    node: Optional[str] = None, bridge: Optional[Path] = None,
    env_file: Optional[Path] = None, runner: Optional[Callable] = None,
) -> Callable:
    """Return a Shopify-read-only uncertain-state reconciliation runner."""
    execute = shopify_execute_runner(
        live=False, python_executable=python_executable, node=node,
        bridge=bridge, env_file=env_file, runner=runner,
    )

    def reconcile(
        entry: dict, manifest_path: Path, manifest_sha256: Optional[str],
    ) -> dict:
        return execute(
            entry, manifest_path, manifest_sha256, reconcile_only=True,
        )

    return reconcile


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


def _verified_report_paths(
    state: dict, *, batch_id: str, manifest_sha256: str,
) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    fish = state.get("fish") or {}
    entries = list(fish.values() if isinstance(fish, dict) else fish)
    eligible = [
        entry for entry in entries if isinstance(entry, dict) and
        entry.get("status") in {"VERIFIED", "PASS_WITH_ACCEPTED_EXCEPTION"}
    ]
    for entry in eligible:
        tank = entry.get("tank_id")
        receipt = entry.get("shopify_receipt")
        if not isinstance(receipt, dict):
            raise BindingError(f"{tank or 'fish'}: Shopify receipt is missing")
        if (
            receipt.get("tank_id") != tank or
            receipt.get("batch_id") != batch_id or
            receipt.get("manifest_sha256") != manifest_sha256
        ):
            raise BindingError(f"{tank or 'fish'}: Shopify receipt identity mismatch")
        path_value = receipt.get("verify_report_path")
        report_digest = receipt.get("verify_report_sha256")
        report_created_at = receipt.get("verify_report_created_at")
        if (
            not isinstance(path_value, str) or
            not isinstance(report_digest, str) or
            re.fullmatch(r"[0-9a-f]{64}", report_digest) is None or
            not isinstance(report_created_at, str)
        ):
            raise BindingError(
                f"{tank or 'fish'}: bound independent verify report is missing"
            )
        _aware_timestamp(
            report_created_at,
            f"{tank or 'fish'} Shopify receipt verify_report_created_at",
        )
        path = Path(path_value).expanduser().resolve()
        _verified_report(
            path, tank=str(tank), batch_id=batch_id,
            manifest_sha256=manifest_sha256,
            expected_sha256=report_digest,
            expected_created_at=report_created_at,
        )
        if path not in seen:
            paths.append(path)
            seen.add(path)
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
        return state_dir.resolve()
    return (manifest_path.parent / ".betta-shopify-state").resolve()


def _batch_audit_paths(
    state: dict, batch_dir: Path, verification_reports: Iterable[Path],
    inventory_csv: Optional[Path], *, batch_id: str,
) -> list[Path]:
    """Freeze and return one immutable set of non-secret BAU evidence."""
    state_dir = batch_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    snapshot = state_dir / "archive-process-snapshot.json"
    ledger = state_dir / "archive-audit-inputs.json"

    if ledger.is_file():
        data = _json_output(
            ledger.read_text(encoding="utf-8"), "archive audit-input ledger",
        )
        if (
            data.get("schema") != "nta-betta-archive-audit-inputs-v1" or
            data.get("batch_id") != batch_id or
            not isinstance(data.get("files"), list)
        ):
            raise BindingError("archive audit-input ledger identity mismatch")
        result = []
        for record in data["files"]:
            if not isinstance(record, dict):
                raise BindingError("archive audit-input ledger is malformed")
            path = Path(record.get("path", "")).expanduser().resolve()
            if not path.is_file() or _sha256_file(path) != record.get("sha256"):
                raise BindingError(f"frozen archive audit input changed: {path}")
            result.append(path)
        return result + [ledger.resolve()]

    process_state = state_dir / "process.json"
    if not snapshot.is_file():
        if not process_state.is_file():
            raise BindingError("process state is unavailable for archive snapshot")
        try:
            fd = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(process_state.read_bytes())
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(snapshot, 0o444)
        except FileExistsError:
            pass

    excluded = {path.resolve() for path in verification_reports}
    if inventory_csv is not None:
        excluded.add(inventory_csv.resolve())
    candidates: list[Path] = []

    reports_dir = batch_dir / "reports"
    if reports_dir.is_dir():
        candidates.extend(
            path for path in reports_dir.rglob("*")
            if path.is_file() and not path.name.startswith("archive-")
        )

    evidence_dir = batch_dir / "evidence"
    if evidence_dir.is_dir():
        candidates.extend(evidence_dir.rglob("*.json"))

    for name in (
        "authority.json", "gen-budget.json", "sources.json",
        "discord-notifications.json",
    ):
        path = state_dir / name
        if path.is_file():
            candidates.append(path)

    for path in _paths(state.get("authorisation")):
        if path.expanduser().is_file():
            candidates.append(path.expanduser())

    candidates.append(snapshot)
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
    result = sorted(result, key=str)
    ledger_data = {
        "schema": "nta-betta-archive-audit-inputs-v1",
        "batch_id": batch_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": [
            {"path": str(path), "sha256": _sha256_file(path)}
            for path in result
        ],
    }
    payload = (json.dumps(
        ledger_data, indent=2, sort_keys=True, ensure_ascii=False,
    ) + "\n").encode("utf-8")
    try:
        fd = os.open(ledger, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(ledger, 0o444)
    except FileExistsError as exc:
        raise BindingError(
            "archive audit-input ledger appeared concurrently; retry after inspection"
        ) from exc
    return result + [ledger.resolve()]


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
        manifest_data = _manifest_data(manifest)
        manifest_sha256 = _sha256_file(manifest)
        reports = _verified_report_paths(
            state, batch_id=manifest_data["batch_id"],
            manifest_sha256=manifest_sha256,
        )
        inventory_csv = _inventory_csv(state, batch_dir)
        audit_paths = _batch_audit_paths(
            state, batch_dir, reports, inventory_csv,
            batch_id=manifest_data["batch_id"],
        )
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
    reconcile_runner: Optional[Callable] = None,
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
    if live or reconcile_runner is not None:
        runners["reconcile"] = reconcile_runner or shopify_reconcile_runner(
            python_executable=configured_python, node=node, bridge=bridge,
            env_file=env_file,
        )
    return runners
