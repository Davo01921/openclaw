#!/usr/bin/env python3
"""Unified, resumable Betta batch orchestrator (V2.2).

Coordinates the existing V2.1 components behind one ``process_batch`` entry point.
It never replaces the Grok generator and performs no external calls itself: every
external operation (intake, identification, generation, QA, Shopify resolve/execute/
verify, telemetry, archive) is supplied as an injected adapter. This keeps the
orchestration fully testable offline and lets the live runtime wire the same stages
to the real scripts/bridge.

Guarantees:

* one isolated workspace per batch (``betta_batches.py``);
* crash-safe, resumable state at ``<batch>/state/process.json``;
* idempotent: completed stages and successful per-fish work are never repeated, so a
  restart never repeats a paid generation or a Shopify mutation;
* per-fish quarantine instead of publishing uncertain fish;
* a standing authorisation gate bound to the exact manifest SHA-256.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

SYDNEY = ZoneInfo("Australia/Sydney")
STATE_SCHEMA = "nta-betta-process-v1"

STAGES = (
    "DETECTED", "ALLOCATED", "INTAKE_VERIFIED", "IDENTIFIED", "GENERATED",
    "QA_VERIFIED", "SHOPIFY_RESOLVED", "MANIFEST_READY", "AUTHORISED",
    "SHOPIFY_EXECUTING", "SHOPIFY_VERIFIED", "TELEMETRY_EXPORTED", "ARCHIVING",
    "ARCHIVED", "COMPLETE",
)
STAGE_INDEX = {name: index for index, name in enumerate(STAGES)}

FISH_PASS = "VERIFIED"
FISH_PASS_EXCEPTION = "PASS_WITH_ACCEPTED_EXCEPTION"
FISH_QUARANTINED = "QUARANTINED"
FISH_FAILED = "FAILED"


class ProcessError(ValueError):
    pass


def now_sydney() -> str:
    return datetime.now(SYDNEY).isoformat()


def _atomic_write(path: Path, data: dict) -> None:
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


class _Lock:
    def __init__(self, path: Path, timeout: float = 15.0, poll: float = 0.02):
        self.path = Path(path)
        self.timeout = timeout
        self.poll = poll
        self._fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a+")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    self._fh.close()
                    raise ProcessError("timed out acquiring process state lock")
                time.sleep(self.poll)

    def __exit__(self, *exc):
        if self._fh is not None:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            self._fh.close()
        return False


class ProcessState:
    """Crash-safe, advisory-locked state for one batch."""

    def __init__(self, batch_dir: Path, batch_id: str):
        self.batch_dir = Path(batch_dir)
        self.batch_id = batch_id
        self.path = self.batch_dir / "state" / "process.json"

    def load(self) -> dict:
        if self.path.is_file():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {"schema": STATE_SCHEMA, "batch_id": self.batch_id, "stage": "ALLOCATED",
                "status": "ACTIVE", "fish": {}, "manifest_sha256": None,
                "generated": [], "executed": [], "log": []}

    def update(self, mutate: Callable[[dict], None]) -> dict:
        with _Lock(self.path.with_suffix(".json.lock")):
            data = self.load()
            mutate(data)
            _atomic_write(self.path, data)
            return data


def _reach(state: dict, stage: str) -> None:
    if state["stage"] != stage:
        state["stage"] = stage
        state["log"].append({"at": now_sydney(), "stage": stage})


class BatchProcessor:
    def __init__(self, batch_dir: Path, batch_id: str, *, adapters: dict,
                 policy, clock=now_sydney):
        self.state = ProcessState(batch_dir, batch_id)
        self.adapters = adapters
        self.policy = policy
        self.clock = clock
        self.batch_dir = Path(batch_dir)

    # -- helpers ----------------------------------------------------------- #
    def _stage_done(self, data: dict, stage: str) -> bool:
        return STAGE_INDEX[data["stage"]] >= STAGE_INDEX[stage]

    def _call(self, name: str, **kwargs):
        adapter = self.adapters.get(name)
        if adapter is None:
            raise ProcessError(f"missing adapter: {name}")
        return adapter(**kwargs)

    # -- pipeline ---------------------------------------------------------- #
    def run(self) -> dict:
        data = self.state.load()
        if not self._stage_done(data, "INTAKE_VERIFIED"):
            detection = self._call("intake", batch_dir=self.batch_dir, state=data)
            self.state.update(lambda d: (d.setdefault("intake", detection), _reach(d, "INTAKE_VERIFIED")))
        detection = self.state.load().get("intake", {})

        # Identification (deterministic label resolution; no paid calls yet).
        data = self.state.load()
        if not self._stage_done(data, "IDENTIFIED"):
            def identify(d: dict) -> None:
                fish = {}
                for index, record in enumerate(detection.get("fish", [])):
                    decision = self._call("identify", record=record, batch_dir=self.batch_dir)
                    key = record.get("path") or f"fish-{index}"
                    entry = {
                        "source_path": record.get("path"),
                        "source_sha256": record.get("sha256"),
                        "tank_id": decision.get("tank_id"),
                        "photo_date": decision.get("photo_date"),
                        "status": "PENDING",
                        "notes": [],
                    }
                    if not decision.get("tank_id") or decision.get("uncertain") is not False:
                        entry["status"] = FISH_QUARANTINED
                        entry["notes"].append("identification uncertain")
                    fish[key] = entry
                # duplicate tank ids quarantine every clashing fish
                seen = {}
                for key, entry in fish.items():
                    tank = entry.get("tank_id")
                    if not tank:
                        continue
                    if tank in seen:
                        entry["status"] = FISH_QUARANTINED
                        entry["notes"].append("duplicate tank id")
                        fish[seen[tank]]["status"] = FISH_QUARANTINED
                        fish[seen[tank]]["notes"].append("duplicate tank id")
                    else:
                        seen[tank] = key
                d["fish"] = fish
                _reach(d, "IDENTIFIED")
            self.state.update(identify)

        # Paid generation, gated by the standing policy.
        data = self.state.load()
        eligible = {k: v for k, v in data["fish"].items() if v["status"] == "PENDING"}
        if eligible and not self.policy.paid_generation_authorised():
            return self._finish(data, "AWAITING_AUTHORISATION")
        if not self._stage_done(data, "GENERATED"):
            def generate(d: dict) -> None:
                for key, entry in d["fish"].items():
                    if entry["status"] != "PENDING":
                        continue
                    if key in d.get("generated", []):
                        continue  # idempotent: never regenerate an existing hero
                    try:
                        hero = self._call("generate", entry=entry, batch_dir=self.batch_dir)
                        entry["hero_path"] = hero.get("hero_path")
                        entry["hero_sha256"] = hero.get("hero_sha256")
                        self._call("finish", entry=entry, batch_dir=self.batch_dir)
                        d.setdefault("generated", []).append(key)
                    except Exception as exc:
                        # budget exceeded / interrupted / generator failure: quarantine, continue.
                        entry["status"] = FISH_QUARANTINED
                        entry["notes"].append(f"generation failed: {exc}")
                _reach(d, "GENERATED")
            self.state.update(generate)

        # Independent QA with quarantine (never auto-accept material discrepancies).
        data = self.state.load()
        if not self._stage_done(data, "QA_VERIFIED"):
            def qa(d: dict) -> None:
                for entry in d["fish"].values():
                    if entry["status"] != "PENDING":
                        continue
                    result = self._call("qa", entry=entry, batch_dir=self.batch_dir)
                    if result.get("outcome") == "PASS":
                        entry["status"] = FISH_PASS
                    elif result.get("accepted_exception"):
                        entry["status"] = FISH_PASS_EXCEPTION
                        entry["accepted_exception"] = result["accepted_exception"]
                    else:
                        entry["status"] = FISH_QUARANTINED
                        entry["notes"].append("qa failed: " + ",".join(result.get("failed_assertions", [])))
                _reach(d, "QA_VERIFIED")
            self.state.update(qa)

        # Shopify resolution (exact unique product required).
        data = self.state.load()
        if not self._stage_done(data, "SHOPIFY_RESOLVED"):
            def resolve(d: dict) -> None:
                for entry in d["fish"].values():
                    if entry["status"] not in (FISH_PASS, FISH_PASS_EXCEPTION):
                        continue
                    resolved = self._call("resolve", entry=entry, batch_dir=self.batch_dir)
                    if resolved.get("status") != "RESOLVED":
                        entry["status"] = FISH_QUARANTINED
                        entry["notes"].append("shopify resolution not unique")
                    else:
                        entry["product"] = resolved["product"]
                _reach(d, "SHOPIFY_RESOLVED")
            self.state.update(resolve)

        # Immutable manifest + standing authorisation bound to its hash.
        data = self.state.load()
        if not self._stage_done(data, "MANIFEST_READY"):
            def manifest(d: dict) -> None:
                built = self._call("build_manifest", state=d, batch_dir=self.batch_dir)
                d["manifest"] = built["manifest"]
                d["manifest_sha256"] = built["manifest_sha256"]
                _reach(d, "MANIFEST_READY")
            self.state.update(manifest)

        data = self.state.load()
        receipt = self.policy.authorise(data.get("manifest_sha256"))
        if receipt is None:
            return self._finish(data, "AWAITING_AUTHORISATION")
        self.state.update(lambda d: d.update({"authorisation": receipt}) or _reach(d, "AUTHORISED"))

        # Execute (idempotent per fish) then independently verify.
        data = self.state.load()
        if not self._stage_done(data, "SHOPIFY_VERIFIED"):
            def execute(d: dict) -> None:
                _reach(d, "SHOPIFY_EXECUTING")
                for key, entry in d["fish"].items():
                    if entry["status"] not in (FISH_PASS, FISH_PASS_EXCEPTION):
                        continue
                    if key in d.get("executed", []):
                        continue  # idempotent: never repeat a Shopify mutation
                    outcome = self._call("execute", entry=entry, state=d, batch_dir=self.batch_dir)
                    if outcome.get("status") == "VERIFIED":
                        entry["shopify_receipt"] = outcome.get("receipt")
                        d.setdefault("executed", []).append(key)
                    elif outcome.get("status") == "AWAITING_LIVE":
                        # Dry-run: pause without quarantine and without claiming success.
                        d["awaiting_live"] = True
                        break
                    else:
                        entry["status"] = FISH_QUARANTINED
                        entry["notes"].append("shopify execute not verified")
                if not d.get("awaiting_live"):
                    _reach(d, "SHOPIFY_VERIFIED")
            self.state.update(execute)

        data = self.state.load()
        if data.get("awaiting_live"):
            return self._finish(data, "AWAITING_LIVE")
        if not self._stage_done(data, "TELEMETRY_EXPORTED"):
            self.state.update(lambda d: (self._call("telemetry", state=d, batch_dir=self.batch_dir),
                                         _reach(d, "TELEMETRY_EXPORTED")))

        data = self.state.load()
        if not self._stage_done(data, "ARCHIVED"):
            def archive(d: dict) -> None:
                _reach(d, "ARCHIVING")
                self._call("archive", state=d, batch_dir=self.batch_dir)
                _reach(d, "ARCHIVED")
            self.state.update(archive)

        data = self.state.load()
        return self._finish(data, "COMPLETE" if self._all_published(data) else "PARTIAL")

    def _all_published(self, data: dict) -> bool:
        published = [e for e in data["fish"].values() if e["status"] in (FISH_PASS, FISH_PASS_EXCEPTION)]
        quarantined = [e for e in data["fish"].values() if e["status"] == FISH_QUARANTINED]
        return bool(published) and not quarantined and all(
            key in data.get("executed", []) for key in data["fish"]
            if data["fish"][key]["status"] in (FISH_PASS, FISH_PASS_EXCEPTION))

    def _finish(self, data: dict, status: str) -> dict:
        final = self.state.update(lambda d: d.update({"status": status}))
        summary = {
            "batch_id": self.state.batch_id,
            "stage": final["stage"],
            "status": status,
            "published": sum(1 for e in final["fish"].values() if e["status"] in (FISH_PASS, FISH_PASS_EXCEPTION)),
            "quarantined": sum(1 for e in final["fish"].values() if e["status"] == FISH_QUARANTINED),
            "manifest_sha256": final.get("manifest_sha256"),
        }
        return summary


def process_batch(batch_dir: Path, batch_id: str, *, adapters: dict, policy,
                  clock=now_sydney) -> dict:
    return BatchProcessor(batch_dir, batch_id, adapters=adapters, policy=policy, clock=clock).run()


def main() -> int:
    parser = argparse.ArgumentParser(description="Unified Betta batch orchestrator (adapter-driven)")
    parser.add_argument("batch_dir", type=Path)
    parser.add_argument("batch_id")
    args = parser.parse_args()
    # The live adapter wiring is provided by the runtime integration; the CLI refuses
    # to run without it rather than guess.
    print("ERROR: betta_process requires wired adapters; use process_batch() from the runtime",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
