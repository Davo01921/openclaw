#!/usr/bin/env python3
"""Real, batch-scoped adapters wiring betta_process to existing V2.1 components.

Reuses the existing engines (grok_hero, betta_finish_heroes, render_betta_label,
vision_review, betta_shopify_batch, betta_archive, betta_telemetry). It does not
reimplement generation, the Shopify uploader or the archive.

Every external step is executed through an injectable runner so the wiring is
testable offline. Live Shopify writes and paid generation are refused unless
explicitly enabled for a supervised run. All paths are batch-scoped. Telemetry is
recorded as each call occurs; if it cannot be recorded the stage fails closed.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import betta_archive as archive_mod  # noqa: E402
import betta_telemetry as telemetry_mod  # noqa: E402
import betta_watch as watch_mod  # noqa: E402
import label_identity as label_mod  # noqa: E402

SYDNEY = ZoneInfo("Australia/Sydney")


class AdapterError(RuntimeError):
    pass


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _subprocess_runner(argv, *, timeout=240):
    result = subprocess.run([str(a) for a in argv], capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise AdapterError(f"command failed ({result.returncode}): {result.stderr[-400:]}")
    return result.stdout


class Adapters:
    """One bundle of batch-scoped stage adapters."""

    def __init__(self, *, batch_id: str, batch_dir: Path, intake_dir: Path,
                 telemetry_db: Path, policy, live_shopify: bool = False,
                 live_generation: bool = False, owner_exceptions: Optional[dict] = None,
                 runners: Optional[dict] = None, processed_registry: Optional[Path] = None,
                 budget=None):
        self.batch_id = batch_id
        self.batch_dir = Path(batch_dir)
        self.intake_dir = Path(intake_dir)
        self.telemetry_db = Path(telemetry_db)
        self.policy = policy
        self.live_shopify = live_shopify
        self.live_generation = live_generation
        self.owner_exceptions = owner_exceptions or {}
        self.runners = runners or {}
        self.registry = watch_mod.ProcessedRegistry(processed_registry) if processed_registry else None
        self.budget = budget

    # -- telemetry (fail closed) ------------------------------------------- #
    def _record(self, stage: str, outcome: str, *, tank: Optional[str] = None,
                started: Optional[float] = None, provider=None, model=None,
                tokens_input=None, tokens_output=None, cost=None, cost_source=None,
                error=None, detail=None) -> None:
        entry = {
            "batch_id": self.batch_id, "tank_number": tank, "stage": stage,
            "provider": provider, "model": model, "attempt": 1,
            "timestamp": iso_now(),
            "duration_seconds": (time.monotonic() - started) if started else None,
            "outcome": outcome, "tokens_input": tokens_input, "tokens_output": tokens_output,
            "cost": cost, "cost_source": cost_source, "error": error,
            "detail_json": json.dumps(detail, sort_keys=True) if detail is not None else None,
        }
        try:
            con = telemetry_mod.connect(self.telemetry_db)
            try:
                telemetry_mod.record_call(con, entry)
            finally:
                con.close()
        except Exception as exc:  # fail closed: do not proceed on unrecordable telemetry
            raise AdapterError(f"telemetry unavailable: {exc}") from exc

    def _run(self, name: str, argv: list, *, stage: str, tank: Optional[str] = None):
        started = time.monotonic()
        runner = self.runners.get(name) or _subprocess_runner
        try:
            output = runner(argv)
        except Exception as exc:
            self._record(stage, "ERROR", tank=tank, started=started, error=str(exc))
            raise
        self._record(stage, "OK", tank=tank, started=started)
        return output

    # -- intake ------------------------------------------------------------ #
    def intake(self, batch_dir, state):
        batch_dir = Path(batch_dir)
        dest_dir = batch_dir / "intake"
        dest_dir.mkdir(parents=True, exist_ok=True)
        known = self.registry.hashes() if self.registry else set()
        for existing in sorted(dest_dir.glob("*")):
            if existing.is_file():
                known.add(sha256_file(existing))
        stable = watch_mod.scan(self.intake_dir, now=time.time(),
                                settle_seconds=self.runners.get("settle_seconds", 20.0),
                                known_hashes=known)
        fish = []
        for candidate in stable:
            source = Path(candidate["path"])
            dest = dest_dir / source.name
            if not dest.exists():
                shutil.copy2(source, dest)  # copy; never move/delete the original
            digest = sha256_file(dest)
            if self.registry:
                self.registry.record(digest, self.batch_id)
            self._record("intake", "OK", tank=source.stem, detail={"sha256": digest})
            fish.append({"path": str(dest), "sha256": digest})
        # resume: include any files already in the batch intake dir
        if not fish:
            for existing in sorted(dest_dir.glob("*")):
                if existing.is_file():
                    fish.append({"path": str(existing), "sha256": sha256_file(existing)})
        return {"fish": fish}

    # -- identification ---------------------------------------------------- #
    def identify(self, record, batch_dir):
        files = [Path(record["path"])]
        runner = self.runners.get("catalogue")
        started = time.monotonic()
        if runner is None:
            evidence = json.loads(_subprocess_runner(
                [sys.executable, str(_SCRIPT_DIR / "vision_review.py"), "--mode", "catalogue",
                 "--file", str(files[0])]))
        else:
            evidence = runner(files)
        output = evidence.get("output") or evidence
        tank = output.get("tank_id")
        date = output.get("photo_date")
        uncertain = False
        try:
            tank = label_mod.normalize_tank(tank) if tank else None
            if date is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(date)):
                date = label_mod.normalize_date(date)
        except ValueError:
            uncertain = True
        if not tank or not date:
            uncertain = True
        self._record("identify", "OK" if not uncertain else "UNCERTAIN",
                     tank=tank, started=started, provider=evidence.get("provider"),
                     model=evidence.get("model"))
        return {"tank_id": tank, "photo_date": date, "uncertain": uncertain}

    # -- generation / finishing ------------------------------------------- #
    def generate(self, entry, batch_dir):
        if not self.live_generation and "generate" not in self.runners:
            raise AdapterError("paid generation not authorised for this run")
        hero_dir = Path(batch_dir) / "evidence" / "heroes"
        hero_dir.mkdir(parents=True, exist_ok=True)
        clean = hero_dir / f"{entry['tank_id']}-clean.png"
        if clean.is_file():
            return {"hero_path": str(clean), "hero_sha256": sha256_file(clean)}  # idempotent
        tank = entry["tank_id"]
        source = entry["source_path"]
        runner = self.runners.get("generate") or _subprocess_runner
        if self.budget is not None:
            self.budget.register_fish(tank)
        max_attempts = self.budget.limits["max_attempts_per_fish"] if self.budget else 1
        last_error = None
        for _ in range(max_attempts):
            if self.budget is not None:
                ok, reason = self.budget.can_attempt(tank)
                if not ok:
                    raise AdapterError(f"generation blocked: {reason}")
                reservation = self.budget.reserve(tank)  # conservative fallback cost
            started = time.monotonic()
            try:
                output = runner([sys.executable, str(_SCRIPT_DIR / "grok_hero.py"),
                                 "--source", source, "--output", str(clean)])
            except Exception as exc:  # charge the attempt conservatively, then retry
                if self.budget is not None:
                    self.budget.settle(reservation, None, reported=False)
                self._record("generate", "ERROR", tank=tank, started=started, error=str(exc))
                last_error = exc
                continue
            cost, source_label = self._parse_grok_cost(output)
            if not clean.is_file():
                if self.budget is not None:
                    self.budget.settle(reservation, None, reported=False)
                self._record("generate", "ERROR", tank=tank, started=started, error="no output file")
                last_error = AdapterError("generator produced no hero")
                continue
            if self.budget is not None:
                self.budget.settle(reservation, cost, reported=cost is not None)
            self._record("generate", "OK", tank=tank, started=started, cost=cost, cost_source=source_label)
            return {"hero_path": str(clean), "hero_sha256": sha256_file(clean)}
        raise AdapterError(f"generation failed within budget for {tank}: {last_error}")

    @staticmethod
    def _parse_grok_cost(output) -> tuple:
        try:
            record = json.loads(output) if isinstance(output, str) and output.strip().startswith("{") else {}
        except (ValueError, TypeError):
            record = {}
        cost = record.get("grokai_cost") if isinstance(record, dict) else None
        return (float(cost) if isinstance(cost, (int, float)) else None,
                (record.get("grokai_cost_source") if isinstance(record, dict) else None) or "unavailable")

    def finish(self, entry, batch_dir):
        runner = self.runners.get("render")
        clean = entry.get("hero_path")
        final = Path(batch_dir) / "evidence" / "heroes" / f"{entry['tank_id']}.png"
        if runner is not None:
            runner(clean, final, entry["tank_id"], entry["photo_date"])
        else:
            render = getattr(__import__("render_betta_label"), "render")
            render(Path(clean), final, entry["tank_id"], entry["photo_date"])
        entry["hero_path"] = str(final)
        entry["hero_sha256"] = sha256_file(final)
        # record any Grok cost reported by the generator sidecar if present
        self._record("finish", "OK", tank=entry["tank_id"])

    # -- QA ---------------------------------------------------------------- #
    def qa(self, entry, batch_dir):
        source = Path(entry["source_path"])
        hero = Path(entry["hero_path"])
        runner = self.runners.get("qa")
        started = time.monotonic()
        if runner is None:
            evidence = json.loads(_subprocess_runner(
                [sys.executable, str(_SCRIPT_DIR / "vision_review.py"), "--mode", "qa",
                 "--file", str(source), "--file", str(hero), "--file", str(source)]))
        else:
            evidence = runner(entry)
        assertions = evidence.get("assertions") or (evidence.get("output") or {}).get("assertions", {})
        failed = sorted(k for k, v in assertions.items() if v == "FAIL")
        outcome = "PASS" if not failed and evidence.get("overall", "PASS") == "PASS" else "FAIL"
        accepted = None
        if outcome == "FAIL" and entry["tank_id"] in self.owner_exceptions:
            accepted = self.owner_exceptions[entry["tank_id"]]
        self._record("qa", outcome, tank=entry["tank_id"], started=started,
                     provider=evidence.get("provider"), model=evidence.get("model"))
        return {"outcome": outcome, "failed_assertions": failed, "accepted_exception": accepted}

    # -- Shopify ----------------------------------------------------------- #
    def resolve(self, entry, batch_dir):
        runner = self.runners.get("resolve")
        if runner is None:
            raise AdapterError("Shopify resolve requires the live bridge runner")
        resolved = runner(entry)
        if resolved.get("status") != "RESOLVED":
            return {"status": resolved.get("status", "AMBIGUOUS")}
        entry["product"] = resolved["product"]
        return {"status": "RESOLVED", "product": resolved["product"]}

    def build_manifest(self, state, batch_dir):
        items = [entry for entry in state["fish"].values()
                 if entry["status"] in ("VERIFIED", "PASS_WITH_ACCEPTED_EXCEPTION")]
        manifest = {"schema": "nta-betta-shopify-batch-v1", "batch_id": self.batch_id,
                    "shopify_write_authorised": bool(self.live_shopify), "items": items}
        payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        return {"manifest": manifest, "manifest_sha256": hashlib.sha256(payload).hexdigest()}

    def execute(self, entry, state, batch_dir):
        manifest_path = Path(batch_dir) / "manifest" / "shopify-production.json"
        if not manifest_path.is_file():
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(state["manifest"], indent=2), encoding="utf-8")
        if not self.live_shopify:
            return {"status": "AWAITING_LIVE"}  # dry-run: never writes, never claims success
        runner = self.runners.get("execute")
        if runner is None:
            raise AdapterError("live Shopify execute requires the uploader runner")
        result = runner(entry, manifest_path, state.get("manifest_sha256"))
        return result

    def telemetry(self, state, batch_dir):
        csv_path = Path(batch_dir) / "reports" / "betta-call-telemetry.csv"
        con = telemetry_mod.connect(self.telemetry_db)
        try:
            telemetry_mod.export_calls(con, self.batch_id, csv_path)
            summary = telemetry_mod.batch_call_summary(con, self.batch_id)
        finally:
            con.close()
        return summary

    def archive(self, state, batch_dir):
        runner = self.runners.get("archive")
        if runner is None:
            raise AdapterError("archive requires the archive runner")
        return runner(state, batch_dir)


def make_adapters(**kwargs) -> dict:
    bundle = Adapters(**kwargs)
    return {name: getattr(bundle, name) for name in
            ("intake", "identify", "generate", "finish", "qa", "resolve",
             "build_manifest", "execute", "telemetry", "archive")}
