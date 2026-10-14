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
FISH_RECONCILIATION_PENDING = "RECONCILIATION_PENDING"


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

    @staticmethod
    def _is_reconciliation_pending(exc: Exception) -> bool:
        return getattr(exc, "reconciliation_pending", False) is True

    @staticmethod
    def _mark_pending(entry: dict, kind: str, reason: str) -> None:
        entry.setdefault("pending_from_status", entry.get("status", "PENDING"))
        entry["status"] = FISH_RECONCILIATION_PENDING
        entry["pending_kind"] = kind
        entry["pending_reason"] = reason
        note = f"{kind} reconciliation pending: {reason}"
        if note not in entry.setdefault("notes", []):
            entry["notes"].append(note)

    @staticmethod
    def _clear_pending(entry: dict, default: str) -> None:
        previous = entry.pop("pending_from_status", None)
        entry.pop("pending_kind", None)
        entry.pop("pending_reason", None)
        entry["status"] = previous if previous not in (None, FISH_RECONCILIATION_PENDING) else default

    @staticmethod
    def _shopify_candidates(data: dict) -> list[dict]:
        return [entry for entry in data.get("fish", {}).values()
                if entry.get("status") in (FISH_PASS, FISH_PASS_EXCEPTION)
                or (entry.get("status") == FISH_RECONCILIATION_PENDING
                    and entry.get("pending_kind") == "shopify")]

    # -- pipeline ---------------------------------------------------------- #
    def run(self) -> dict:
        data = self.state.load()
        if data.get("status") in ("COMPLETE", "PARTIAL"):
            return self._summary(data)
        automatic = getattr(self.policy, "data", {}).get("automatic_batch_authorisation") is True
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
                    try:
                        decision = self._call("identify", record=record, batch_dir=self.batch_dir)
                    except Exception as exc:
                        decision = {"uncertain": True, "error": str(exc)}
                    key = record.get("path") or f"fish-{index}"
                    entry = {
                        "source_path": record.get("path"),
                        "source_sha256": record.get("sha256"),
                        "tank_id": decision.get("tank_id"),
                        "photo_date": decision.get("photo_date"),
                        "status": "PENDING",
                        "notes": [],
                    }
                    for field in ("catalogue", "catalogue_path", "catalogue_sha256", "approved_title", "title",
                                  "catalogue_evidence_path", "catalogue_evidence_sha256",
                                  "fish_name", "tail_type", "sex", "date_entered", "source_reference"):
                        if field in decision:
                            entry[field] = decision[field]
                    entry.setdefault("date_entered", detection.get("date_entered") or self.clock())
                    if not decision.get("tank_id") or decision.get("uncertain") is not False:
                        entry["status"] = FISH_QUARANTINED
                        if decision.get("error"):
                            entry["notes"].append("identification failed")
                            entry["identify_error"] = str(decision["error"])[:400]
                        else:
                            entry["notes"].append("identification uncertain")
                            if decision.get("uncertain_reason"):
                                entry["identify_reason"] = str(decision["uncertain_reason"])[:300]
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

        # One focused top-label crop retry for otherwise uncertain identifications
        # before any paid generation or eligibility work.
        data = self.state.load()
        retryable = [entry for entry in data["fish"].values()
                     if entry.get("status") == FISH_QUARANTINED
                     and isinstance(entry.get("notes"), list) and len(entry["notes"]) == 1
                     and entry["notes"][0] in ("identification uncertain",
                                               "identification failed")]
        if (retryable and not data.get("identification_retry_complete")
                and self.adapters.get("retry_identify") is not None):
            def retry_identification(d: dict) -> None:
                for entry in d["fish"].values():
                    notes = entry.get("notes")
                    if not (entry.get("status") == FISH_QUARANTINED
                            and isinstance(notes, list) and len(notes) == 1
                            and notes[0] in ("identification uncertain",
                                             "identification failed")):
                        continue
                    try:
                        decision = self._call("retry_identify", entry=entry,
                                              batch_dir=self.batch_dir)
                    except Exception as exc:
                        entry["notes"] = ["focused label retry failed"]
                        entry["identify_error"] = str(exc)[:400]
                        continue
                    if decision.get("uncertain") is False and decision.get("tank_id"):
                        entry.update({
                            "tank_id": decision["tank_id"],
                            "photo_date": decision["photo_date"],
                            "title": decision.get("proposed_title"),
                            "proposed_title": decision.get("proposed_title"),
                            "catalogue_evidence_path": decision.get("catalogue_evidence_path"),
                            "catalogue_evidence_sha256": decision.get("catalogue_evidence_sha256"),
                            "status": "PENDING",
                            "notes": ["focused label retry accepted"],
                        })
                    else:
                        entry["notes"] = ["focused label retry uncertain"]
                # re-check duplicate tank ids among the pending fish
                seen = {}
                for key, entry in d["fish"].items():
                    if entry.get("status") != "PENDING":
                        continue
                    tank = entry.get("tank_id")
                    if tank in seen:
                        entry["status"] = FISH_QUARANTINED
                        entry["notes"].append("duplicate tank id")
                        other = d["fish"][seen[tank]]
                        other["status"] = FISH_QUARANTINED
                        other["notes"].append("duplicate tank id")
                    else:
                        seen[tank] = key
                d["identification_retry_complete"] = True
            self.state.update(retry_identification)

        # Automatic (BAU) runs perform one read-only Shopify resolution and
        # standing-baseline check before any paid generation.  A fish that could
        # not be written under the standing scope (for example a product whose
        # inventory is not 0) is quarantined with its reason instead of spending
        # generation budget.  Supervised runs without the adapter are unchanged.
        data = self.state.load()
        if (automatic and self.adapters.get("eligibility") is not None
                and not self._stage_done(data, "GENERATED")):
            def eligibility(d: dict) -> None:
                for entry in d["fish"].values():
                    if entry.get("status") != "PENDING" or entry.get("product"):
                        continue
                    try:
                        verdict = self._call("eligibility", entry=entry, state=d,
                                             batch_dir=self.batch_dir)
                    except Exception as exc:
                        verdict = {"eligible": False,
                                   "reason": f"pre-generation eligibility check failed: {exc}"}
                    if isinstance(verdict, dict) and verdict.get("eligible") is True:
                        if isinstance(verdict.get("product"), dict):
                            entry["product"] = verdict["product"]
                        continue
                    entry["status"] = FISH_QUARANTINED
                    reason = (verdict or {}).get("reason") or "not eligible for automatic writes"
                    entry.setdefault("notes", []).append(f"pre-generation ineligible: {reason}")
            self.state.update(eligibility)

        # Paid generation, gated by the standing policy.
        data = self.state.load()
        eligible = {k: v for k, v in data["fish"].items()
                    if v["status"] == "PENDING"
                    or (v["status"] == FISH_RECONCILIATION_PENDING
                        and v.get("pending_kind") == "generation")}
        if eligible and not self.policy.paid_generation_authorised():
            return self._finish(data, "AWAITING_AUTHORISATION")
        if not self._stage_done(data, "GENERATED"):
            def generate(d: dict) -> None:
                for key, entry in d["fish"].items():
                    is_recovery = (entry["status"] == FISH_RECONCILIATION_PENDING
                                   and entry.get("pending_kind") == "generation")
                    if entry["status"] != "PENDING" and not is_recovery:
                        continue
                    if key in d.get("generated", []):
                        continue  # idempotent: never regenerate an existing hero
                    try:
                        hero = self._call("generate", entry=entry, batch_dir=self.batch_dir)
                        entry["hero_path"] = hero.get("hero_path")
                        entry["hero_sha256"] = hero.get("hero_sha256")
                        self._call("finish", entry=entry, batch_dir=self.batch_dir)
                        d.setdefault("generated", []).append(key)
                        if is_recovery:
                            self._clear_pending(entry, "PENDING")
                    except Exception as exc:
                        if self._is_reconciliation_pending(exc):
                            self._mark_pending(entry, "generation", str(exc))
                            break
                        entry["status"] = FISH_QUARANTINED
                        entry["notes"].append(f"generation failed: {exc}")
                if not any(e.get("status") == FISH_RECONCILIATION_PENDING
                           and e.get("pending_kind") == "generation"
                           for e in d["fish"].values()):
                    _reach(d, "GENERATED")
            self.state.update(generate)

        data = self.state.load()
        if any(e.get("status") == FISH_RECONCILIATION_PENDING
               and e.get("pending_kind") == "generation"
               for e in data["fish"].values()):
            return self._finish(data, "RECONCILIATION_PENDING")

        # Independent QA with quarantine (never auto-accept material discrepancies).
        data = self.state.load()
        if not self._stage_done(data, "QA_VERIFIED"):
            def qa(d: dict) -> None:
                for entry in d["fish"].values():
                    if entry["status"] != "PENDING":
                        continue
                    try:
                        result = self._call("qa", entry=entry, batch_dir=self.batch_dir)
                    except Exception as exc:
                        result = {"outcome": "FAIL", "failed_assertions": [str(exc)]}
                    if result.get("outcome") == "PASS":
                        entry["status"] = FISH_PASS
                    elif result.get("accepted_exception") and not automatic:
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
                    if entry.get("product"):
                        continue  # already resolved by the pre-generation eligibility gate
                    try:
                        resolved = self._call("resolve", entry=entry, batch_dir=self.batch_dir)
                    except Exception as exc:
                        resolved = {"status": "FAILED", "reason": str(exc)}
                    if resolved.get("status") != "RESOLVED":
                        entry["status"] = FISH_QUARANTINED
                        entry["notes"].append("shopify resolution not unique")
                    else:
                        entry["product"] = resolved["product"]
                _reach(d, "SHOPIFY_RESOLVED")
            self.state.update(resolve)

        # Immutable manifest + standing authorisation bound to its hash.
        data = self.state.load()
        if automatic and not self._shopify_candidates(data):
            self._call("telemetry", state=data, batch_dir=self.batch_dir)
            return self._finish(data, "PARTIAL")
        if not self._stage_done(data, "MANIFEST_READY"):
            def manifest(d: dict) -> None:
                built = self._call("build_manifest", state=d, batch_dir=self.batch_dir)
                d["manifest"] = built["manifest"]
                d["manifest_sha256"] = built["manifest_sha256"]
                if built.get("manifest_path"):
                    d["manifest_path"] = str(built["manifest_path"])
                _reach(d, "MANIFEST_READY")
            self.state.update(manifest)

        data = self.state.load()
        if automatic and not self._shopify_candidates(data):
            self._call("telemetry", state=data, batch_dir=self.batch_dir)
            return self._finish(data, "PARTIAL")
        if self._stage_done(data, "SHOPIFY_VERIFIED"):
            receipt = data.get("authorisation")
        elif automatic:
            manifest_path = data.get("manifest_path") or data.get("manifest", {}).get("path")
            if not manifest_path:
                raise ProcessError("persisted production manifest path is required")
            receipt = self.policy.authorise_manifest(
                Path(manifest_path), self.batch_dir / "state" / "authority.json",
                expected_sha256=data.get("manifest_sha256"))
        else:
            receipt = self.policy.authorise(data.get("manifest_sha256"))
        if receipt is None:
            return self._finish(data, "AWAITING_AUTHORISATION")
        if not self._stage_done(data, "AUTHORISED"):
            self.state.update(lambda d: d.update({"authorisation": receipt}) or _reach(d, "AUTHORISED"))

        # Execute (idempotent per fish) then independently verify.
        data = self.state.load()
        if not self._stage_done(data, "SHOPIFY_VERIFIED"):
            def execute(d: dict) -> None:
                _reach(d, "SHOPIFY_EXECUTING")
                for key, entry in d["fish"].items():
                    is_recovery = (entry.get("status") == FISH_RECONCILIATION_PENDING
                                   and entry.get("pending_kind") == "shopify")
                    if entry["status"] not in (FISH_PASS, FISH_PASS_EXCEPTION) and not is_recovery:
                        continue
                    if key in d.get("executed", []):
                        continue  # idempotent: never repeat a Shopify mutation
                    try:
                        adapter = "reconcile" if is_recovery else "execute"
                        outcome = self._call(adapter, entry=entry, state=d, batch_dir=self.batch_dir)
                    except Exception as exc:
                        if is_recovery or self._is_reconciliation_pending(exc):
                            self._mark_pending(entry, "shopify", str(exc))
                            break
                        entry["status"] = FISH_QUARANTINED
                        entry["notes"].append(f"shopify execute failed: {exc}")
                        continue
                    outcome_status = str(outcome.get("status", "")).upper()
                    if outcome_status in ("VERIFIED", "READ_ONLY_VERIFIED"):
                        entry["shopify_receipt"] = outcome.get("receipt")
                        d.setdefault("executed", []).append(key)
                        if is_recovery:
                            self._clear_pending(entry, FISH_PASS)
                    elif outcome_status == "AWAITING_LIVE":
                        # Dry-run: pause without quarantine and without claiming success.
                        d["awaiting_live"] = True
                        break
                    elif outcome_status in ("PENDING_RECONCILIATION", "RECONCILIATION_PENDING",
                                            "UNCERTAIN", "READ_ONLY_FAILED"):
                        self._mark_pending(
                            entry, "shopify", str(outcome.get("reason") or outcome_status))
                        break
                    else:
                        entry["status"] = FISH_QUARANTINED
                        entry["notes"].append("shopify execute not verified")
                if (not d.get("awaiting_live")
                        and not any(e.get("status") == FISH_RECONCILIATION_PENDING
                                    and e.get("pending_kind") == "shopify"
                                    for e in d["fish"].values())):
                    _reach(d, "SHOPIFY_VERIFIED")
            self.state.update(execute)

        data = self.state.load()
        if data.get("awaiting_live"):
            return self._finish(data, "AWAITING_LIVE")
        if any(e.get("status") == FISH_RECONCILIATION_PENDING
               and e.get("pending_kind") == "shopify"
               for e in data["fish"].values()):
            return self._finish(data, "RECONCILIATION_PENDING")
        if not self._stage_done(data, "TELEMETRY_EXPORTED"):
            self.state.update(lambda d: (self._call("telemetry", state=d, batch_dir=self.batch_dir),
                                         _reach(d, "TELEMETRY_EXPORTED")))

        data = self.state.load()
        if not self._stage_done(data, "ARCHIVED"):
            def archive(d: dict) -> None:
                _reach(d, "ARCHIVING")
                outcome = self._call("archive", state=d, batch_dir=self.batch_dir)
                if automatic and (not isinstance(outcome, dict) or outcome.get("status") != "ARCHIVED"
                                  or outcome.get("batch_status") != "COMPLETE"):
                    raise ProcessError("archive did not provide a verified COMPLETE receipt")
                d["archive_receipt"] = outcome
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
        return self._summary(final)

    def _summary(self, final: dict) -> dict:
        summary = {
            "batch_id": self.state.batch_id,
            "stage": final["stage"],
            "status": final["status"],
            "published": len(final.get("executed", [])),
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
