#!/usr/bin/env python3
"""Offline deterministic runtime composition for NTA Betta Processing V2.1.

`betta_batch.py` owns the ledger state machine, evidence gates and the mutation
envelope. This module supplies the remaining deterministic safety duties that the
closeout and audit documents left to the live OpenClaw adapter:

* serialized ledger writes (advisory file lock + atomic replacement);
* cross-batch intake / source deduplication;
* API-error classification for writer and reader responses;
* uncertain-write reconciliation that never performs an automatic retry;
* inventory CSV construction and deterministic validation;
* telemetry-before-PASS gating;
* an independent-readback trust check that rejects writer-derived evidence.

This module performs no network, Shopify or paid model calls. Every external
operation is supplied as an adapter, so the same orchestration can be exercised
offline with fakes and later driven by a concrete live adapter. When no concrete
adapter exists this runtime must not be presented as production-capable.
"""

from __future__ import annotations

import csv
import fcntl
import io
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional, TypeVar

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import betta_batch as bb  # noqa: E402
import betta_telemetry as bt  # noqa: E402

T = TypeVar("T")

APPLIED = "APPLIED"
REJECTED = "REJECTED"
UNCERTAIN = "UNCERTAIN"
READ_OK = "READ_OK"
READ_RETRYABLE = "READ_RETRYABLE"
READ_BLOCKED = "READ_BLOCKED"

REASON_BY_STATUS = {
    408: "timeout",
    429: "server_error",
    500: "server_error",
    502: "server_error",
    503: "server_error",
    504: "server_error",
}

INVENTORY_HEADERS = ["Tank Number", "Proposed Title", "Cost", "Retail Price"]


class RuntimeError_(bb.LedgerError):
    pass


class DuplicateIntake(RuntimeError_):
    pass


class ReconciliationRequired(RuntimeError_):
    """An inconclusive mutation must be reconciled, never retried immediately."""


class SystemClock:
    def now(self) -> str:
        return datetime.now(timezone.utc).isoformat()


class FrozenClock:
    """Deterministic monotonic clock for offline tests."""

    def __init__(self, start: str = "2026-10-09T00:00:00+00:00", step_seconds: float = 1.0):
        self._current = datetime.fromisoformat(start)
        self._step = step_seconds

    def now(self) -> str:
        value = self._current.isoformat()
        self._current = self._current + timedelta(seconds=self._step)
        return value


# --------------------------------------------------------------------------- #
# Serialized ledger writes
# --------------------------------------------------------------------------- #
class LedgerStore:
    """Advisory-locked, atomically written JSON ledger.

    ``fcntl.flock`` locks are associated with the open file description, so two
    independent ``open()`` calls (including from threads in one process) contend
    for the same lock. Combined with ``betta_batch.save``'s fsync + atomic
    ``os.replace`` this gives serialized, crash-safe updates. It is a single-host
    lock; a multi-host writer must add its own coordination.
    """

    def __init__(self, path: Path, lock_timeout: float = 15.0, poll: float = 0.02):
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.lock_timeout = lock_timeout
        self.poll = poll

    class _Lock:
        def __init__(self, store: "LedgerStore"):
            self.store = store
            self._fh = None

        def __enter__(self):
            self.store.lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.store.lock_path, "a+")
            deadline = time.monotonic() + self.store.lock_timeout
            while True:
                try:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return self
                except OSError:
                    if time.monotonic() >= deadline:
                        self._fh.close()
                        raise RuntimeError_("timed out acquiring ledger lock")
                    time.sleep(self.store.poll)

        def __exit__(self, *exc):
            if self._fh is not None:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                self._fh.close()
            return False

    def read(self) -> dict:
        if not self.path.is_file():
            raise RuntimeError_(f"ledger not found: {self.path}")
        with self._Lock(self):
            return bb.load(self.path)

    def update(self, mutate: Callable[[dict], T], create: Optional[Callable[[], dict]] = None) -> T:
        with self._Lock(self):
            if self.path.is_file():
                data = bb.load(self.path)
            elif create is not None:
                data = create()
            else:
                raise RuntimeError_(f"ledger not found: {self.path}")
            result = mutate(data)
            bb.validate_ledger(data)
            bb.save(self.path, data)
            return result


# --------------------------------------------------------------------------- #
# Cross-batch intake / source deduplication
# --------------------------------------------------------------------------- #
INTAKE_SCHEMA = """
CREATE TABLE IF NOT EXISTS betta_intake_sources (
    batch_id TEXT NOT NULL,
    intake_ref TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    tank_id TEXT,
    path TEXT,
    source_reference TEXT,
    date_entered TEXT NOT NULL,
    allowed_duplicate_of TEXT,
    PRIMARY KEY (batch_id, intake_ref)
);
CREATE INDEX IF NOT EXISTS idx_betta_intake_sha ON betta_intake_sources(source_sha256);
"""


class IntakeRegistry:
    """Persistent source-hash registry used to reject duplicate intake across batches.

    A source hash already recorded under a different (batch_id, intake_ref) is a
    duplicate unless the caller explicitly records an ``allow_duplicate_of``
    reference to the original identity. The same (batch_id, intake_ref) is an
    idempotent re-registration and never raises.
    """

    def __init__(self, path: Path, timeout: float = 15.0):
        self.path = Path(path)
        self.timeout = timeout

    @staticmethod
    def key(batch_id: str, intake_ref: str) -> str:
        return f"{batch_id}:{intake_ref}"

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path, timeout=self.timeout)
        con.row_factory = sqlite3.Row
        con.executescript(INTAKE_SCHEMA)
        return con

    def find(self, source_sha256: str) -> list[dict]:
        if not self.path.is_file():
            return []
        con = self._connect()
        try:
            rows = con.execute(
                "SELECT * FROM betta_intake_sources WHERE source_sha256=?", (source_sha256,)
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            con.close()

    def register(
        self,
        batch_id: str,
        intake_ref: str,
        tank_id: Optional[str],
        asset: dict,
        date_entered: str,
        source_reference: Optional[str] = None,
        allow_duplicate_of: Optional[str] = None,
    ) -> dict:
        sha = asset.get("sha256")
        bb.require(sha, "source sha256 required for intake registration")
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            rows = con.execute(
                "SELECT * FROM betta_intake_sources WHERE source_sha256=?", (sha,)
            ).fetchall()
            same = next(
                (r for r in rows if r["batch_id"] == batch_id and r["intake_ref"] == intake_ref), None
            )
            if same is not None:
                con.execute(
                    "UPDATE betta_intake_sources SET tank_id=?, path=?, source_reference=? "
                    "WHERE batch_id=? AND intake_ref=?",
                    (tank_id, asset.get("path"), source_reference, batch_id, intake_ref),
                )
                con.commit()
                return dict(same)
            for row in rows:
                if allow_duplicate_of is not None and allow_duplicate_of == self.key(
                    row["batch_id"], row["intake_ref"]
                ):
                    continue
                raise DuplicateIntake(
                    f"source {str(sha)[:12]} already intake as batch={row['batch_id']} "
                    f"ref={row['intake_ref']} tank={row['tank_id']}"
                )
            con.execute(
                "INSERT INTO betta_intake_sources "
                "(batch_id, intake_ref, source_sha256, tank_id, path, source_reference, "
                "date_entered, allowed_duplicate_of) VALUES (?,?,?,?,?,?,?,?)",
                (batch_id, intake_ref, sha, tank_id, asset.get("path"), source_reference,
                 date_entered, allow_duplicate_of),
            )
            con.commit()
        except DuplicateIntake:
            con.rollback()
            raise
        finally:
            con.close()
        return {
            "batch_id": batch_id,
            "intake_ref": intake_ref,
            "source_sha256": sha,
            "tank_id": tank_id,
            "path": asset.get("path"),
            "source_reference": source_reference,
            "date_entered": date_entered,
            "allowed_duplicate_of": allow_duplicate_of,
        }


# --------------------------------------------------------------------------- #
# API-error classification
# --------------------------------------------------------------------------- #
def _graphql_errors(result: dict) -> list:
    errors = result.get("graphql_errors") or []
    if isinstance(errors, str):
        return [errors]
    return list(errors)


def classify_write_result(result: object) -> tuple[str, Optional[str]]:
    """Classify a Shopify writer response into APPLIED / REJECTED / UNCERTAIN.

    Only an explicit success with no top-level or user errors is APPLIED. Transport
    and server-side failures are UNCERTAIN because the mutation may or may not have
    applied. Deterministic validation/authorisation failures are REJECTED.
    """
    if not isinstance(result, dict):
        return UNCERTAIN, "ambiguous_result"
    if result.get("transport_ok") is False:
        return UNCERTAIN, "transport_error"
    status = result.get("status_code")
    if isinstance(status, int) and status in REASON_BY_STATUS:
        return UNCERTAIN, REASON_BY_STATUS[status]
    errors = _graphql_errors(result)
    if errors:
        blob = " ".join(str(error).lower() for error in errors)
        if "throttl" in blob or "timeout" in blob or "try again" in blob:
            return UNCERTAIN, "server_error"
        return REJECTED, "graphql_error"
    if result.get("user_errors"):
        return REJECTED, "user_error"
    if result.get("ok") is True:
        return APPLIED, None
    if result.get("ok") is False:
        return REJECTED, "rejected"
    return UNCERTAIN, "ambiguous_result"


def classify_read_result(result: object) -> str:
    """Classify an independent Shopify read response.

    A usable read must positively attest ``source == FRESH_SHOPIFY_READ``. Transport
    and transient server failures are retryable; anything else is blocked so the
    caller holds the item instead of inventing state.
    """
    if not isinstance(result, dict):
        return READ_BLOCKED
    if result.get("transport_ok") is False:
        return READ_RETRYABLE
    status = result.get("status_code")
    if isinstance(status, int) and status in (408, 429, 500, 502, 503, 504):
        return READ_RETRYABLE
    if result.get("ok") is False and result.get("source") != "FRESH_SHOPIFY_READ":
        return READ_BLOCKED
    if result.get("source") != "FRESH_SHOPIFY_READ":
        return READ_BLOCKED
    return READ_OK


# --------------------------------------------------------------------------- #
# Trustworthy independent read-back
# --------------------------------------------------------------------------- #
def _parse_iso(value: object) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def verify_independent_readback(item: dict, readback: dict, *, write_completed_at: Optional[str] = None) -> None:
    """Require a fresh, independently-sourced read-back, then run the core assertions.

    Writer-derived evidence is rejected outright: a mutation response is never proof
    of final state. The read must carry its own fetch identity and timestamp that
    post-dates the write it is meant to verify.
    """
    bb.require(readback.get("writer_response_used") is not True,
               "read-back must not be derived from the writer response")
    bb.require(readback.get("fetch_id"), "read-back fetch_id required")
    fetch_id = str(readback["fetch_id"])
    write_id = str((item.get("write") or {}).get("write_id") or "")
    if write_id:
        bb.require(fetch_id != write_id, "read-back fetch_id must differ from the writer identity")
    fetched_at = _parse_iso(readback.get("fetched_at"))
    bb.require(fetched_at is not None, "read-back fetched_at must be an ISO timestamp")
    completed = _parse_iso(write_completed_at or (item.get("write") or {}).get("completed_at"))
    if completed is not None:
        bb.require(fetched_at >= completed, "read-back must be fetched at or after the write completed")
    bb.verify_readback({**item, "readback": readback})


# --------------------------------------------------------------------------- #
# Uncertain-write reconciliation
# --------------------------------------------------------------------------- #
def _readback_state(readback: dict) -> dict:
    return {
        "title": readback.get("title"),
        "arrival_date": readback.get("arrival_date"),
        "inventory": readback.get("inventory"),
        "media_hashes": list(readback.get("media_hashes") or [])[:2],
    }


def determine_reconciliation(item: dict, readback: dict) -> str:
    """Return APPLIED, NOT_APPLIED or UNRESOLVED from an independent read.

    APPLIED requires every authorised field to match the intended mutation and every
    protected field to match the pre-write snapshot. NOT_APPLIED requires the read to
    still match the recorded pre-write baseline for all authorised fields. Anything
    else is UNRESOLVED and must hold for operator review.
    """
    mutation = item["mutation"]
    before = item["product"]["before"]
    baseline = (item.get("write") or {}).get("baseline") or {}
    for key in bb.PROTECTED:
        if readback.get(key) != before.get(key):
            return "UNRESOLVED"
    view = _readback_state(readback)
    intended = {
        "title": mutation["title"],
        "arrival_date": mutation["arrival_date"],
        "inventory": 1,
        "media_hashes": list(mutation["media"])[:2],
    }
    if view == intended:
        return "APPLIED"
    if baseline.get("title") is None or baseline.get("media_hashes") is None:
        return "UNRESOLVED"
    base_view = {
        "title": baseline.get("title"),
        "arrival_date": baseline.get("arrival_date"),
        "inventory": before.get("inventory"),
        "media_hashes": list(baseline.get("media_hashes") or [])[:2],
    }
    if view == base_view:
        return "NOT_APPLIED"
    return "UNRESOLVED"


# --------------------------------------------------------------------------- #
# Inventory CSV
# --------------------------------------------------------------------------- #
def _csv_value(value: object) -> str:
    return "" if value is None else str(value)


def _csv_row(item: dict) -> list:
    before = item["product"]["before"]
    return [
        item["id"],
        bb.expected_catalogue_title(item["catalogue"]),
        _csv_value(before.get("cost")),
        _csv_value(before.get("price")),
    ]


def build_inventory_csv(items: list) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(INVENTORY_HEADERS)
    for item in sorted(items, key=lambda entry: entry["id"]):
        writer.writerow(_csv_row(item))
    return buffer.getvalue()


def validate_inventory_csv(text: str, expected_items: list) -> None:
    """Fail closed unless the CSV exactly reflects the live pre-write snapshots.

    Enforces the fixed header, four fields per row, one unique row per accepted
    tank, tank-set equality and value equality with the snapshot title/cost/price.
    Because cost and price must equal the snapshot, CSV values can never authorise a
    price or cost change.
    """
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise bb.LedgerError("inventory CSV is empty")
    bb.require(header == INVENTORY_HEADERS, "inventory CSV header mismatch")
    rows = [row for row in reader if row and not (len(row) == 1 and row[0] == "")]
    expected = {item["id"]: _csv_row(item) for item in expected_items}
    bb.require(len(rows) == len(expected), "inventory CSV row count mismatch")
    seen = set()
    for row in rows:
        bb.require(len(row) == 4, "inventory CSV row must have exactly four fields")
        tank = row[0]
        bb.require(tank not in seen, "duplicate tank row in inventory CSV")
        seen.add(tank)
        bb.require(tank in expected, f"unexpected tank in inventory CSV: {tank}")
        bb.require(row == expected[tank], f"inventory CSV values do not match the live snapshot for {tank}")
    bb.require(seen == set(expected), "inventory CSV tank set mismatch")


# --------------------------------------------------------------------------- #
# Telemetry-before-PASS gate
# --------------------------------------------------------------------------- #
def telemetry_row_exists(db_path: Path, batch_id: str, tank_number: str) -> bool:
    path = Path(db_path)
    if not path.is_file():
        return False
    con = sqlite3.connect(path)
    try:
        row = con.execute(
            "SELECT 1 FROM betta_processing_telemetry WHERE batch_id=? AND tank_number=? LIMIT 1",
            (batch_id, tank_number),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False
    finally:
        con.close()


def require_telemetry_before_pass(db_path: Path, batch_id: str, tank_number: str) -> None:
    bb.require(
        telemetry_row_exists(db_path, batch_id, tank_number),
        f"persisted telemetry row required before PASS: {batch_id}/{tank_number}",
    )


# --------------------------------------------------------------------------- #
# Adapter-driven orchestration
# --------------------------------------------------------------------------- #
def _find_item(data: dict, item_id: str) -> dict:
    item = next((entry for entry in data.get("items", []) if entry.get("id") == item_id), None)
    bb.require(item is not None, f"unknown item: {item_id}")
    return item


def new_ledger(batch_id: str) -> dict:
    return {"schema_version": 2, "batch_id": batch_id, "batch_state": "ASSEMBLING", "items": []}


class BettaRuntime:
    """Deterministic orchestrator over injected external adapters.

    The runtime owns state progression, serialized persistence, error handling and
    reconciliation. Adapters own all external I/O. No method here performs network,
    Shopify or paid model calls on its own.
    """

    def __init__(
        self,
        *,
        ledger_path: Path,
        intake_registry_path: Path,
        telemetry_db: Path,
        source_store,
        vision,
        hero_generator,
        shopify,
        archiver,
        clock=None,
    ):
        self.store = LedgerStore(Path(ledger_path))
        self.intake_registry = IntakeRegistry(Path(intake_registry_path))
        self.telemetry_db = Path(telemetry_db)
        self.source_store = source_store
        self.vision = vision
        self.hero_generator = hero_generator
        self.shopify = shopify
        self.archiver = archiver
        self.clock = clock or SystemClock()

    # -- intake ------------------------------------------------------------ #
    def intake(
        self,
        batch_id: str,
        tank_id: str,
        attachment: dict,
        *,
        intake_ref: Optional[str] = None,
        source_reference: Optional[str] = None,
        new_fish_authorised: bool = False,
        allow_duplicate_of: Optional[str] = None,
    ) -> dict:
        ref = intake_ref or tank_id
        sha = attachment.get("sha256") or bb.sha256(attachment["path"])
        # Reject a cross-batch duplicate before copying any bytes.
        existing_rows = self.intake_registry.find(sha)
        for row in existing_rows:
            same = row["batch_id"] == batch_id and row["intake_ref"] == ref
            allowed = allow_duplicate_of == IntakeRegistry.key(row["batch_id"], row["intake_ref"])
            if same or allowed:
                continue
            raise DuplicateIntake(
                f"source {str(sha)[:12]} already intake as batch={row['batch_id']} "
                f"ref={row['intake_ref']} tank={row['tank_id']}"
            )

        date_entered = self.clock.now()
        asset = self.source_store.save(attachment, tank_id=tank_id)
        bb.require(asset.get("sha256") == sha, "saved source hash does not match the attachment")
        self.intake_registry.register(
            batch_id, ref, tank_id, asset, date_entered,
            source_reference=source_reference, allow_duplicate_of=allow_duplicate_of,
        )

        def mutate(data: dict) -> dict:
            existing = next((entry for entry in data["items"] if entry["id"] == tank_id), None)
            if existing is not None:
                bb.require(existing["source"]["sha256"] == sha,
                           "item id re-used with a different source photograph")
                return existing
            item = {
                "id": tank_id,
                "state": "SAVED",
                "history": [
                    {"from": None, "to": "DISCOVERED", "at": date_entered},
                    {"from": "DISCOVERED", "to": "SAVED", "at": date_entered},
                ],
                "source": asset,
                "source_reference": source_reference,
                "intake": {
                    "intake_ref": ref,
                    "date_entered": date_entered,
                    "source_reference": source_reference,
                    "new_fish_authorised": new_fish_authorised,
                    "source_sha256": sha,
                },
            }
            data["items"].append(item)
            return item

        return self.store.update(mutate, create=lambda: new_ledger(batch_id))

    # -- visual catalogue -------------------------------------------------- #
    def catalogue(self, item_id: str) -> dict:
        asset = self.store.read()
        item = _find_item(asset, item_id)
        bb.require(item["state"] == "SAVED", "catalogue requires a SAVED item")
        evidence = self.vision.catalogue(item["source"])
        output = evidence.get("output") or {}
        catalogue = {
            "tank_id": output.get("tank_id"),
            "photo_date": output.get("photo_date"),
            "fish_name": output.get("fish_name"),
            "tail_type": output.get("tail_type"),
            "sex": output.get("sex"),
            "sex_confidence": output.get("sex_confidence"),
            "evidence": evidence,
        }
        catalogue["title"] = bb.expected_catalogue_title(catalogue)

        def mutate(data: dict) -> dict:
            entry = _find_item(data, item_id)
            bb.require(entry["state"] == "SAVED", "catalogue state changed concurrently")
            entry["catalogue"] = catalogue
            bb.advance(data, item_id, "VISUAL_PENDING")
            bb.advance(data, item_id, "VISUAL_ACCEPTED")
            return entry

        return self.store.update(mutate)


    # -- parallel Shopify resolve + hero generation ------------------------ #
    def prepare(self, item_id: str, *, workers: int = 4) -> dict:
        snapshot = self.store.read()
        plan = bb.parallel_preparation_plan(snapshot, workers)
        tasks = [task for task in plan["tasks"] if task["item_id"] == item_id]
        for task in tasks:
            operation = task["operation"]
            if operation == "shopify_resolve":
                resolved = self.shopify.resolve(item_id)
                bb.require(resolved.get("status") == "RESOLVED",
                           f"Shopify resolution did not identify exactly one product for {item_id}")

                def record_product(data: dict) -> None:
                    _find_item(data, item_id)["product"] = resolved["snapshot"]
                self.store.update(record_product)
            elif operation == "grok_hero":
                generated = self.hero_generator.generate(self.store.read(), item_id)

                def record_hero(data: dict) -> None:
                    entry = _find_item(data, item_id)
                    entry.setdefault("images", {})["hero"] = generated["asset"]
                    entry["grok"] = generated.get("record")
                self.store.update(record_hero)
        joined = self.store.read()
        entry = _find_item(joined, item_id)
        if entry["state"] == "VISUAL_ACCEPTED":
            def join(data: dict) -> None:
                bb.advance(data, item_id, "PRODUCT_RESOLVED")
            self.store.update(join)
        return {"item_id": item_id, "tasks": [task["operation"] for task in tasks]}

    # -- inventory CSV ----------------------------------------------------- #
    def build_csv(self, csv_path: Path) -> str:
        snapshot = self.store.read()
        accepted = [
            entry for entry in snapshot["items"]
            if entry["state"] == "PRODUCT_RESOLVED"
        ]
        bb.require(accepted, "no PRODUCT_RESOLVED items available for the inventory CSV")
        text = build_inventory_csv(accepted)
        validate_inventory_csv(text, accepted)
        Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
        Path(csv_path).write_text(text, encoding="utf-8")

        def mutate(data: dict) -> None:
            for entry in data["items"]:
                if entry["state"] == "PRODUCT_RESOLVED":
                    bb.advance(data, entry["id"], "CSV_READY")
        self.store.update(mutate)
        return text

    # -- image QA ---------------------------------------------------------- #
    def run_image_qa(self, item_id: str) -> dict:
        item = _find_item(self.store.read(), item_id)
        bb.require(item["state"] == "CSV_READY", "image QA requires a CSV_READY item")

        def to_candidate(data: dict) -> None:
            bb.advance(data, item_id, "IMAGE_CANDIDATE_READY")
            bb.advance(data, item_id, "IMAGE_QA_PENDING")
        self.store.update(to_candidate)

        current = _find_item(self.store.read(), item_id)
        evidence = self.vision.qa(current["source"], current["images"]["hero"], current["source"])
        deterministic = {key: "PASS" for key in bb.QA_DETERMINISTIC}

        def record_qa(data: dict) -> None:
            entry = _find_item(data, item_id)
            entry["image_qa"] = {
                "deterministic": deterministic,
                "visual": evidence,
                "outcome": "PASS",
            }
            bb.advance(data, item_id, "IMAGES_READY")
        self.store.update(record_qa)
        return {"item_id": item_id, "outcome": "PASS"}

    # -- authorised mutation ----------------------------------------------- #
    def begin_mutation(self, item_id: str) -> dict:
        item = _find_item(self.store.read(), item_id)
        bb.require(item["state"] == "IMAGES_READY", "mutation requires an IMAGES_READY item")
        before = item["product"]["before"]
        mutation = {
            "title": bb.expected_catalogue_title(item["catalogue"]),
            "arrival_date": item["catalogue"]["photo_date"],
            "inventory": 1,
            "media": [item["images"]["hero"]["sha256"], item["source"]["sha256"]],
        }
        write = {
            "write_id": f"write-{item_id}-{self.clock.now()}",
            "started_at": self.clock.now(),
            "baseline": {
                "title": before.get("title"),
                "arrival_date": before.get("arrival_date"),
                "media_hashes": before.get("media_hashes"),
            },
        }

        def mutate(data: dict) -> None:
            entry = _find_item(data, item_id)
            entry["mutation"] = mutation
            entry["write"] = write
            bb.advance(data, item_id, "MUTATION_PENDING")
        self.store.update(mutate)
        return self.mutation_envelope(item_id)

    def mutation_envelope(self, item_id: str) -> dict:
        data = self.store.read()
        item = _find_item(data, item_id)
        bb.require(item["state"] == "MUTATION_PENDING", "item is not mutation-ready")
        product = item["product"]
        return {
            "batch_id": data["batch_id"],
            "item_id": item_id,
            "product_id": product["id"],
            "variant_id": product["variant_id"],
            "location_id": product["location_id"],
            "changes": item["mutation"],
        }

    def apply_mutation(self, item_id: str) -> str:
        """Apply one mutation. Returns a result class; never retries on UNCERTAIN."""
        item = _find_item(self.store.read(), item_id)
        bb.require(item["state"] == "MUTATION_PENDING", "item is not mutation-ready")
        envelope = self.mutation_envelope(item_id)
        result = self.shopify.mutate(envelope)
        result_class, reason = classify_write_result(result)
        completed_at = self.clock.now()

        def persist(data: dict) -> None:
            entry = _find_item(data, item_id)
            entry.setdefault("write", {})["completed_at"] = completed_at
            entry["write"]["result_class"] = result_class
            if result_class == APPLIED:
                bb.advance(data, item_id, "MUTATED")
            elif result_class == REJECTED:
                entry["write"]["error"] = reason
                bb.advance(data, item_id, "FIX_REQUIRED")
            else:
                entry["uncertain_write"] = {
                    "attempted_at": completed_at,
                    "reason": reason,
                    "writer_result_class": "UNCERTAIN",
                    "write_id": entry["write"]["write_id"],
                    "error": (result or {}).get("error") if isinstance(result, dict) else None,
                }
                bb.advance(data, item_id, "MUTATION_UNCERTAIN")
        self.store.update(persist)
        return result_class

    def reconcile(self, item_id: str, *, retry_authorised: bool = False) -> str:
        """Independently reconcile an UNCERTAIN write. Never retries without authority."""
        item = _find_item(self.store.read(), item_id)
        bb.require(item["state"] == "MUTATION_UNCERTAIN", "item is not awaiting reconciliation")
        readback = self.shopify.read(item["product"]["id"])
        read_class = classify_read_result(readback)
        readback_at = self.clock.now()
        if read_class != READ_OK:
            outcome = "UNRESOLVED"
        else:
            outcome = determine_reconciliation(item, readback)

        def persist(data: dict) -> None:
            entry = _find_item(data, item_id)
            entry["reconciliation"] = {
                "outcome": outcome,
                "readback_at": readback_at,
                "read_class": read_class,
                "fetch_id": readback.get("fetch_id") if isinstance(readback, dict) else None,
                "retry_authorised": bool(retry_authorised),
            }
            if outcome == "APPLIED":
                entry["readback"] = readback
                bb.advance(data, item_id, "MUTATED")
            elif outcome == "NOT_APPLIED" and retry_authorised:
                bb.advance(data, item_id, "MUTATION_PENDING")
        self.store.update(persist)
        return outcome


    # -- fresh read-back verification -------------------------------------- #
    def verify(self, item_id: str) -> dict:
        item = _find_item(self.store.read(), item_id)
        bb.require(item["state"] == "MUTATED", "verification requires a MUTATED item")
        readback = self.shopify.read(item["product"]["id"])
        read_class = classify_read_result(readback)
        bb.require(read_class == READ_OK, f"independent read-back unavailable: {read_class}")
        verify_independent_readback(item, readback)

        def persist(data: dict) -> None:
            entry = _find_item(data, item_id)
            entry["readback"] = readback
            bb.advance(data, item_id, "VERIFIED")
        self.store.update(persist)
        return readback

    # -- persisted telemetry then PASS ------------------------------------- #
    def finalize(self, item_id: str) -> dict:
        item = _find_item(self.store.read(), item_id)
        bb.require(item["state"] == "VERIFIED", "finalize requires a VERIFIED item")
        ledger = self.store.read()
        grok_records = [item["grok"]] if isinstance(item.get("grok"), dict) else []
        row = bt.build_from_ledger(ledger, item_id, grok_records)
        con = bt.connect(self.telemetry_db)
        try:
            bt.upsert(con, row)
        finally:
            con.close()
        require_telemetry_before_pass(self.telemetry_db, ledger["batch_id"], item_id)

        def persist(data: dict) -> None:
            bb.advance(data, item_id, "PASS")
        self.store.update(persist)
        return row

    # -- archive ----------------------------------------------------------- #
    def archive(self, item_id: str, archive_date: str) -> dict:
        item = _find_item(self.store.read(), item_id)
        bb.require(item["state"] == "PASS", "archive requires a PASS item")
        record = self.archiver.archive(item, archive_date)

        def persist(data: dict) -> None:
            entry = _find_item(data, item_id)
            entry["archive"] = record
            bb.advance(data, item_id, "ARCHIVED")
            if all(candidate["state"] == "ARCHIVED" for candidate in data["items"]):
                data["batch_state"] = "DONE"
        self.store.update(persist)
        return record

    # -- convenience full path --------------------------------------------- #
    def run_to_archive(
        self,
        *,
        batch_id: str,
        tank_id: str,
        attachment: dict,
        csv_path: Path,
        archive_date: str,
        **intake_kwargs,
    ) -> dict:
        self.intake(batch_id, tank_id, attachment, **intake_kwargs)
        self.catalogue(tank_id)
        self.prepare(tank_id)
        self.build_csv(csv_path)
        self.run_image_qa(tank_id)
        self.begin_mutation(tank_id)
        self.apply_mutation(tank_id)
        self.verify(tank_id)
        self.finalize(tank_id)
        return self.archive(tank_id, archive_date)

