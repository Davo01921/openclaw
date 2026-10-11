#!/usr/bin/env python3
"""Paid-generation budget enforcement for Betta V2.2.

Enforces the owner-approved limits before any paid Grok/xAI request, with a
crash-safe, concurrency-safe ledger. Fails closed when a cost cannot be
established. Unknown settled costs are charged at the conservative reservation,
never treated as zero.

Approved defaults: 2 attempts/fish (1 initial + 1 retry), USD 0.14/fish,
USD 2.80/batch, max 20 fish/batch, USD 0.07 fallback per generation.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import secrets
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCHEMA = "nta-betta-generation-budget-v1"

DEFAULT_LIMITS = {
    "per_fish_usd": 0.14,
    "per_batch_usd": 2.80,
    "max_attempts_per_fish": 2,
    "max_retries_per_fish": 1,
    "max_fish_per_batch": 20,
    "fallback_cost_usd": 0.07,
}
MONEY_TOLERANCE = 1e-9


class BudgetError(RuntimeError):
    pass


def _finite_number(value, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BudgetError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise BudgetError(f"{label} must be finite")
    if positive and result <= 0:
        raise BudgetError(f"{label} must be positive")
    if not positive and result < 0:
        raise BudgetError(f"{label} must be non-negative")
    return result


def _positive_int(value, label: str, *, allow_zero: bool = False) -> int:
    if type(value) is not int or value < (0 if allow_zero else 1):
        qualifier = "non-negative" if allow_zero else "positive"
        raise BudgetError(f"{label} must be a {qualifier} integer")
    return value


def _validated_limits(overrides: Optional[dict]) -> dict:
    if overrides is not None and not isinstance(overrides, dict):
        raise BudgetError("limits must be an object")
    overrides = overrides or {}
    unknown = set(overrides) - set(DEFAULT_LIMITS)
    if unknown:
        raise BudgetError("unsupported budget limits: " + ", ".join(sorted(unknown)))
    limits = {**DEFAULT_LIMITS, **overrides}
    if "max_attempts_per_fish" in overrides and "max_retries_per_fish" not in overrides:
        attempts = overrides["max_attempts_per_fish"]
        if type(attempts) is int and attempts >= 1:
            limits["max_retries_per_fish"] = min(
                DEFAULT_LIMITS["max_retries_per_fish"], attempts - 1,
            )
    if "per_fish_usd" in overrides and "fallback_cost_usd" not in overrides:
        per_fish = overrides["per_fish_usd"]
        if (isinstance(per_fish, (int, float)) and not isinstance(per_fish, bool) and
                math.isfinite(float(per_fish)) and
                float(per_fish) + MONEY_TOLERANCE < DEFAULT_LIMITS["fallback_cost_usd"]):
            limits["fallback_cost_usd"] = None

    for key in ("per_fish_usd", "per_batch_usd"):
        value = _finite_number(limits[key], key, positive=True)
        if value > DEFAULT_LIMITS[key] + MONEY_TOLERANCE:
            raise BudgetError(f"{key} exceeds the approved hard cap")
        limits[key] = value
    for key in ("max_attempts_per_fish", "max_fish_per_batch"):
        value = _positive_int(limits[key], key)
        if value > DEFAULT_LIMITS[key]:
            raise BudgetError(f"{key} exceeds the approved hard cap")
        limits[key] = value
    retries = _positive_int(
        limits["max_retries_per_fish"], "max_retries_per_fish", allow_zero=True,
    )
    if (retries > DEFAULT_LIMITS["max_retries_per_fish"] or
            retries > limits["max_attempts_per_fish"] - 1):
        raise BudgetError("max_retries_per_fish exceeds the approved attempt ceiling")
    limits["max_retries_per_fish"] = retries

    fallback = limits.get("fallback_cost_usd")
    if fallback is not None:
        fallback = _finite_number(fallback, "fallback_cost_usd", positive=True)
        if fallback + MONEY_TOLERANCE < DEFAULT_LIMITS["fallback_cost_usd"]:
            raise BudgetError("fallback_cost_usd cannot be below the conservative 0.07 floor")
        if fallback > limits["per_fish_usd"] + MONEY_TOLERANCE:
            raise BudgetError("fallback_cost_usd cannot exceed per_fish_usd")
        limits["fallback_cost_usd"] = fallback
    return limits


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


class GenerationBudget:
    def __init__(self, path: Path, *, batch_id: str = "", limits: Optional[dict] = None,
                 lock_timeout: float = 15.0):
        self.path = Path(path)
        if not isinstance(batch_id, str):
            raise BudgetError("batch_id must be a string")
        self.batch_id = batch_id
        self.limits = _validated_limits(limits)
        self.lock_timeout = _finite_number(lock_timeout, "lock_timeout", positive=True)

    # -- persistence ------------------------------------------------------- #
    def _blank(self) -> dict:
        return {"schema": SCHEMA, "batch_id": self.batch_id, "limits": self.limits,
                "fish": {}, "reservations": {}, "batch_spent": 0.0,
                "batch_reserved": 0.0, "blocked": False, "blocked_reason": None}

    def _load(self) -> dict:
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise BudgetError(f"budget ledger is unreadable: {exc}") from exc
            self._validate_ledger(data)
            return data
        data = self._blank()
        self._validate_ledger(data)
        return data

    def _validate_ledger(self, data: dict) -> None:
        if not isinstance(data, dict) or data.get("schema") != SCHEMA:
            raise BudgetError("unsupported budget schema")
        if data.get("batch_id") != self.batch_id:
            raise BudgetError("budget ledger batch_id differs from the requested batch")
        persisted_raw = data.get("limits")
        if (not isinstance(persisted_raw, dict) or
                set(persisted_raw) != set(DEFAULT_LIMITS)):
            raise BudgetError("persisted budget limits are missing or structurally invalid")
        try:
            persisted_limits = _validated_limits(persisted_raw)
        except BudgetError as exc:
            raise BudgetError(f"invalid persisted budget limits: {exc}") from exc
        if persisted_limits != self.limits:
            raise BudgetError("budget ledger limits differ from the requested limits")

        fish = data.get("fish")
        reservations = data.get("reservations")
        if not isinstance(fish, dict) or not isinstance(reservations, dict):
            raise BudgetError("budget ledger fish and reservations must be objects")
        if len(fish) > self.limits["max_fish_per_batch"]:
            raise BudgetError("budget ledger exceeds max_fish_per_batch")
        batch_spent = _finite_number(data.get("batch_spent"), "batch_spent")
        batch_reserved = _finite_number(data.get("batch_reserved"), "batch_reserved")
        blocked = data.setdefault("blocked", False)
        data.setdefault("blocked_reason", None)
        if not isinstance(blocked, bool):
            raise BudgetError("budget ledger blocked flag must be boolean")
        if blocked and not isinstance(data.get("blocked_reason"), str):
            raise BudgetError("blocked budget ledger requires a reason")
        if not blocked and data.get("blocked_reason") is not None:
            raise BudgetError("unblocked budget ledger cannot carry a blocked reason")

        listed_reservations: dict[str, str] = {}
        fish_spent = 0.0
        fish_reserved = 0.0
        for tank, entry in fish.items():
            if not isinstance(tank, str) or not tank or not isinstance(entry, dict):
                raise BudgetError("budget ledger contains an invalid fish entry")
            attempts = _positive_int(entry.get("attempts"), f"{tank}.attempts", allow_zero=True)
            if attempts > self.limits["max_attempts_per_fish"]:
                raise BudgetError(f"{tank}.attempts exceeds the approved limit")
            spent = _finite_number(entry.get("spent"), f"{tank}.spent")
            reserved = _finite_number(entry.get("reserved"), f"{tank}.reserved")
            ids = entry.get("reservations")
            if (not isinstance(ids, list) or
                    any(not isinstance(rid, str) or not rid for rid in ids) or
                    len(ids) != len(set(ids))):
                raise BudgetError(f"{tank}.reservations must contain unique IDs")
            for rid in ids:
                if rid in listed_reservations:
                    raise BudgetError(f"reservation {rid} is listed for multiple fish")
                listed_reservations[rid] = tank
            fish_spent += spent
            fish_reserved += reserved

        calculated_spent = 0.0
        calculated_reserved = 0.0
        violations = []
        counted_attempts = {tank: 0 for tank in fish}
        for rid, reservation in reservations.items():
            if not isinstance(rid, str) or not rid or not isinstance(reservation, dict):
                raise BudgetError("budget ledger contains an invalid reservation")
            tank = reservation.get("tank")
            if tank not in fish or listed_reservations.get(rid) != tank:
                raise BudgetError(f"reservation {rid} is not bound to exactly one registered fish")
            amount = _finite_number(reservation.get("amount"), f"{rid}.amount", positive=True)
            if amount > self.limits["per_fish_usd"] + MONEY_TOLERANCE:
                raise BudgetError(f"reservation {rid} exceeds per_fish_usd")
            settled = reservation.get("settled")
            if not isinstance(settled, bool):
                raise BudgetError(f"{rid}.settled must be boolean")
            violation = reservation.get("budget_violation")
            if violation is not None:
                if not settled or not isinstance(violation, str) or not violation:
                    raise BudgetError(f"{rid}.budget_violation is invalid")
                violations.append(violation)
            if settled:
                actual = _finite_number(reservation.get("actual"), f"{rid}.actual")
                if (actual > amount + MONEY_TOLERANCE) != bool(violation):
                    raise BudgetError(
                        f"{rid} provider overage and budget_violation evidence disagree"
                    )
                calculated_spent += actual
            else:
                if reservation.get("actual") is not None:
                    raise BudgetError(f"unsettled reservation {rid} cannot have actual cost")
                calculated_reserved += amount
            if "reported" in reservation and not isinstance(reservation["reported"], bool):
                raise BudgetError(f"{rid}.reported must be boolean")
            released = reservation.get("released")
            if released is not None:
                if (not settled or not isinstance(released, str) or not released or
                        reservation.get("actual") != 0.0 or violation):
                    raise BudgetError(f"{rid}.released evidence is invalid")
            else:
                counted_attempts[tank] += 1

        if set(listed_reservations) != set(reservations):
            raise BudgetError("fish reservation lists differ from the reservation ledger")
        for tank, expected_attempts in counted_attempts.items():
            if fish[tank]["attempts"] != expected_attempts:
                raise BudgetError(f"{tank}.attempts differs from reservation evidence")
        for label, actual, calculated in (
            ("fish spent total", fish_spent, calculated_spent),
            ("fish reserved total", fish_reserved, calculated_reserved),
            ("batch_spent", batch_spent, calculated_spent),
            ("batch_reserved", batch_reserved, calculated_reserved),
        ):
            if not math.isclose(actual, calculated, rel_tol=0.0, abs_tol=MONEY_TOLERANCE):
                raise BudgetError(f"budget ledger {label} is inconsistent")
        if blocked != bool(violations):
            raise BudgetError("budget ledger blocked state differs from recorded violations")
        if violations and data.get("blocked_reason") not in violations:
            raise BudgetError("budget ledger blocked reason lacks reservation evidence")
        if not blocked:
            if batch_spent + batch_reserved > self.limits["per_batch_usd"] + MONEY_TOLERANCE:
                raise BudgetError("budget ledger exceeds per_batch_usd without a block")
            for tank, entry in fish.items():
                if (float(entry["spent"]) + float(entry["reserved"]) >
                        self.limits["per_fish_usd"] + MONEY_TOLERANCE):
                    raise BudgetError(f"{tank} exceeds per_fish_usd without a block")

    @staticmethod
    def _ensure_not_blocked(data: dict) -> None:
        if data.get("blocked") is True:
            raise BudgetError(f"budget ledger is blocked: {data.get('blocked_reason')}")

    class _Lock:
        def __init__(self, budget: "GenerationBudget"):
            self.budget = budget
            self._fh = None

        def __enter__(self):
            self.budget.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.budget.path.with_suffix(".lock"), "a+")
            deadline = time.monotonic() + self.budget.lock_timeout
            while True:
                try:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return self
                except OSError:
                    if time.monotonic() >= deadline:
                        self._fh.close()
                        raise BudgetError("timed out acquiring budget lock")
                    time.sleep(0.02)

        def __exit__(self, *exc):
            if self._fh is not None:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                self._fh.close()
            return False

    # -- helpers ----------------------------------------------------------- #
    def _committed(self, data: dict, tank: str) -> float:
        entry = data["fish"].get(tank, {})
        return float(entry.get("spent", 0.0)) + float(entry.get("reserved", 0.0))

    def register_fish(self, tank: str) -> None:
        with self._Lock(self):
            data = self._load()
            self._ensure_not_blocked(data)
            if not isinstance(tank, str) or not tank:
                raise BudgetError("tank must be a non-empty string")
            if tank in data["fish"]:
                return
            if len(data["fish"]) >= self.limits["max_fish_per_batch"]:
                raise BudgetError(f"batch exceeds max_fish_per_batch={self.limits['max_fish_per_batch']}")
            data["fish"][tank] = {"attempts": 0, "spent": 0.0, "reserved": 0.0, "reservations": []}
            self._validate_ledger(data)
            _atomic_write(self.path, data)

    def can_attempt(self, tank: str) -> tuple[bool, Optional[str]]:
        data = self._load()
        if data.get("blocked") is True:
            return False, f"budget ledger is blocked: {data.get('blocked_reason')}"
        entry = data["fish"].get(tank)
        if entry is None:
            return False, "fish not registered"
        if entry["attempts"] >= self.limits["max_attempts_per_fish"]:
            return False, f"max attempts reached ({self.limits['max_attempts_per_fish']})"
        return True, None

    def reserve(self, tank: str, amount: Optional[float] = None) -> str:
        """Reserve cost for one attempt. Fails closed on unknown cost."""
        with self._Lock(self):
            data = self._load()
            self._ensure_not_blocked(data)
            entry = data["fish"].get(tank)
            if entry is None:
                raise BudgetError("fish not registered")
            if entry["attempts"] >= self.limits["max_attempts_per_fish"]:
                raise BudgetError(f"attempts exhausted for {tank}")
            if amount is None:
                amount = self.limits.get("fallback_cost_usd")
            if amount is None:
                raise BudgetError("no cost available and no fallback; failing closed")
            amount = _finite_number(amount, "reservation amount", positive=True)
            if self._committed(data, tank) + amount > self.limits["per_fish_usd"] + 1e-9:
                raise BudgetError(f"per-fish budget exceeded for {tank}")
            if data["batch_spent"] + data["batch_reserved"] + amount > self.limits["per_batch_usd"] + 1e-9:
                raise BudgetError("per-batch budget exceeded")
            rid = f"res-{secrets.token_hex(6)}"
            entry["attempts"] += 1
            entry["reserved"] = float(entry.get("reserved", 0.0)) + amount
            entry["reservations"].append(rid)
            data["reservations"][rid] = {"tank": tank, "amount": amount, "settled": False,
                                          "actual": None, "at": _now()}
            data["batch_reserved"] = float(data["batch_reserved"]) + amount
            self._validate_ledger(data)
            _atomic_write(self.path, data)
            return rid

    def settle(self, rid: str, actual_cost: Optional[float], *, reported: bool = True) -> float:
        """Reconcile a reservation. Unknown cost settles at the reserved amount."""
        with self._Lock(self):
            data = self._load()
            reservation = data["reservations"].get(rid)
            if reservation is None:
                raise BudgetError("unknown reservation")
            if reservation["settled"]:
                if reservation.get("budget_violation"):
                    raise BudgetError(reservation["budget_violation"])
                actual = reservation.get("actual")
                return float(reservation["amount"] if actual is None else actual)
            tank = reservation["tank"]
            amount = float(reservation["amount"])
            charged = amount if actual_cost is None else _finite_number(
                actual_cost, "actual cost",
            )
            entry = data["fish"][tank]
            entry["reserved"] = max(0.0, float(entry.get("reserved", 0.0)) - amount)
            entry["spent"] = float(entry.get("spent", 0.0)) + charged
            data["batch_reserved"] = max(0.0, float(data["batch_reserved"]) - amount)
            data["batch_spent"] = float(data["batch_spent"]) + charged
            reservation.update({"settled": True, "actual": charged, "reported": reported})
            violations = []
            if charged > amount + MONEY_TOLERANCE:
                violations.append(
                    f"provider actual cost {charged:.6f} exceeded reservation {amount:.6f}"
                )
            if entry["spent"] + entry["reserved"] > self.limits["per_fish_usd"] + MONEY_TOLERANCE:
                violations.append(f"actual cost exceeded per-fish budget for {tank}")
            if (data["batch_spent"] + data["batch_reserved"] >
                    self.limits["per_batch_usd"] + MONEY_TOLERANCE):
                violations.append("actual cost exceeded per-batch budget")
            violation = "; ".join(violations) if violations else None
            if violation:
                reservation["budget_violation"] = violation
                data["blocked"] = True
                data["blocked_reason"] = violation
            self._validate_ledger(data)
            _atomic_write(self.path, data)
            if violation:
                raise BudgetError(violation)
            return charged

    def release(self, rid: str, reason: str = "not applied") -> None:
        """Release a reservation when the request provably did not incur cost."""
        with self._Lock(self):
            data = self._load()
            reservation = data["reservations"].get(rid)
            if reservation is None or reservation["settled"]:
                return
            tank = reservation["tank"]
            amount = float(reservation["amount"])
            data["fish"][tank]["reserved"] = max(0.0, float(data["fish"][tank].get("reserved", 0.0)) - amount)
            data["fish"][tank]["attempts"] = max(0, data["fish"][tank]["attempts"] - 1)
            data["batch_reserved"] = max(0.0, float(data["batch_reserved"]) - amount)
            reservation.update({"settled": True, "actual": 0.0, "released": reason})
            self._validate_ledger(data)
            _atomic_write(self.path, data)

    def summary(self) -> dict:
        data = self._load()
        return {"batch_id": data.get("batch_id"), "limits": data["limits"],
                "batch_spent": round(data["batch_spent"], 6),
                "batch_reserved": round(data["batch_reserved"], 6),
                "blocked": data["blocked"], "blocked_reason": data["blocked_reason"],
                "fish": {t: {"attempts": e["attempts"], "spent": round(e["spent"], 6),
                             "reserved": round(e["reserved"], 6)}
                         for t, e in data["fish"].items()}}


def main() -> int:
    parser = argparse.ArgumentParser(description="Betta generation budget ledger")
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--batch-id", default="")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    p = sub.add_parser("register"); p.add_argument("tank")
    p = sub.add_parser("reserve"); p.add_argument("tank"); p.add_argument("--amount", type=float, default=None)
    p = sub.add_parser("settle"); p.add_argument("rid"); p.add_argument("--cost", type=float, default=None)
    p = sub.add_parser("release"); p.add_argument("rid")
    args = parser.parse_args()
    budget = GenerationBudget(args.ledger, batch_id=args.batch_id)
    try:
        if args.cmd == "show":
            print(json.dumps(budget.summary(), indent=2, sort_keys=True))
        elif args.cmd == "register":
            budget.register_fish(args.tank); print("ok")
        elif args.cmd == "reserve":
            print(budget.reserve(args.tank, args.amount))
        elif args.cmd == "settle":
            print(budget.settle(args.rid, args.cost))
        elif args.cmd == "release":
            budget.release(args.rid); print("ok")
        return 0
    except BudgetError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
