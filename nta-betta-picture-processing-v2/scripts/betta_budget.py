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


class BudgetError(RuntimeError):
    pass


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
        self.batch_id = batch_id
        self.limits = {**DEFAULT_LIMITS, **(limits or {})}
        self.lock_timeout = lock_timeout

    # -- persistence ------------------------------------------------------- #
    def _blank(self) -> dict:
        return {"schema": SCHEMA, "batch_id": self.batch_id, "limits": self.limits,
                "fish": {}, "reservations": {}, "batch_spent": 0.0, "batch_reserved": 0.0}

    def _load(self) -> dict:
        if self.path.is_file():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("schema") != SCHEMA:
                raise BudgetError("unsupported budget schema")
            return data
        return self._blank()

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
            if tank in data["fish"]:
                return
            if len(data["fish"]) >= self.limits["max_fish_per_batch"]:
                raise BudgetError(f"batch exceeds max_fish_per_batch={self.limits['max_fish_per_batch']}")
            data["fish"][tank] = {"attempts": 0, "spent": 0.0, "reserved": 0.0, "reservations": []}
            _atomic_write(self.path, data)

    def can_attempt(self, tank: str) -> tuple[bool, Optional[str]]:
        data = self._load()
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
            entry = data["fish"].get(tank)
            if entry is None:
                raise BudgetError("fish not registered")
            if entry["attempts"] >= self.limits["max_attempts_per_fish"]:
                raise BudgetError(f"attempts exhausted for {tank}")
            if amount is None:
                amount = self.limits.get("fallback_cost_usd")
            if amount is None or float(amount) <= 0:
                raise BudgetError("no cost available and no fallback; failing closed")
            amount = float(amount)
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
                return float(reservation["actual"] or reservation["amount"])
            tank = reservation["tank"]
            amount = float(reservation["amount"])
            charged = amount if actual_cost is None else float(actual_cost)
            if charged < 0:
                raise BudgetError("negative cost")
            entry = data["fish"][tank]
            entry["reserved"] = max(0.0, float(entry.get("reserved", 0.0)) - amount)
            entry["spent"] = float(entry.get("spent", 0.0)) + charged
            data["batch_reserved"] = max(0.0, float(data["batch_reserved"]) - amount)
            data["batch_spent"] = float(data["batch_spent"]) + charged
            reservation.update({"settled": True, "actual": charged, "reported": reported})
            _atomic_write(self.path, data)
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
            _atomic_write(self.path, data)

    def summary(self) -> dict:
        data = self._load()
        return {"batch_id": data.get("batch_id"), "limits": data["limits"],
                "batch_spent": round(data["batch_spent"], 6),
                "batch_reserved": round(data["batch_reserved"], 6),
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
