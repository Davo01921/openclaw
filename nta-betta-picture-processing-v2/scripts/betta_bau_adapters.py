#!/usr/bin/env python3
"""Strict production adapters used only by the BAU dispatcher.

This layer retains the existing Grok generator, renderer, uploader, telemetry and
archive engines, while making their inputs satisfy the production evidence
contracts.  The legacy adapters remain available to supervised/offline callers.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import mimetypes
import os
import re
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import betta_adapters as base  # noqa: E402
import betta_shopify_batch as uploader  # noqa: E402
import betta_telemetry as telemetry_mod  # noqa: E402
import label_identity as label_mod  # noqa: E402
import betta_batch as batch_mod


CATALOGUE_FIELDS = ("tank_id", "photo_date", "fish_name", "tail_type", "sex")
QA_ASSERTIONS = {
    "same_identity", "body_anatomy", "scale_markings", "regional_colour",
    "tail_fins_pose", "complete_framing", "realistic_texture",
    "hero_composition", "label", "reference_integrity",
}
GROK_MODEL = "grok-imagine-image-2.0"
TITLE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 '/+().,&-]*$")


class StrictAdapterError(base.AdapterError):
    pass


def _sha(path: Path) -> str:
    return base.sha256_file(Path(path))


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _write_immutable_json(path: Path, value: dict) -> Path:
    """Create exact evidence once; refuse drift on resume."""
    path = Path(path).expanduser().absolute()
    expected = _json_bytes(value)
    if path.exists() or path.is_symlink():
        if (path.is_symlink() or not path.is_file() or
                path.stat().st_mode & 0o222 or path.read_bytes() != expected):
            raise StrictAdapterError(f"immutable evidence differs: {path.name}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(expected)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o444)
    return path


def _iso_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise StrictAdapterError(f"{label} timestamp missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StrictAdapterError(f"{label} timestamp invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StrictAdapterError(f"{label} timestamp must include a timezone")
    return parsed


def _attested_call(evidence: Mapping[str, Any], source_hashes: list[str], label: str,
                   *, not_before: datetime, call_id_required: bool = True) -> None:
    for field in ("provider", "model"):
        if not isinstance(evidence.get(field), str) or not evidence[field].strip():
            raise StrictAdapterError(f"{label} {field} attestation missing")
    if call_id_required and (not isinstance(evidence.get("call_id"), str)
                             or not evidence["call_id"].strip()):
        raise StrictAdapterError(f"{label} call_id attestation missing")
    timestamp = _iso_timestamp(evidence.get("timestamp"), label)
    if timestamp < not_before:
        raise StrictAdapterError(f"{label} predates the immutable batch selection")
    if timestamp > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise StrictAdapterError(f"{label} timestamp is implausibly in the future")
    if evidence.get("input_hashes") != source_hashes:
        raise StrictAdapterError(f"{label} input hashes do not bind the selected evidence")
    try:
        from betta_vision_route import validate_attestation
        validate_attestation(evidence.get("routing"), evidence.get("provider"), evidence.get("model"))
    except (ImportError, ValueError) as exc:
        raise StrictAdapterError(f"{label} route attestation invalid: {exc}") from exc


def _confidence(output: Mapping[str, Any], field: str) -> float:
    confidence = output.get("confidence")
    value = confidence.get(field) if isinstance(confidence, Mapping) else None
    if value is None:
        value = output.get(f"{field}_confidence")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StrictAdapterError(f"catalogue confidence missing for {field}")
    result = float(value)
    if not math.isfinite(result) or result < 0.90 or result > 1.0:
        raise StrictAdapterError(f"catalogue confidence below 0.90 for {field}")
    return result


def _mime(path: Path) -> str:
    value = mimetypes.guess_type(path.name)[0]
    if value == "image/jpg":
        value = "image/jpeg"
    if value not in {"image/png", "image/jpeg"}:
        raise StrictAdapterError(f"uploader does not support original MIME type: {path.suffix}")
    return value


class StrictBAUAdapters(base.Adapters):
    """Production evidence adapter for one dispatcher-owned immutable batch."""

    def __init__(self, *, selected_sources: list[dict], **kwargs):
        budget = kwargs.get("budget")
        if budget is None:
            raise StrictAdapterError("BAU requires a GenerationBudget")
        if not isinstance(selected_sources, list) or not selected_sources:
            raise StrictAdapterError("BAU requires a non-empty immutable source selection")
        super().__init__(**kwargs)
        self.selected_sources = copy.deepcopy(selected_sources)
        maximum = min(20, int(self.budget.limits.get("max_fish_per_batch", 0)))
        if maximum <= 0 or len(selected_sources) > maximum:
            raise StrictAdapterError(f"selected batch exceeds the production maximum of {maximum}")
        self.selection_timestamp = self._selection_timestamp()
        # Permit small clock skew, while allowing a persisted receipt to remain
        # valid for an arbitrarily long crash/resume interval.
        self.evidence_not_before = self.selection_timestamp - timedelta(minutes=5)

    def _selection_timestamp(self) -> datetime:
        path = self.batch_dir / "state" / "sources.json"
        try:
            metadata = path.stat()
            selection = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise StrictAdapterError("immutable dispatcher source selection is unavailable") from exc
        if metadata.st_mode & 0o222:
            raise StrictAdapterError("dispatcher source selection must be read-only")
        expected = sorted(
            (value.get("path"), value.get("sha256"), value.get("size"))
            for value in self.selected_sources
        )
        persisted = selection.get("selected_sources")
        actual = sorted(
            (value.get("path"), value.get("sha256"), value.get("size"))
            for value in persisted
        ) if isinstance(persisted, list) and all(isinstance(value, dict) for value in persisted) else []
        if (selection.get("dispatcher_owned") is not True or
                selection.get("batch_id") != self.batch_id or actual != expected):
            raise StrictAdapterError("dispatcher source selection does not match this batch")
        return _iso_timestamp(selection.get("selected_at"), "source selection")

    def _validate_receipt_identity(self, evidence: Mapping[str, Any], *, source: Path,
                                   source_sha256: str, tank: Optional[str] = None,
                                   hero: Optional[Path] = None,
                                   hero_sha256: Optional[str] = None) -> None:
        expected_source = {"path": str(source.resolve()), "sha256": source_sha256}
        if evidence.get("batch_id") != self.batch_id or evidence.get("source_identity") != expected_source:
            raise StrictAdapterError("call receipt does not bind this batch/source identity")
        if tank is not None and evidence.get("tank_id") != tank:
            raise StrictAdapterError("call receipt does not bind the expected tank")
        if hero is not None:
            expected_hero = {"path": str(hero.resolve()), "sha256": hero_sha256}
            if evidence.get("hero_identity") != expected_hero:
                raise StrictAdapterError("QA receipt does not bind the expected hero identity")

    def _record_vision_evidence(self, stage: str, tank: str, evidence: Mapping[str, Any],
                                started: float) -> None:
        for index, attempt in enumerate(evidence.get("attempts") or [], 1):
            if not isinstance(attempt, Mapping):
                continue
            usage = attempt.get("usage") if isinstance(attempt.get("usage"), Mapping) else {}
            self._record(
                stage, "ERROR", tank=tank, provider=attempt.get("provider"),
                model=attempt.get("model"), tokens_input=usage.get("tokens_input"),
                tokens_output=usage.get("tokens_output"), error=str(attempt.get("error") or "provider attempt failed"),
                detail={"attempt": index, "final_call_id": evidence.get("call_id")},
            )
        usage = evidence.get("usage") if isinstance(evidence.get("usage"), Mapping) else {}
        self._record(
            stage, "OK", tank=tank, started=started,
            provider=evidence.get("provider"), model=evidence.get("model"),
            tokens_input=usage.get("tokens_input"), tokens_output=usage.get("tokens_output"),
            detail={"attempt": len(evidence.get("attempts") or []) + 1,
                    "call_id": evidence.get("call_id")},
        )

    # -- immutable intake ------------------------------------------------- #
    def intake(self, batch_dir, state):
        destination = Path(batch_dir).resolve() / "intake"
        destination.mkdir(parents=True, exist_ok=True)
        intake_root = self.intake_dir.resolve()
        seen: set[str] = set()
        fish: list[dict] = []
        entered = base.iso_now()
        for selected in self.selected_sources:
            source_text = selected.get("path")
            if not isinstance(source_text, str) or os.path.realpath(source_text) != source_text:
                raise StrictAdapterError("selected source path is not canonical")
            source = Path(source_text)
            if not source.is_file() or source.parent.resolve() != intake_root:
                raise StrictAdapterError("selected source is outside the configured intake root")
            digest = selected.get("sha256")
            if not isinstance(digest, str) or uploader.SHA_RE.fullmatch(digest) is None:
                raise StrictAdapterError("selected source SHA-256 is invalid")
            if digest in seen:
                raise StrictAdapterError("selected source content is duplicated")
            if source.stat().st_size != selected.get("size") or _sha(source) != digest:
                raise StrictAdapterError("selected source changed after dispatcher selection")
            target = destination / source.name
            if target.exists():
                if not target.is_file() or _sha(target) != digest:
                    raise StrictAdapterError(f"intake destination collision: {target.name}")
            else:
                shutil.copy2(source, target)
                if _sha(target) != digest:
                    raise StrictAdapterError("copied intake hash mismatch")
            seen.add(digest)
            if self.registry:
                self.registry.record(digest, self.batch_id)
            self._record("intake", "OK", tank=source.stem, detail={"sha256": digest})
            fish.append({"path": str(target.resolve()), "sha256": digest,
                         "size": target.stat().st_size, "date_entered": entered})
        return {"fish": fish, "selected_source_count": len(fish)}

    # -- complete, attested catalogue ------------------------------------ #
    def _vision_call(self, files: list, mode: str, *, attempts: int = 2) -> dict:
        """One moderation-free vision call with bounded retries on call failures.

        Retries cover transport-level failures (timeout, nonzero exit, invalid
        envelope JSON); deterministic evidence/quality outcomes are never retried
        here.
        """
        runner = self.runners.get(mode) if mode == "label" else self.runners.get("catalogue")
        delay = float(self.runners.get("vision_retry_delay_seconds", 2.0))
        last_error: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            try:
                if runner is not None:
                    evidence = runner([Path(value) for value in files])
                else:
                    argv = [sys.executable, str(_SCRIPT_DIR / "vision_review.py"),
                            "--mode", mode]
                    for value in files:
                        argv.extend(["--file", str(value)])
                    evidence = json.loads(base._subprocess_runner(argv))
                if not isinstance(evidence, dict):
                    raise StrictAdapterError(f"{mode} returned non-object evidence")
                return evidence
            except Exception as exc:  # transport failure: bounded retry
                last_error = exc
                if attempt < attempts and delay > 0:
                    time.sleep(delay)
        raise StrictAdapterError(
            f"{mode} call failed after {attempts} attempts: {last_error}") from last_error

    def identify(self, record, batch_dir):
        source = Path(record["path"])
        started = time.monotonic()
        receipt_path = Path(batch_dir) / "evidence" / "catalogue" / f"{record['sha256']}.json"
        reused = receipt_path.is_file()
        if reused:
            evidence = json.loads(receipt_path.read_text())
        else:
            try:
                evidence = self._vision_call([source], "catalogue")
            except StrictAdapterError as exc:
                try:
                    self._record("identify", "ERROR", tank=source.stem, started=started,
                                 error=str(exc))
                except Exception:  # never mask the original failure
                    pass
                raise
        if not isinstance(evidence, dict):
            raise StrictAdapterError("catalogue returned non-object evidence")
        _attested_call(evidence, [record["sha256"]], "catalogue",
                       not_before=self.evidence_not_before)
        if reused:
            self._validate_receipt_identity(
                evidence, source=source, source_sha256=record["sha256"],
            )
        output = evidence.get("output")
        if not isinstance(output, dict):
            raise StrictAdapterError("catalogue output object missing")

        # Identity-quality outcomes (low confidence, unreadable or malformed
        # label, unusable title components) are returned as a truthful uncertain
        # decision for the orchestrator to quarantine and retry with a focused
        # label crop.  Only call/attestation failures raise.
        uncertain_reason: Optional[str] = None
        tank = None
        photo_date = None
        fish_name = str(output.get("fish_name") or "").strip()
        tail_type = str(output.get("tail_type") or "").strip()
        sex = str(output.get("sex") or "").strip().title()
        title = None
        try:
            tank = label_mod.normalize_tank(output.get("tank_id")) if output.get("tank_id") else None
            photo_date = output.get("photo_date")
            if photo_date is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(photo_date)):
                photo_date = label_mod.normalize_date(photo_date)
        except (TypeError, ValueError):
            tank, photo_date = None, None
        confidence_output = dict(output)
        confidence_output.setdefault("tank_id_confidence", output.get("tank_confidence"))
        confidence_output.setdefault("photo_date_confidence", output.get("date_confidence"))
        confidence_values = {}
        for field in ("tank_id", "photo_date"):
            try:
                confidence_values[field] = _confidence(confidence_output, field)
            except StrictAdapterError:
                confidence_values[field] = None
        if output.get("one_fish_visible") is not True:
            uncertain_reason = "one fish not confirmed visible"
        elif confidence_values["tank_id"] is None or confidence_values["photo_date"] is None:
            uncertain_reason = "catalogue confidence below 0.90"
        elif not tank or not photo_date:
            uncertain_reason = "catalogue tank/date is invalid"
        elif (not TITLE_COMPONENT_RE.fullmatch(fish_name)
                or not TITLE_COMPONENT_RE.fullmatch(tail_type)
                or sex not in {"Male", "Female"}):
            uncertain_reason = "catalogue title components are incomplete or invalid"
        elif tank.lower() in fish_name.lower() or sex.lower() in fish_name.lower():
            uncertain_reason = "fish_name contains a deterministic title component"
        else:
            try:
                title = batch_mod.expected_catalogue_title({**output, "tank_id": tank})
            except (TypeError, ValueError):
                uncertain_reason = "deterministic title could not be composed"

        receipt = {
            "batch_id": self.batch_id,
            "source_identity": {"path": str(source.resolve()), "sha256": record["sha256"]},
            "provider": evidence["provider"], "model": evidence["model"],
            "call_id": evidence["call_id"], "timestamp": evidence["timestamp"],
            "input_hashes": [record["sha256"]], "output": {
                **output, "tank_id": tank, "photo_date": photo_date,
                "fish_name": fish_name, "tail_type": tail_type, "sex": sex,
                "title": title,
            },
            "uncertain": uncertain_reason is not None,
            "uncertain_reason": uncertain_reason,
            "routing": evidence.get("routing"), "usage": evidence.get("usage"),
            "attempts": evidence.get("attempts") or [],
        }
        receipt_path = (Path(batch_dir) / "evidence" / "catalogue" /
                        f"{record['sha256']}.json")
        if not reused:
            _write_immutable_json(receipt_path, receipt)
        if not reused:
            self._record_vision_evidence(
                "identify", tank or source.stem, evidence, started)
        result = {
            "tank_id": tank, "photo_date": photo_date, "fish_name": fish_name,
            "tail_type": tail_type, "sex": sex, "title": title,
            "uncertain": uncertain_reason is not None,
            "uncertain_reason": uncertain_reason,
            "catalogue_evidence_path": str(receipt_path),
            "catalogue_evidence_sha256": _sha(receipt_path),
            "date_entered": record.get("date_entered"),
        }
        return result

    def retry_identify(self, entry, batch_dir):
        """One focused top-label crop re-read for otherwise uncertain fish.

        The crop covers the physical tank card only; a confident reading binds
        the same source hash and must pass the same attestation and confidence
        gates as the catalogue read before it can replace an uncertain result.
        """
        source = Path(entry["source_path"]).resolve()
        digest = entry.get("source_sha256")
        if not isinstance(digest, str) or _sha(source) != digest:
            raise StrictAdapterError("label retry source changed")
        fish_name = str(entry.get("fish_name") or "")
        tail_type = str(entry.get("tail_type") or "")
        sex = str(entry.get("sex") or "Male")
        if (not TITLE_COMPONENT_RE.fullmatch(fish_name)
                or not TITLE_COMPONENT_RE.fullmatch(tail_type)
                or sex not in {"Male", "Female"}):
            return {"tank_id": None, "photo_date": None, "uncertain": True,
                    "proposed_title": None,
                    "uncertain_reason": "fish components unsuitable for label retry"}
        crop_dir = Path(batch_dir) / "evidence" / "label-crops"
        crop_dir.mkdir(parents=True, exist_ok=True)
        crop = crop_dir / f"{digest}-label.png"
        if not crop.is_file():
            temporary = crop_dir / (crop.name + ".part")
            try:
                from PIL import Image  # local import: only needed for the crop
                with Image.open(source) as image:
                    width, height = image.size
                    upper = image.convert("RGB").crop(
                        (0, 0, width, max(1, int(height * 0.30))))
                    upper.save(temporary, format="PNG")
                os.replace(temporary, crop)
            except Exception as exc:
                if temporary.exists():
                    temporary.unlink()
                raise StrictAdapterError(
                    f"label crop could not be created: {exc}") from exc
        crop_sha = _sha(crop)
        started = time.monotonic()
        try:
            evidence = self._vision_call([crop], "label")
        except StrictAdapterError as exc:
            try:
                self._record("identify_label_retry", "ERROR",
                             tank=entry.get("tank_id") or source.stem,
                             started=started, error=str(exc))
            except Exception:
                pass
            raise
        _attested_call(evidence, [crop_sha], "catalogue label retry",
                       not_before=self.evidence_not_before)
        output = evidence.get("output")
        if not isinstance(output, dict):
            raise StrictAdapterError("catalogue label retry output object missing")
        tank = None
        photo_date = None
        try:
            tank = label_mod.normalize_tank(output.get("tank_id")) if output.get("tank_id") else None
            photo_date = output.get("photo_date")
            if photo_date is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(photo_date)):
                photo_date = label_mod.normalize_date(photo_date)
        except (TypeError, ValueError):
            tank, photo_date = None, None
        tank_confidence = output.get("tank_confidence")
        date_confidence = output.get("date_confidence")
        uncertain = not tank or not photo_date
        for value in (tank_confidence, date_confidence):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                uncertain = True
            elif not math.isfinite(float(value)) or float(value) < 0.90:
                uncertain = True
        title = None
        if not uncertain:
            try:
                title = batch_mod.expected_catalogue_title({
                    "tank_id": tank, "fish_name": fish_name,
                    "tail_type": tail_type, "sex": sex,
                })
            except (TypeError, ValueError):
                uncertain = True
        receipt = {
            "batch_id": self.batch_id,
            "source_identity": {"path": str(source), "sha256": digest},
            "crop_identity": {"path": str(crop), "sha256": crop_sha},
            "provider": evidence["provider"], "model": evidence["model"],
            "call_id": evidence["call_id"], "timestamp": evidence["timestamp"],
            "input_hashes": [crop_sha],
            "output": {**output, "tank_id": tank, "photo_date": photo_date,
                       "title": title if not uncertain else None},
            "uncertain": uncertain,
            "routing": evidence.get("routing"), "usage": evidence.get("usage"),
            "attempts": evidence.get("attempts") or [],
        }
        receipt_path = (Path(batch_dir) / "evidence" / "catalogue" /
                        f"{digest}-label-retry.json")
        _write_immutable_json(receipt_path, receipt)
        self._record("identify_label_retry", "UNCERTAIN" if uncertain else "OK",
                     tank=tank or entry.get("tank_id") or source.stem, started=started,
                     provider=evidence.get("provider"), model=evidence.get("model"))
        return {
            "tank_id": tank if not uncertain else None,
            "photo_date": photo_date if not uncertain else None,
            "uncertain": uncertain, "proposed_title": title,
            "tank_confidence": tank_confidence, "date_confidence": date_confidence,
            "catalogue_evidence_path": str(receipt_path),
            "catalogue_evidence_sha256": _sha(receipt_path),
        }

    # -- pre-generation eligibility (read-only, no spend) ----------------- #
    def eligibility(self, entry, state, batch_dir):
        """Resolve the exact product and enforce the standing 0-to-1 baseline.

        Read-only: one fresh Shopify resolution with bounded retries.  Ineligible
        fish carry a precise reason so the orchestrator quarantines them instead
        of spending generation budget on a write the standing scope cannot
        authorise.
        """
        tank = entry.get("tank_id")
        if not tank:
            return {"eligible": False, "reason": "tank identity is unresolved"}
        runner = self.runners.get("resolve")
        if runner is None:
            raise StrictAdapterError("eligibility requires the Shopify resolve runner")
        attempts = 3
        delay = float(self.runners.get("eligibility_retry_delay_seconds", 1.0))
        last_error: Optional[Exception] = None
        resolved = None
        for attempt in range(1, attempts + 1):
            try:
                resolved = runner(entry)
                last_error = None
                break
            except Exception as exc:  # transient bridge/network errors retry
                last_error = exc
                if attempt < attempts and delay > 0:
                    time.sleep(delay)
                    delay = min(delay * 2, 4.0)
        if last_error is not None:
            return {"eligible": False,
                    "reason": f"shopify resolution failed after {attempts} attempts: {last_error}"}
        if not isinstance(resolved, dict) or resolved.get("status") != "RESOLVED":
            return {"eligible": False, "reason": "shopify resolution is not unique"}
        product = resolved.get("product")
        if not isinstance(product, dict):
            return {"eligible": False, "reason": "shopify resolution omitted the product snapshot"}
        before = product.get("before")
        if not isinstance(before, dict):
            return {"eligible": False, "reason": "shopify resolution omitted the baseline"}
        rule = self.policy.inventory_rule() if callable(
            getattr(self.policy, "inventory_rule", None)) else {}
        allowed_from = rule.get("allowed_from", [0])
        available = before.get("inventory")
        if available not in allowed_from:
            return {"eligible": False,
                    "reason": (f"shopify inventory baseline is {available!r}; "
                               f"automatic scope permits {allowed_from} to 1 only")}
        if rule.get("require_deny", True) and before.get("inventory_policy") != "DENY":
            return {"eligible": False, "reason": "shopify inventory policy is not DENY"}
        if rule.get("require_tracked", True) and before.get("tracked") is not True:
            return {"eligible": False, "reason": "shopify inventory is not tracked"}
        return {"eligible": True, "reason": "shopify baseline permits 0-to-1",
                "product": product}

    # -- paid generation with durable, hash-bound receipt ---------------- #
    def _generation_receipt(self, tank: str, clean: Path, source: Path) -> Optional[dict]:
        path = self.batch_dir / "evidence" / "generation" / f"{tank}.json"
        if not path.is_file():
            return None
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise StrictAdapterError("generation receipt is unreadable") from exc
        self._validate_generation_receipt(receipt, source, clean)
        return receipt

    @staticmethod
    def _validate_generation_receipt(receipt: Mapping[str, Any], source: Path, clean: Path) -> None:
        if receipt.get("provider") != "xai" or receipt.get("model") != GROK_MODEL:
            raise StrictAdapterError("generation provider/model receipt is invalid")
        _iso_timestamp(receipt.get("timestamp"), "generation")
        if (receipt.get("source_sha256") != _sha(source)
                or receipt.get("output_sha256") != _sha(clean)
                or Path(str(receipt.get("source_path", ""))).resolve() != source.resolve()
                or Path(str(receipt.get("output_path", ""))).resolve() != clean.resolve()):
            raise StrictAdapterError("generation receipt does not bind source/output bytes")
        cost = receipt.get("grokai_cost")
        if (isinstance(cost, bool) or not isinstance(cost, (int, float))
                or not math.isfinite(float(cost)) or float(cost) < 0
                or not receipt.get("grokai_cost_source")):
            raise StrictAdapterError("generation cost receipt is unreliable")

    def generate(self, entry, batch_dir):
        if getattr(self.policy, "source_path", None):
            self.policy = type(self.policy).load(self.policy.source_path)
            if not self.policy.paid_generation_authorised():
                raise StrictAdapterError("standing paid generation authority was revoked")
        if not self.live_generation and "generate" not in self.runners:
            raise StrictAdapterError("paid generation not authorised for this run")
        tank = entry["tank_id"]
        source = Path(entry["source_path"]).resolve()
        clean = Path(batch_dir).resolve() / "evidence" / "heroes" / f"{tank}-clean.png"
        receipt_path = Path(batch_dir).resolve() / "evidence" / "generation" / f"{tank}.json"
        self.budget.register_fish(tank)
        ledger = self.budget._load()
        if ledger.get("blocked") is True:
            raise StrictAdapterError(
                f"generation budget is blocked: {ledger.get('blocked_reason') or 'cap exceeded'}")
        outstanding = [rid for rid, reservation in ledger["reservations"].items()
                       if reservation.get("tank") == tank and not reservation.get("settled")]

        # A reliable local file+receipt pair is the only permitted recovery for
        # an unknown generation result.  It reconciles the held reservation
        # without another provider call.
        if clean.exists():
            receipt = self._generation_receipt(tank, clean, source)
            if receipt is None:
                raise base.ReconciliationPending(
                    "generation",
                    "generation output exists without a reliable receipt; manual reconciliation required",
                )
            if len(outstanding) > 1:
                raise base.ReconciliationPending(
                    "generation", "multiple unsettled generation requests require manual reconciliation")
            if outstanding:
                self.budget.settle(outstanding[0], float(receipt["grokai_cost"]), reported=True)
            return {"hero_path": str(clean), "hero_sha256": _sha(clean),
                    "generation_receipt": str(receipt_path)}

        if outstanding:
            raise base.ReconciliationPending(
                "generation", "unsettled generation request requires reconciliation; request will not replay")
        ok, reason = self.budget.can_attempt(tank)
        if not ok:
            raise StrictAdapterError(f"generation blocked: {reason}")
        reservation = self.budget.reserve(tank)
        attempt = int(self.budget._load()["fish"][tank]["attempts"])
        runner = self.runners.get("generate") or base._subprocess_runner
        started = time.monotonic()
        try:
            output = runner([sys.executable, str(_SCRIPT_DIR / "grok_hero.py"),
                             "--source", str(source), "--output", str(clean),
                             "--model", GROK_MODEL, "--quality", "low"])
        except Exception as exc:
            # Acceptance is unknown. Keep the conservative reservation held and
            # never issue a second provider request.
            self._record("generate", "UNCERTAIN", tank=tank, started=started,
                         error=str(exc), detail={"attempt": attempt, "reservation": reservation})
            raise base.ReconciliationPending(
                "generation", "generation outcome is uncertain; request will not replay") from exc
        try:
            receipt = json.loads(output) if isinstance(output, str) else output
            if not isinstance(receipt, dict) or not clean.is_file():
                raise StrictAdapterError("generation omitted its output or JSON receipt")
            self._validate_generation_receipt(receipt, source, clean)
            # Evidence lands first. A crash before settlement is reconciled from
            # these local bytes on the next run.
            _write_immutable_json(receipt_path, receipt)
            charged = self.budget.settle(
                reservation, float(receipt["grokai_cost"]), reported=True)
        except Exception as exc:
            self._record("generate", "UNCERTAIN", tank=tank, started=started,
                         error=str(exc), detail={"attempt": attempt, "reservation": reservation})
            ledger = self.budget._load()
            if ledger.get("blocked") is True:
                raise StrictAdapterError(
                    f"generation budget is blocked: {ledger.get('blocked_reason') or 'cap exceeded'}") from exc
            raise base.ReconciliationPending(
                "generation", "generation output lacks a reliable receipt; request will not replay") from exc
        self._record("generate", "OK", tank=tank, started=started,
                     provider=receipt["provider"], model=receipt["model"],
                     tokens_input=receipt.get("tokens_input"),
                     tokens_output=receipt.get("tokens_output"), cost=charged,
                     cost_source=receipt["grokai_cost_source"],
                     detail={"attempt": attempt, "receipt": str(receipt_path)})
        return {"hero_path": str(clean), "hero_sha256": _sha(clean),
                "generation_receipt": str(receipt_path)}

    # -- exact mandatory QA ---------------------------------------------- #
    def qa(self, entry, batch_dir):
        source = Path(entry["source_path"]).resolve()
        hero = Path(entry["hero_path"]).resolve()
        runner = self.runners.get("qa")
        started = time.monotonic()
        path = Path(batch_dir).resolve() / "evidence" / "qa" / f"{entry['tank_id']}.json"
        reused = path.is_file()
        if runner is None:
            from PIL import Image
            with Image.open(hero) as image:
                if image.size != (2048, 2048) or hero.name != f"{entry['tank_id']}.png":
                    raise StrictAdapterError("deterministic hero dimensions/filename check failed")
        if reused:
            evidence = json.loads(path.read_text(encoding="utf-8"))
        elif runner is None:
            evidence = json.loads(base._subprocess_runner([
                sys.executable, str(_SCRIPT_DIR / "vision_review.py"), "--mode", "qa",
                "--file", str(source), "--file", str(hero), "--file", str(source),
            ]))
        else:
            evidence = runner(entry)
        if not isinstance(evidence, dict):
            raise StrictAdapterError("QA returned non-object evidence")
        expected_hashes = [entry["source_sha256"], entry["hero_sha256"], entry["source_sha256"]]
        if _sha(source) != entry["source_sha256"] or _sha(hero) != entry["hero_sha256"]:
            raise StrictAdapterError("QA input bytes changed")
        _attested_call(evidence, expected_hashes, "QA", not_before=self.evidence_not_before)
        if reused:
            self._validate_receipt_identity(
                evidence, source=source, source_sha256=entry["source_sha256"],
                tank=entry["tank_id"], hero=hero, hero_sha256=entry["hero_sha256"],
            )
        output = evidence.get("output") if isinstance(evidence.get("output"), dict) else evidence
        assertions = output.get("assertions") if isinstance(output, dict) else None
        overall = output.get("overall") if isinstance(output, dict) else None
        if (not isinstance(assertions, dict) or not QA_ASSERTIONS.issubset(assertions)
                or any(assertions[name] != "PASS" for name in QA_ASSERTIONS)
                or any(value != "PASS" for value in assertions.values())
                or overall != "PASS" or evidence.get("accepted_exception")):
            failed = sorted(name for name in QA_ASSERTIONS
                            if not isinstance(assertions, dict) or assertions.get(name) != "PASS")
            self._record("qa", "FAIL", tank=entry["tank_id"], started=started,
                         provider=evidence.get("provider"), model=evidence.get("model"),
                         detail={"failed_assertions": failed})
            return {"outcome": "FAIL", "failed_assertions": failed,
                    "accepted_exception": None}
        receipt = {
            "batch_id": self.batch_id, "tank_id": entry["tank_id"],
            "source_identity": {"path": str(source), "sha256": entry["source_sha256"]},
            "hero_identity": {"path": str(hero), "sha256": entry["hero_sha256"]},
            "provider": evidence["provider"], "model": evidence["model"],
            "call_id": evidence["call_id"], "timestamp": evidence["timestamp"],
            "input_hashes": expected_hashes,
            "routing": evidence.get("routing"), "usage": evidence.get("usage"),
            "attempts": evidence.get("attempts") or [],
            "output": {"assertions": {name: assertions[name] for name in sorted(assertions)},
                       "overall": "PASS", "reasons": output.get("reasons", [])},
        }
        _write_immutable_json(path, receipt)
        entry["image_qa_path"] = str(path)
        entry["image_qa_sha256"] = _sha(path)
        if not reused:
            self._record_vision_evidence("qa", entry["tank_id"], evidence, started)
        return {"outcome": "PASS", "failed_assertions": [],
                "accepted_exception": None, "receipt_path": str(path),
                "receipt_sha256": _sha(path)}

    # -- real uploader ManifestBundle ------------------------------------ #
    @staticmethod
    def _location(raw_product: dict, location_id: str) -> dict:
        variants = (raw_product.get("variants") or {}).get("nodes") or []
        if len(variants) != 1:
            raise StrictAdapterError("resolved snapshot does not contain exactly one variant")
        levels = ((variants[0].get("inventoryItem") or {}).get("inventoryLevels") or {}).get("nodes") or []
        matches = [level.get("location") for level in levels
                   if (level.get("location") or {}).get("id") == location_id]
        if len(matches) != 1:
            raise StrictAdapterError("resolved snapshot lacks the exact inventory location")
        return matches[0]

    def build_manifest(self, state, batch_dir):
        batch_dir = Path(batch_dir).resolve()
        entries = [entry for entry in state.get("fish", {}).values()
                   if entry.get("status") == "VERIFIED"]
        if not entries:
            raise StrictAdapterError("no strict-QA PASS fish are eligible for a manifest")
        if len(entries) > min(20, int(self.budget.limits["max_fish_per_batch"])):
            raise StrictAdapterError("manifest exceeds the production batch maximum")
        write_authorised = bool(self.live_shopify)
        approval_items, snapshots, details, labels, authorities, items = [], [], [], [], [], []
        for entry in sorted(entries, key=lambda value: value["tank_id"]):
            tank = entry["tank_id"]
            product = entry.get("product") or {}
            before = product.get("before") or {}
            raw_product = copy.deepcopy(product.get("raw_snapshot"))
            if not isinstance(raw_product, dict):
                raise StrictAdapterError(f"{tank}: full raw Shopify snapshot missing")
            hero = Path(entry["hero_path"]).resolve()
            original = Path(entry["source_path"]).resolve()
            qa_path = Path(entry.get("image_qa_path", "")).resolve()
            for path, digest, label in (
                (hero, entry.get("hero_sha256"), "hero"),
                (original, entry.get("source_sha256"), "original"),
                (qa_path, entry.get("image_qa_sha256"), "QA"),
            ):
                if not path.is_file() or _sha(path) != digest:
                    raise StrictAdapterError(f"{tank}: {label} evidence missing or changed")
            title = entry.get("title")
            expected_title = (f"{tank} - {entry.get('fish_name')} "
                              f"{entry.get('tail_type')} {entry.get('sex')}")
            if title != expected_title:
                raise StrictAdapterError(f"{tank}: deterministic title mismatch")
            product_id = product.get("id")
            variant_id = product.get("variant_id")
            inventory_id = product.get("inventory_item_id")
            location_id = product.get("location_id")
            location = self._location(raw_product, location_id)
            source_reference = f"bau:{self.batch_id}:{entry['source_sha256']}"
            approval_items.append({
                "tank_id": tank, "product_id": product_id, "variant_id": variant_id,
                "inventory_item_id": inventory_id, "existing_title": before.get("title"),
                "proposed_title": title, "existing_arrival_date": before.get("arrival_date"),
                "proposed_arrival_date": entry["photo_date"],
                "existing_inventory": before.get("inventory"), "proposed_inventory": 1,
                "source_reference": source_reference, "hero_path": str(hero),
                "hero_sha256": entry["hero_sha256"], "original_path": str(original),
                "original_sha256": entry["source_sha256"],
                "retail_price_preserved": before.get("price"),
                "cost_preserved": before.get("cost"),
            })
            snapshots.append({"tank_id": tank, "status": "PREFLIGHT_PASS",
                              "inventory_location": location, "product": raw_product})
            details.append({
                "tank_id": tank, "product_id": product_id, "variant_id": variant_id,
                "inventory_item_id": inventory_id, "existing_title": before.get("title"),
                "product_status": before.get("status"), "handle": before.get("handle"),
                "vendor": before.get("vendor"), "product_type": before.get("product_type"),
                "retail_price": before.get("price"), "cost": before.get("cost"),
                "existing_arrival_date": before.get("arrival_date"),
                "inventory_quantity": before.get("inventory"),
            })
            labels.append({"tank_id": tank, "source_path": str(original),
                           "source_sha256": entry["source_sha256"],
                           "photo_date": entry["photo_date"], "status": "RECONCILED"})
            authorities.append({
                "tank_id": tank, "source_sha256": entry["source_sha256"],
                "new_fish_authorised": True, "source_reference": source_reference,
                "intake_confirmed": True, "shopify_write_authorised": write_authorised,
            })
            items.append({
                "tank_id": tank, "product_id": product_id, "variant_id": variant_id,
                "inventory_item_id": inventory_id, "location_id": location_id,
                "approved_title": title, "arrival_date": entry["photo_date"],
                "quantity": 1, "inventory_reason": "received",
                "source_reference": source_reference,
                "hero": {"path": str(hero), "sha256": entry["hero_sha256"],
                         "mime_type": _mime(hero)},
                "original": {"path": str(original), "sha256": entry["source_sha256"],
                             "mime_type": _mime(original)},
                "image_qa": {"path": str(qa_path), "sha256": entry["image_qa_sha256"],
                             "exception": None},
                "write_authorised": write_authorised,
            })

        evidence_values = {
            "approval_plan": {"items": approval_items},
            "protected_snapshot": {"records": snapshots},
            "shopify_details": {"items": details},
            "labels": {"items": labels},
            "new_fish_authority": {"items": authorities},
        }
        evidence_records = {}
        for name, value in evidence_values.items():
            path = batch_dir / "evidence" / "shopify" / f"{name}.json"
            _write_immutable_json(path, value)
            evidence_records[name] = {"path": str(path), "sha256": _sha(path)}
        manifest = {
            "schema": uploader.MANIFEST_SCHEMA, "batch_id": self.batch_id,
            "shopify_write_authorised": write_authorised,
            "state_dir": str(batch_dir / "state" / "shopify"),
            "report_dir": str(batch_dir / "reports" / "shopify"),
            "evidence": evidence_records, "items": items,
        }
        path = batch_dir / "manifest" / "shopify-production.json"
        _write_immutable_json(path, manifest)
        bundle = uploader.ManifestBundle(path)
        if len(bundle.contexts) != len(items):
            raise StrictAdapterError("uploader manifest validation lost an item")
        csv_path = batch_dir / "reports" / "betta-inventory.csv"
        if not csv_path.exists():
            with csv_path.open("x", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Title", "Retail Price", "Cost", "Quantity"])
                for entry in sorted(entries, key=lambda value: value["tank_id"]):
                    before = entry["product"]["before"]
                    writer.writerow([entry["title"], before["price"], before["cost"], 1])
        return {"manifest": manifest, "manifest_path": str(path),
                "manifest_sha256": bundle.sha256}

    def execute(self, entry, state, batch_dir):
        path = Path(state["manifest_path"])
        if _sha(path) != state["manifest_sha256"]:
            raise StrictAdapterError("persisted manifest bytes changed before execution")
        if not self.live_shopify:
            return {"status": "AWAITING_LIVE"}
        if getattr(self.policy, "source_path", None):
            self.policy = type(self.policy).load(self.policy.source_path)
        self.policy.authorise_manifest(path, Path(batch_dir) / "state" / "authority.json",
                                      expected_sha256=state["manifest_sha256"])
        preflight = self.runners.get("preflight")
        if preflight is None:
            raise StrictAdapterError("live uploader preflight is required")
        result = preflight(manifest_path=path, manifest_sha256=state["manifest_sha256"], tank_id=entry["tank_id"])
        if result.get("status") != "PREFLIGHT_PASS":
            raise StrictAdapterError("fresh uploader preflight blocked execution")
        try:
            return self.runners["execute"](entry, path, state["manifest_sha256"])
        except Exception as exc:
            raise base.ReconciliationPending(
                "shopify", "Shopify write result is unknown; mutation will not replay") from exc

    def reconcile(self, entry, state, batch_dir):
        """Perform only the binding's read-only reconciliation for pending Shopify state."""
        path = Path(state["manifest_path"])
        if not path.is_file() or _sha(path) != state.get("manifest_sha256"):
            raise StrictAdapterError("persisted manifest bytes changed before reconciliation")
        runner = self.runners.get("reconcile")
        if runner is None:
            raise StrictAdapterError("Shopify reconciliation runner is required")
        result = runner(entry, path, state["manifest_sha256"])
        if not isinstance(result, dict):
            raise StrictAdapterError("Shopify reconciliation returned a non-object result")
        return result

    # -- per-fish operational telemetry plus call export ----------------- #
    def telemetry(self, state, batch_dir):
        batch_dir = Path(batch_dir).resolve()
        con = telemetry_mod.connect(self.telemetry_db)
        try:
            telemetry_mod.ensure_call_schema(con)
            for entry in state.get("fish", {}).values():
                if not entry.get("tank_id"):
                    continue
                rows = con.execute(
                    "SELECT stage,provider,model,tokens_input,tokens_output,cost,cost_source,outcome "
                    "FROM betta_call_telemetry WHERE batch_id=? AND tank_number=? ORDER BY id",
                    (self.batch_id, entry.get("tank_id")),
                ).fetchall()
                providers = sorted({row[1] for row in rows if row[1]})
                models = sorted({row[2] for row in rows if row[2]})
                grok = [row for row in rows if row[0] == "generate"]
                costs = [float(row[5]) for row in grok if row[5] is not None]
                started_at = entry.get("date_entered") or state.get("created_at") or base.iso_now()
                verified_at = ((entry.get("shopify_receipt") or {}).get("verified_at")
                               if isinstance(entry.get("shopify_receipt"), dict) else None)
                archive_receipt = state.get("archive_receipt")
                archive_completed_at = state.get("archive_completed_at")
                if archive_completed_at is None and isinstance(archive_receipt, Mapping):
                    archive_completed_at = archive_receipt.get("completed_at")
                telemetry_mod.upsert(con, {
                    "batch_id": self.batch_id, "tank_number": entry["tank_id"],
                    "date_entered": started_at,
                    "arrival_date": entry.get("photo_date"),
                    "onboarding_started_at": started_at,
                    "shopify_verified_at": verified_at,
                    "onboarding_seconds": telemetry_mod.seconds_between(started_at, verified_at),
                    "archive_completed_at": archive_completed_at,
                    "end_to_archive_seconds": telemetry_mod.seconds_between(started_at, archive_completed_at),
                    "model_calls": sum(1 for row in rows if row[1] or row[2]),
                    "retry_count": sum(1 for row in rows if row[7] in {"ERROR", "UNCERTAIN"}),
                    "grok_calls": len(grok),
                    "grok_cost_unknown_calls": sum(1 for row in grok if row[5] is None),
                    "tokens_input": sum(int(row[3] or 0) for row in rows),
                    "tokens_output": sum(int(row[4] or 0) for row in rows),
                    "grokai_cost": sum(costs) if grok and len(costs) == len(grok) else None,
                    "grokai_cost_currency": "USD",
                    "grokai_cost_source": ",".join(sorted({row[6] for row in grok if row[6]})) or None,
                    "provider": ",".join(providers) or None, "model": ",".join(models) or None,
                    "product_id": (entry.get("product") or {}).get("id"),
                    "title": entry.get("title"),
                })
            calls_csv = batch_dir / "reports" / "betta-call-telemetry.csv"
            rows = telemetry_mod.export_calls(con, self.batch_id, calls_csv)
            aggregate_csv = batch_dir / "reports" / "betta-telemetry.csv"
            telemetry_mod.export_csv(con, aggregate_csv, batch_id=self.batch_id)
            summary = telemetry_mod.batch_call_summary(con, self.batch_id)
            summary.update({"call_rows": rows, "calls_csv": str(calls_csv),
                            "telemetry_csv": str(aggregate_csv)})
            return summary
        finally:
            con.close()


def make_strict_adapters(**kwargs) -> dict:
    bundle = StrictBAUAdapters(**kwargs)
    return {name: getattr(bundle, name) for name in (
        "intake", "identify", "retry_identify", "eligibility", "generate", "finish",
        "qa", "resolve", "build_manifest", "execute", "reconcile", "telemetry",
        "archive",
    )}

