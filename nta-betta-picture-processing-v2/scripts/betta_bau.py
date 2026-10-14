#!/usr/bin/env python3
"""Fail-closed BAU dispatcher for the Betta processing pipeline.

The dispatcher is intentionally a thin production boundary.  It selects an
immutable set of stable originals, owns one batch at a time, wires the existing
orchestrator, and records Discord delivery intent before attempting a send.
It never discovers work from arbitrary ACTIVE batches and it never retries a
failed or uncertain dispatcher outcome.

``--smoke`` and ``--status`` are read-only.  ``--once`` is disabled unless both
the JSON configuration and standing policy are enabled.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import inspect
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import betta_adapters  # noqa: E402
import betta_batches  # noqa: E402
import betta_bindings  # noqa: E402
import betta_budget  # noqa: E402
import betta_policy  # noqa: E402
import betta_process  # noqa: E402
import betta_watch  # noqa: E402


CONFIG_SCHEMA = "nta-betta-bau-config-v1"
SOURCES_SCHEMA = "nta-betta-bau-sources-v1"
OUTCOME_SCHEMA = "nta-betta-bau-outcome-v1"
NOTIFICATIONS_SCHEMA = "nta-betta-bau-notifications-v1"
EXPECTED_DISCORD_TARGET = "channel:1542019252683546645"
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class DispatcherError(RuntimeError):
    """A fail-closed dispatcher decision."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_json(path: Path) -> dict:
    with Path(path).open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise DispatcherError(f"JSON object required: {path}")
    return data


def load_config(path: Path) -> dict:
    data = _read_json(path)
    if data.get("schema") != CONFIG_SCHEMA:
        raise DispatcherError("unsupported BAU configuration schema")
    return data


def _canonical_absolute(value: object) -> bool:
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        return False
    return os.path.realpath(value) == value


def validate_config(config: dict, *, production: bool = False) -> list[str]:
    """Return blockers without reading credential contents or changing state."""
    blockers: list[str] = []
    if config.get("schema") != CONFIG_SCHEMA:
        blockers.append("unsupported configuration schema")
    paths = config.get("paths")
    if not isinstance(paths, dict):
        return blockers + ["paths must be an object"]
    required = (
        "python", "node", "openclaw", "bridge", "env", "intake", "batches",
        "archive", "telemetry", "registry", "policy", "dispatcher_lock",
    )
    for name in required:
        value = paths.get(name)
        executable_path = name in {"python", "node", "openclaw"}
        if not (isinstance(value, str) and Path(value).is_absolute()) or (not executable_path and not _canonical_absolute(value)):
            blockers.append(f"paths.{name} must be a canonical absolute path")

    discord = config.get("discord") or {}
    if discord.get("channel") != "discord":
        blockers.append("discord.channel must be discord")
    if discord.get("target") != EXPECTED_DISCORD_TARGET:
        blockers.append("discord.target is not the approved #betta-processing channel")

    settle = config.get("settle_seconds", betta_watch.DEFAULT_SETTLE_SECONDS)
    if not isinstance(settle, (int, float)) or settle < 0:
        blockers.append("settle_seconds must be non-negative")

    if production and not blockers:
        for name in ("python", "node", "openclaw"):
            path = Path(paths[name])
            if not path.is_file() or not os.access(path, os.X_OK):
                blockers.append(f"paths.{name} is not executable")
        for name in ("bridge", "env", "policy"):
            if not Path(paths[name]).is_file():
                blockers.append(f"paths.{name} does not exist")
        if not Path(paths["intake"]).is_dir():
            blockers.append("paths.intake is not a directory")
        # The configured environment file is only existence-checked.  Its
        # contents are credentials and are never read by this dispatcher.
    return blockers


def _readonly_registry_hashes(path: Path) -> set[str]:
    """Read a registry without creating it (used by smoke/status)."""
    path = Path(path)
    if not path.is_file():
        return set()
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
        try:
            return {row[0] for row in con.execute("SELECT source_sha256 FROM processed")
                    if isinstance(row[0], str) and HASH_RE.fullmatch(row[0])}
        finally:
            con.close()
    except sqlite3.Error as exc:
        raise DispatcherError(f"processed registry unreadable: {exc}") from exc


def _manifest_hashes(data: dict) -> set[str]:
    """Extract original-source hashes only, never hero/QA hashes."""
    found: set[str] = set()
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        value = item.get("source_sha256")
        original = item.get("original")
        if isinstance(original, dict):
            value = original.get("sha256") or value
        if isinstance(value, str) and HASH_RE.fullmatch(value):
            found.add(value)
    for record in data.get("selected_sources") or data.get("sources") or []:
        if isinstance(record, dict):
            value = record.get("sha256") or record.get("source_sha256")
            if isinstance(value, str) and HASH_RE.fullmatch(value):
                found.add(value)
    for record in data.get("files") or []:
        if not isinstance(record, dict) or record.get("role") != "original":
            continue
        value = record.get("source_sha256") or record.get("destination_sha256")
        if isinstance(value, str) and HASH_RE.fullmatch(value):
            found.add(value)
    return found


def _historical_manifest_paths(config: dict) -> list[Path]:
    """Find evidence for completed batches and archived production history."""
    paths = config["paths"]
    result: set[Path] = set()
    batches_root = Path(paths["batches"])
    registry_path = batches_root / "registry.json"
    if registry_path.is_file():
        try:
            registry = _read_json(registry_path)
            for entry in registry.get("batches") or []:
                if not isinstance(entry, dict) or entry.get("status") != betta_batches.COMPLETE:
                    continue
                directory = Path(entry.get("path") or (batches_root / str(entry.get("batch_id", ""))))
                if directory.is_dir():
                    result.update(directory.glob("manifest/*.json"))
                    result.update(directory.glob("state/sources.json"))
        except (OSError, ValueError, DispatcherError):
            # A corrupt lifecycle registry is reported elsewhere by status.  Do
            # not guess that an ACTIVE/manual batch is historical.
            pass
    archive_root = Path(paths["archive"])
    if archive_root.is_dir():
        result.update(archive_root.rglob("*manifest*.json"))
        result.update(archive_root.rglob("sources.json"))
    return sorted(path for path in result if path.is_file())


def historical_hashes(config: dict) -> dict[str, str]:
    """Return source hash -> batch id from immutable historical evidence."""
    found: dict[str, str] = {}
    for path in _historical_manifest_paths(config):
        try:
            data = _read_json(path)
        except (OSError, ValueError, DispatcherError):
            continue
        batch_id = str(data.get("batch_id") or "historical")
        for digest in _manifest_hashes(data):
            found.setdefault(digest, batch_id)
    return found


def seed_processed_registry(config: dict) -> int:
    """Add completed historical source hashes without changing existing rows."""
    seeds = historical_hashes(config)
    path = Path(config["paths"]["registry"])
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS processed (source_sha256 TEXT PRIMARY KEY, "
                    "batch_id TEXT, processed_at TEXT)")
        before = con.total_changes
        for digest, batch_id in sorted(seeds.items()):
            con.execute("INSERT OR IGNORE INTO processed "
                        "(source_sha256,batch_id,processed_at) VALUES (?,?,?)",
                        (digest, batch_id, _utc_now()))
        con.commit()
        return con.total_changes - before
    finally:
        con.close()


def _deduplicate_candidates(candidates: Iterable[dict]) -> list[dict]:
    selected: list[dict] = []
    seen: set[str] = set()
    for candidate in sorted(candidates, key=lambda item: str(item.get("path", ""))):
        digest = candidate.get("sha256")
        if not isinstance(digest, str) or not HASH_RE.fullmatch(digest) or digest in seen:
            continue
        path = os.path.realpath(str(candidate.get("path", "")))
        if not Path(path).is_absolute():
            continue
        selected.append({"path": path, "sha256": digest,
                         "size": int(candidate.get("size", Path(path).stat().st_size))})
        seen.add(digest)
    return selected


def scan_candidates(config: dict, *, now: Optional[float] = None,
                    known_hashes: Optional[set[str]] = None,
                    scanner: Callable = betta_watch.scan) -> list[dict]:
    candidates = scanner(
        Path(config["paths"]["intake"]),
        now=time.time() if now is None else now,
        settle_seconds=float(config.get("settle_seconds", betta_watch.DEFAULT_SETTLE_SECONDS)),
        known_hashes=known_hashes or set(),
    )
    return _deduplicate_candidates(candidates)


@contextmanager
def dispatcher_lock(path: Path):
    """One non-blocking global lock: launchd overlaps exit safely."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise DispatcherError("another BAU dispatcher is active") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _owned_active_batches(config: dict) -> tuple[list[dict], list[dict]]:
    owned: list[dict] = []
    unmanaged: list[dict] = []
    root = Path(config["paths"]["batches"])
    for entry in betta_batches.active_batches(root):
        directory = Path(entry.get("path") or (root / entry["batch_id"]))
        marker = directory / "state" / "sources.json"
        try:
            data = _read_json(marker) if marker.is_file() else {}
        except (OSError, ValueError, DispatcherError):
            data = {}
        if (data.get("schema") == SOURCES_SCHEMA and data.get("dispatcher_owned") is True
                and data.get("batch_id") == entry.get("batch_id")):
            record = dict(entry)
            record["sources"] = data
            owned.append(record)
        else:
            unmanaged.append(entry)
    return owned, unmanaged


def _zero_mutation_terminal_state(state: object) -> bool:
    """True when a terminal process provably performed no Shopify mutation.

    A batch where every fish was quarantined and nothing executed cannot produce
    the archive receipt that the finalization gate requires, because there is no
    manifest/readback evidence to bind.  It is safe to resolve it as a truthful
    terminal PARTIAL: no write happened, so no write verification is owed.
    """
    if not isinstance(state, dict):
        return False
    if state.get("status") not in ("COMPLETE", "PARTIAL"):
        return False
    if state.get("executed"):
        return False
    if isinstance(state.get("archive_receipt"), dict):
        return False
    fish = state.get("fish")
    if not isinstance(fish, dict) or not fish:
        return False
    if not all(isinstance(entry, dict) for entry in fish.values()):
        return False
    return all(entry.get("status") in ("QUARANTINED", "FAILED")
               for entry in fish.values())


def _terminal_summary(state: dict) -> dict:
    """Summarise a terminal process state without altering it."""
    fish = state.get("fish") or {}
    return {
        "batch_id": state.get("batch_id"),
        "stage": state.get("stage", "UNKNOWN"),
        "status": state.get("status", "PARTIAL"),
        "published": len(state.get("executed") or []),
        "quarantined": sum(1 for entry in fish.values() if isinstance(entry, dict)
                           and entry.get("status") == "QUARANTINED"),
        "manifest_sha256": state.get("manifest_sha256"),
    }


def _resumable(entry: dict) -> bool:
    batch_dir = Path(entry["path"])
    outcome_path = batch_dir / "state" / "bau-outcome.json"
    if outcome_path.is_file():
        try:
            outcome = _read_json(outcome_path)
        except (OSError, ValueError, DispatcherError):
            return False
        if outcome.get("resumable") is not True:
            return False
    state_path = batch_dir / "state" / "process.json"
    if not state_path.is_file():
        return True
    try:
        state = _read_json(state_path)
    except (OSError, ValueError, DispatcherError):
        return False
    status = state.get("status")
    if status in ("ACTIVE", "RECONCILIATION_PENDING", "FINALIZATION_PENDING"):
        return True
    # A process can reach its inert terminal checkpoint immediately before the
    # final audit snapshot.  Only a positive archive receipt makes that state
    # eligible for finalization-only recovery.
    receipt = state.get("archive_receipt")
    return (status in ("COMPLETE", "PARTIAL") and state.get("stage") == "ARCHIVED"
            and isinstance(receipt, dict)
            and receipt.get("status") == "ARCHIVED"
            and receipt.get("batch_status") == "COMPLETE")


def _persist_sources(entry: dict, sources: list[dict]) -> dict:
    path = Path(entry["path"]) / "state" / "sources.json"
    if path.exists():
        raise DispatcherError("immutable batch sources already exist")
    record = {
        "schema": SOURCES_SCHEMA,
        "dispatcher_owned": True,
        "batch_id": entry["batch_id"],
        "selected_at": _utc_now(),
        "selected_sources": sources,
    }
    _atomic_write(path, record)
    os.chmod(path, 0o444)
    return record


def _record_selected(registry_path: Path, batch_id: str, sources: list[dict]) -> None:
    registry = betta_watch.ProcessedRegistry(registry_path)
    for source in sources:
        registry.record(source["sha256"], batch_id)


def _call_supported(callable_: Callable, kwargs: dict):
    signature = inspect.signature(callable_)
    accepts_any = any(p.kind == inspect.Parameter.VAR_KEYWORD
                      for p in signature.parameters.values())
    selected = kwargs if accepts_any else {k: v for k, v in kwargs.items()
                                           if k in signature.parameters}
    return callable_(**selected)


def _wire_and_process(config: dict, policy, entry: dict, *, deps: dict) -> dict:
    paths = config["paths"]
    batch_dir = Path(entry["path"])
    requested_generation = config.get("live_generation") is True
    requested_shopify = config.get("live_shopify") is True
    live_generation = requested_generation and policy.enabled() and policy.paid_generation_authorised()
    policy_data = getattr(policy, "data", {})
    live_shopify = (requested_shopify and policy.enabled()
                    and policy_data.get("automatic_batch_authorisation") is True)
    if requested_generation and not live_generation:
        raise DispatcherError("live generation requested but policy does not authorise it")
    if requested_shopify and not live_shopify:
        raise DispatcherError("live Shopify requested but automatic manifest authority is disabled")

    bind = deps.get("bind_runners", betta_bindings.bind_runners)
    runners = _call_supported(bind, {
        "archive_root": Path(paths["archive"]),
        "node": paths["node"],
        "python": paths["python"],
        "python_executable": paths["python"],
        "bridge": Path(paths["bridge"]),
        "env_file": Path(paths["env"]),
        "live": live_shopify,
        "live_shopify": live_shopify,
    })
    budget_factory = deps.get("budget_factory", betta_budget.GenerationBudget)
    budget = budget_factory(batch_dir / "state" / "gen-budget.json",
                            batch_id=entry["batch_id"], limits=policy.generation_budget())
    make = deps.get("make_adapters", betta_adapters.make_adapters)
    selected_sources = entry["sources"]["selected_sources"]
    adapters = _call_supported(make, {
        "batch_id": entry["batch_id"], "batch_dir": batch_dir,
        "intake_dir": Path(paths["intake"]),
        "telemetry_db": Path(paths["telemetry"]), "policy": policy,
        "live_shopify": live_shopify, "live_generation": live_generation,
        "runners": runners, "processed_registry": Path(paths["registry"]),
        "budget": budget, "selected_sources": selected_sources,
    })
    processor = deps.get("process_batch", betta_process.process_batch)
    return processor(batch_dir, entry["batch_id"], adapters=adapters, policy=policy)


def _positive_archive_receipt(batch_dir: Path) -> bool:
    path = Path(batch_dir) / "state" / "process.json"
    if not path.is_file():
        return False
    try:
        state = _read_json(path)
    except (OSError, ValueError, DispatcherError):
        return False
    receipt = state.get("archive_receipt")
    return (state.get("status") in ("COMPLETE", "PARTIAL")
            and state.get("stage") == "ARCHIVED"
            and isinstance(receipt, dict) and receipt.get("status") == "ARCHIVED"
            and receipt.get("batch_status") == "COMPLETE")


def _verify_finalization(result: object, batch_dir: Path, config: dict) -> dict:
    if not isinstance(result, dict) or result.get("status") != "FINALIZED":
        raise DispatcherError("finalizer did not return FINALIZED")
    for field in ("receipt_path", "archive_receipt_path", "receipt_sha256",
                  "archive_completed_at"):
        if not isinstance(result.get(field), str) or not result[field]:
            raise DispatcherError(f"finalizer omitted {field}")
    receipt_path = Path(result["receipt_path"])
    if (not receipt_path.is_absolute() or receipt_path.is_symlink() or not receipt_path.is_file()
            or os.path.commonpath((str(receipt_path.resolve()), str(Path(batch_dir).resolve())))
            != str(Path(batch_dir).resolve())):
        raise DispatcherError("finalization receipt is outside the batch or missing")
    digest = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    if digest != result["receipt_sha256"] or not HASH_RE.fullmatch(digest):
        raise DispatcherError("finalization receipt SHA-256 mismatch")
    archive_receipt = Path(result["archive_receipt_path"])
    archive_root = Path(config["paths"]["archive"]).resolve()
    if (not archive_receipt.is_absolute() or archive_receipt.is_symlink()
            or not archive_receipt.is_file()
            or os.path.commonpath((str(archive_receipt.resolve()), str(archive_root)))
            != str(archive_root)):
        raise DispatcherError("archived finalization receipt is outside the archive or missing")
    if archive_receipt.read_bytes() != receipt_path.read_bytes():
        raise DispatcherError("local and archived finalization receipts differ")
    receipt = _read_json(receipt_path)
    records = receipt.get("files")
    if not isinstance(records, list) or not records:
        raise DispatcherError("finalization receipt has no archived audit files")
    for record in records:
        if not isinstance(record, dict):
            raise DispatcherError("finalization receipt file record is invalid")
        destination = Path(str(record.get("destination", "")))
        expected = record.get("sha256")
        if (not destination.is_absolute() or destination.is_symlink() or not destination.is_file()
                or os.path.commonpath((str(destination.resolve()), str(archive_root)))
                != str(archive_root)
                or not isinstance(expected, str) or not HASH_RE.fullmatch(expected)
                or hashlib.sha256(destination.read_bytes()).hexdigest() != expected):
            raise DispatcherError("archived final audit file failed hash verification")
    return result


def _reap_zero_mutation_batch(config: dict, entry: dict, seeded: int, *, deps: dict) -> dict:
    """Resolve one provably mutation-free terminal batch without reopening it."""
    state = entry["process"]
    summary = _terminal_summary(state)
    if summary["published"]:
        raise DispatcherError("zero-mutation reconciliation found published fish")
    finalized = dict(summary)
    finalized["finalization"] = {
        "status": "NOT_REQUIRED_NO_MUTATIONS",
        "reason": "no publishable fish and no Shopify mutations were performed",
    }
    actionable = _actionable_status(summary)
    outcome = {"schema": OUTCOME_SCHEMA, "recorded_at": _utc_now(),
               "actionable_status": actionable, "resumable": False, "summary": finalized}
    _atomic_write(Path(entry["path"]) / "state" / "bau-outcome.json", outcome)
    closer = deps.get("close_batch", betta_batches.close_batch)
    close_status = (betta_batches.COMPLETE if actionable == "COMPLETE"
                    else betta_batches.ABANDONED)
    closer(Path(config["paths"]["batches"]), entry["batch_id"], close_status)
    notification = notify_discord(
        config, Path(entry["path"]), summary,
        command_runner=deps.get("command_runner", _default_command_runner),
    )
    result = dict(summary)
    result.update({"status": "RECONCILED", "actionable_status": actionable,
                   "reconciled": True, "finalization": finalized["finalization"],
                   "notification": notification, "seeded_hashes": seeded})
    return result


def _finalize_if_required(config: dict, entry: dict, summary: dict, *, deps: dict) -> dict:
    """Apply the final immutable audit gate after process/archive completion."""
    if summary.get("status") not in ("COMPLETE", "PARTIAL"):
        return summary
    # Injected legacy process fixtures intentionally bypass production
    # finalization unless they explicitly inject a finalizer too.
    required = "make_adapters" not in deps or "finalize" in deps
    if not required:
        return summary
    pending = dict(summary)
    if not _positive_archive_receipt(Path(entry["path"])):
        # A terminal batch that provably performed no Shopify mutation cannot
        # produce the archive receipt this gate requires.  Resolve it truthfully
        # as PARTIAL; the mutating-batch archive contract is unchanged.
        try:
            state = _read_json(Path(entry["path"]) / "state" / "process.json")
        except (OSError, ValueError, DispatcherError):
            state = None
        if _zero_mutation_terminal_state(state):
            resolved = dict(summary)
            resolved["finalization"] = {
                "status": "NOT_REQUIRED_NO_MUTATIONS",
                "reason": "no publishable fish and no Shopify mutations were performed",
            }
            return resolved
        pending.update({"status": "FINALIZATION_PENDING",
                        "reason": "verified archive receipt is not available"})
        return pending
    try:
        finalizer = deps.get("finalize")
        if finalizer is None:
            from betta_bau_finalize import finalize as finalizer
        result = _verify_finalization(
            finalizer(config, Path(entry["path"]), summary), Path(entry["path"]), config)
    except Exception as exc:
        pending.update({"status": "FINALIZATION_PENDING",
                        "reason": "final audit snapshot is pending",
                        "error_type": type(exc).__name__})
        return pending
    completed = dict(summary)
    completed["finalization"] = result
    return completed


def _actionable_status(summary: dict) -> str:
    status = str(summary.get("status", "BLOCKED")).upper()
    if status == "COMPLETE":
        return "COMPLETE"
    if status == "PARTIAL":
        return "PARTIAL"
    return "BLOCKED"


def _notification_text(summary: dict, actionable: str) -> str:
    reason = summary.get("reason")
    reason_text = f" reason {reason};" if reason else ""
    return (f"Betta BAU {actionable.lower()}: batch {summary.get('batch_id', 'unknown')}; "
            f"published {int(summary.get('published', 0))}; "
            f"quarantined {int(summary.get('quarantined', 0))}; "
            f"stage {summary.get('stage', 'unknown')}; status {summary.get('status', actionable)};"
            f"{reason_text}").rstrip(";") + "."


def _default_command_runner(argv: list[str]) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise DispatcherError(f"Discord command failed with exit code {result.returncode}")
    return result.stdout


def notify_discord(config: dict, batch_dir: Path, summary: dict, *,
                   command_runner: Callable = _default_command_runner) -> dict:
    """Send once after a terminal/actionable outcome, with durable uncertainty."""
    actionable = _actionable_status(summary)
    text = _notification_text(summary, actionable)
    event_id = hashlib.sha256(
        f"{summary.get('batch_id')}\0{actionable}\0{text}".encode("utf-8")
    ).hexdigest()
    path = Path(batch_dir) / "state" / "discord-notifications.json"
    ledger = (_read_json(path) if path.is_file() else
              {"schema": NOTIFICATIONS_SCHEMA, "events": {}})
    if ledger.get("schema") != NOTIFICATIONS_SCHEMA:
        raise DispatcherError("unsupported Discord notification ledger")
    existing = ledger.setdefault("events", {}).get(event_id)
    if existing:
        return {"status": existing.get("status", "UNCERTAIN"),
                "event_id": event_id, "sent": existing.get("status") == "SENT"}

    ledger["events"][event_id] = {
        "status": "PENDING", "created_at": _utc_now(), "actionable": actionable,
        "message_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    _atomic_write(path, ledger)  # intent is durable before external dispatch
    argv = [config["paths"]["openclaw"], "message", "send", "--channel", "discord",
            "--target", config["discord"]["target"], "--message", text, "--json"]
    try:
        output = command_runner(argv)
    except Exception as exc:
        ledger = _read_json(path)
        ledger["events"][event_id].update({
            "status": "UNCERTAIN", "finished_at": _utc_now(),
            "error_type": type(exc).__name__,
        })
        _atomic_write(path, ledger)
        return {"status": "UNCERTAIN", "event_id": event_id, "sent": False}

    ledger = _read_json(path)
    receipt = {"status": "SENT", "finished_at": _utc_now(),
               "result_sha256": hashlib.sha256(str(output).encode("utf-8")).hexdigest()}
    try:
        parsed = json.loads(output) if isinstance(output, str) else output
        if isinstance(parsed, dict):
            message_id = parsed.get("messageId") or parsed.get("message_id") or parsed.get("id")
            if message_id is not None:
                receipt["message_id"] = str(message_id)
    except (TypeError, ValueError):
        pass
    ledger["events"][event_id].update(receipt)
    _atomic_write(path, ledger)
    return {"status": "SENT", "event_id": event_id, "sent": True}


def _notify_intake_block(config: dict, summary: dict, *, command_runner: Callable) -> dict:
    """Persist pre-allocation intake alerts under dispatcher state."""
    stable_identity = json.dumps({
        "status": summary.get("status"), "reason": summary.get("reason"),
        "stable_sources": summary.get("stable_sources"),
        "max_fish_per_batch": summary.get("max_fish_per_batch"),
        "batch_ids": summary.get("batch_ids"),
        "source_set_sha256": summary.get("source_set_sha256"),
    }, sort_keys=True, separators=(",", ":"))
    token = hashlib.sha256(stable_identity.encode("utf-8")).hexdigest()[:16]
    event_dir = Path(config["paths"]["registry"]).parent / "bau-events" / token
    return notify_discord(config, event_dir, {
        "batch_id": f"intake-{token}", "stage": "INTAKE", "status": "BLOCKED",
        "published": 0, "quarantined": int(summary.get("stable_sources", 0)),
        "reason": summary.get("reason"),
    }, command_runner=command_runner)


def status_report(config: dict, *, now: Optional[float] = None,
                  scanner: Callable = betta_watch.scan) -> dict:
    blockers = validate_config(config, production=False)
    report = {"config_enabled": config.get("enabled") is True, "blockers": blockers}
    if blockers:
        return report
    try:
        policy = betta_policy.StandingPolicy.load(Path(config["paths"]["policy"]))
        persisted = _readonly_registry_hashes(Path(config["paths"]["registry"]))
        historical = historical_hashes(config)
        known = persisted | set(historical)
        stable = scan_candidates(config, now=now, known_hashes=known, scanner=scanner)
        owned, unmanaged = _owned_active_batches(config)
        report.update({
            "policy_enabled": policy.enabled(), "stable_new_sources": len(stable),
            "policy_paid_generation_authorised": policy.paid_generation_authorised(),
            "policy_automatic_batch_authorisation": (
                getattr(policy, "data", {}).get("automatic_batch_authorisation") is True
            ),
            "processed_hashes": len(persisted),
            "historical_hashes_available": len(historical),
            "owned_active_batches": [e["batch_id"] for e in owned],
            "unmanaged_active_batches": [e["batch_id"] for e in unmanaged],
            "resumable_owned_batches": [e["batch_id"] for e in owned if _resumable(e)],
            "live_generation_requested": config.get("live_generation") is True,
            "live_shopify_requested": config.get("live_shopify") is True,
        })
    except Exception as exc:
        report["blockers"].append(str(exc))
    return report


def smoke(config: dict, *, now: Optional[float] = None,
          scanner: Callable = betta_watch.scan) -> dict:
    """Read-only production preflight; never binds runners or dispatches work."""
    report = status_report(config, now=now, scanner=scanner)
    report["mode"] = "smoke"
    production_blockers = validate_config(config, production=True)
    report["blockers"] = sorted(set(report.get("blockers", []) + production_blockers))
    if config.get("enabled") is not True:
        report["blockers"].append("configuration is disabled")
    if report.get("policy_enabled") is not True:
        report["blockers"].append("standing policy is disabled")
    if (config.get("live_generation") is True
            and report.get("policy_paid_generation_authorised") is not True):
        report["blockers"].append("live generation is not authorised by policy")
    if (config.get("live_shopify") is True
            and report.get("policy_automatic_batch_authorisation") is not True):
        report["blockers"].append("automatic Shopify manifest authority is disabled")
    report["blockers"] = sorted(set(report["blockers"]))
    report.setdefault("historical_hashes_available", 0)
    report["ok"] = not report["blockers"]
    return report


def run_once(config: dict, *, deps: Optional[dict] = None) -> dict:
    deps = deps or {}
    blockers = validate_config(config, production=True)
    if blockers:
        raise DispatcherError("; ".join(blockers))
    if config.get("enabled") is not True:
        return {"status": "DISABLED", "reason": "configuration disabled"}
    if config.get("activation_hold") is True:
        return {"status": "ACTIVATION_HOLD", "reason": "non-mutating activation checks in progress"}
    policy = deps.get("policy") or betta_policy.StandingPolicy.load(
        Path(config["paths"]["policy"]))
    if not policy.enabled():
        return {"status": "DISABLED", "reason": "standing policy disabled"}

    with dispatcher_lock(Path(config["paths"]["dispatcher_lock"])):
        seeded = seed_processed_registry(config)
        owned, _unmanaged = _owned_active_batches(config)
        resumable = [entry for entry in owned if _resumable(entry)]
        nonresumable = [entry for entry in owned if not _resumable(entry)]
        if len(resumable) > 1:
            raise DispatcherError("multiple dispatcher-owned resumable batches; manual reconciliation required")
        if resumable:
            entry = resumable[0]
            _record_selected(Path(config["paths"]["registry"]), entry["batch_id"],
                             entry["sources"]["selected_sources"])
        elif nonresumable:
            # A terminal dispatcher batch left ACTIVE in the lifecycle registry
            # is not permission to reopen it or allocate around it.  The single
            # self-healing exception is a batch that provably performed no
            # Shopify mutation; it is resolved as a truthful terminal PARTIAL
            # (one batch per run) so the dispatcher cannot deadlock on it.
            reapable = []
            for candidate in sorted(nonresumable, key=lambda value: value["batch_id"]):
                try:
                    state = _read_json(Path(candidate["path"]) / "state" / "process.json")
                except (OSError, ValueError, DispatcherError):
                    state = None
                if _zero_mutation_terminal_state(state):
                    record = dict(candidate)
                    record["process"] = state
                    reapable.append(record)
            if reapable:
                return _reap_zero_mutation_batch(config, reapable[0], seeded, deps=deps)
            result = {"status": "BLOCKED", "reason": "owned terminal batch requires reconciliation",
                      "batch_ids": [e["batch_id"] for e in nonresumable], "seeded_hashes": seeded}
            result["notification"] = _notify_intake_block(
                config, result, command_runner=deps.get("command_runner", _default_command_runner))
            return result
        else:
            known = _readonly_registry_hashes(Path(config["paths"]["registry"]))
            candidates = scan_candidates(
                config, known_hashes=known,
                scanner=deps.get("scanner", betta_watch.scan), now=deps.get("now"),
            )
            maximum = int(policy.generation_budget().get("max_fish_per_batch", 0))
            if maximum <= 0:
                raise DispatcherError("policy max_fish_per_batch must be positive")
            if len(candidates) > maximum:
                # Reject the complete stable scan before allocation or any paid
                # call.  Splitting implicitly would change batch semantics.
                result = {"status": "BLOCKED", "reason": "stable intake exceeds batch limit",
                          "stable_sources": len(candidates), "max_fish_per_batch": maximum,
                          "source_set_sha256": hashlib.sha256("\n".join(
                              source["sha256"] for source in candidates
                          ).encode("ascii")).hexdigest(),
                          "seeded_hashes": seeded}
                result["notification"] = _notify_intake_block(
                    config, result,
                    command_runner=deps.get("command_runner", _default_command_runner))
                return result
            if not candidates:
                return {"status": "IDLE", "stable_sources": 0, "seeded_hashes": seeded}
            creator = deps.get("create_batch", betta_batches.create_batch)
            entry = creator(Path(config["paths"]["batches"]), label="BAU automatic intake")
            entry["sources"] = _persist_sources(entry, candidates)
            _record_selected(Path(config["paths"]["registry"]), entry["batch_id"], candidates)

        try:
            summary = _wire_and_process(config, policy, entry, deps=deps)
        except Exception as exc:
            summary = {"batch_id": entry["batch_id"], "stage": "DISPATCH",
                       "status": "BLOCKED", "published": 0, "quarantined": 0,
                       "error_type": type(exc).__name__}
            # Enrich the terminal summary from the durable process state without
            # altering it, so a failure report cannot understate what happened.
            try:
                process_state = _read_json(Path(entry["path"]) / "state" / "process.json")
                summary.update({
                    "stage": process_state.get("stage", "DISPATCH"),
                    "published": len(process_state.get("executed") or []),
                    "quarantined": sum(
                        1 for value in (process_state.get("fish") or {}).values()
                        if isinstance(value, dict)
                        and value.get("status") == "QUARANTINED"),
                })
            except (OSError, ValueError, DispatcherError):
                pass
            print(json.dumps({"dispatch_error": str(exc)[:500],
                              "error_type": type(exc).__name__,
                              "batch_id": entry["batch_id"]}, sort_keys=True),
                  file=sys.stderr)

        summary = _finalize_if_required(config, entry, summary, deps=deps)

        actionable = _actionable_status(summary)
        recoverable = summary.get("status") in {
            "RECONCILIATION_PENDING", "FINALIZATION_PENDING",
        }
        outcome = {"schema": OUTCOME_SCHEMA, "recorded_at": _utc_now(),
                   "actionable_status": actionable, "resumable": recoverable,
                   "summary": summary}
        _atomic_write(Path(entry["path"]) / "state" / "bau-outcome.json", outcome)
        if not recoverable:
            closer = deps.get("close_batch", betta_batches.close_batch)
            close_status = (betta_batches.COMPLETE if actionable == "COMPLETE"
                            else betta_batches.ABANDONED)
            closer(Path(config["paths"]["batches"]), entry["batch_id"], close_status)

        notification = notify_discord(
            config, Path(entry["path"]), summary,
            command_runner=deps.get("command_runner", _default_command_runner),
        )
        result = dict(summary)
        result.update({"actionable_status": actionable, "notification": notification,
                       "seeded_hashes": seeded})
        return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="NTA Betta BAU dispatcher")
    parser.add_argument("--config", required=True, type=Path)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--once", action="store_true")
    modes.add_argument("--smoke", action="store_true")
    modes.add_argument("--status", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.smoke:
            result = smoke(config)
        elif args.status:
            result = status_report(config)
        else:
            result = run_once(config)
        print(json.dumps(result, indent=2, sort_keys=True))
        notification = result.get("notification")
        notification_ok = (not isinstance(notification, dict)
                           or notification.get("status") == "SENT")
        successful = (result.get("status") not in {"BLOCKED", "FAILED", "PARTIAL"}
                      and result.get("actionable_status") != "BLOCKED"
                      and result.get("ok", True) and notification_ok)
        return 0 if successful else 2
    except (DispatcherError, OSError, ValueError, KeyError, sqlite3.Error) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
