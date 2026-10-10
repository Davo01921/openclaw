#!/usr/bin/env python3
"""Bind the existing Shopify bridge/uploader to the V2.2 orchestrator.

Provides the concrete runners the adapters expect, reusing existing components:

* ``shopify_resolve`` — read-only ``node scripts/shopify_live.mjs resolve <tank>``;
* ``shopify_execute`` — the existing ``scripts/betta_shopify_batch.py`` (dry-run
  unless ``live=True`` and an approved manifest SHA-256 are supplied);
* ``archive`` — the existing ``scripts/betta_archive.py``.

Live Shopify mutations are impossible unless ``live=True`` is explicitly passed,
and the uploader itself still requires ``--live`` plus an exact manifest digest.
No credential value is read, printed or stored here.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
SHOPIFY_LIVE = _SCRIPT_DIR / "shopify_live.mjs"
UPLOADER = _SCRIPT_DIR / "betta_shopify_batch.py"
ARCHIVER = _SCRIPT_DIR / "betta_archive.py"


class BindingError(RuntimeError):
    pass


def _run(argv: list, *, runner: Optional[Callable] = None, timeout: int = 180) -> str:
    if runner is not None:
        return runner(argv)
    result = subprocess.run([str(a) for a in argv], capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise BindingError(f"command failed ({result.returncode}): {result.stderr[-400:]}")
    return result.stdout


def shopify_resolve_runner(*, node: str = "node", runner: Optional[Callable] = None) -> Callable:
    def resolve(entry: dict) -> dict:
        tank = entry.get("tank_id")
        if not tank:
            return {"status": "AMBIGUOUS"}
        out = _run([node, str(SHOPIFY_LIVE), "resolve", tank], runner=runner)
        data = json.loads(out)
        if not data.get("ok") or data.get("status") != "RESOLVED":
            return {"status": "AMBIGUOUS"}
        snapshot = data["snapshot"]
        return {"status": "RESOLVED", "product": {
            "id": snapshot["id"], "variant_id": snapshot["variant_id"],
            "location_id": snapshot["location_id"],
            "inventory_item_id": snapshot.get("inventory_item_id"),
            "source": snapshot.get("source", "FRESH_SHOPIFY_READ"),
            "tank_id": snapshot.get("tank_id", tank),
            "before": snapshot.get("before", {}),
        }}
    return resolve


def shopify_execute_runner(*, live: bool = False, confirm_manifest_sha256: Optional[str] = None,
                           runner: Optional[Callable] = None) -> Callable:
    """Return an execute runner. Without live + digest it never writes."""
    def execute(entry: dict, manifest_path: Path, manifest_sha256: Optional[str]) -> dict:
        if not live:
            return {"status": "AWAITING_LIVE"}
        if not confirm_manifest_sha256 or confirm_manifest_sha256 != manifest_sha256:
            raise BindingError("live execute requires --confirm-manifest-sha256 equal to the manifest digest")
        argv = [sys.executable, str(UPLOADER), "execute", "--manifest", str(manifest_path),
                "--live", "--confirm-manifest-sha256", str(confirm_manifest_sha256),
                "--tank", entry["tank_id"]]
        out = _run(argv, runner=runner)
        report = json.loads(out) if out.strip().startswith("{") else {}
        status = "VERIFIED" if report.get("status") == "VERIFIED" else "FAILED"
        return {"status": status, "receipt": report.get("receipt")}
    return execute


def archive_runner(*, archive_root: Path, date: Optional[str] = None,
                   exceptions_path: Optional[Path] = None, live: bool = False,
                   runner: Optional[Callable] = None) -> Callable:
    def archive(state: dict, batch_dir: Path) -> dict:
        batch_dir = Path(batch_dir)
        manifest = batch_dir / "manifest" / "shopify-production.json"
        verify_dir = batch_dir / "reports" / "shopify-production"
        argv = [sys.executable, str(ARCHIVER), "execute", "--manifest", str(manifest),
                "--archive-root", str(archive_root), "--date", date or "", "--batch",
                str(state.get("batch_id", ""))]
        if exceptions_path:
            argv += ["--exceptions", str(exceptions_path)]
        if live:
            argv += ["--apply"]
        # Verify reports are discovered by the archive planner from the batch reports.
        _run(argv, runner=runner)
        return {"status": "ARCHIVED" if live else "AWAITING_LIVE"}
    return archive


def bind_runners(*, archive_root: Path, resolve_runner: Optional[Callable] = None,
                 execute_runner: Optional[Callable] = None, archive: Optional[Callable] = None,
                 node: str = "node") -> dict:
    return {
        "resolve": resolve_runner or shopify_resolve_runner(node=node),
        "execute": execute_runner or shopify_execute_runner(live=False),
        "archive": archive or archive_runner(archive_root=archive_root),
    }
