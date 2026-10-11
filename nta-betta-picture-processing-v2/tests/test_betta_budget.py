"""Offline tests for paid-generation budget enforcement."""

import importlib.util
import tempfile
import threading
import unittest
from pathlib import Path


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bud = _load("betta_budget_t", "betta_budget.py")
policy_mod = _load("betta_policy_b", "betta_policy.py")


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Path(self.tmp.name) / "gen-budget.json"

    def tearDown(self):
        self.tmp.cleanup()

    def budget(self, **limits):
        return bud.GenerationBudget(self.ledger, batch_id="b1", limits=limits or None)

    def test_one_generation(self):
        b = self.budget(); b.register_fish("2BT12")
        rid = b.reserve("2BT12"); charged = b.settle(rid, 0.07)
        self.assertEqual(charged, 0.07)
        self.assertEqual(b.summary()["batch_spent"], 0.07)

    def test_one_permitted_retry(self):
        b = self.budget(); b.register_fish("2BT12")
        r1 = b.reserve("2BT12"); b.settle(r1, 0.07, reported=False)  # failed attempt, still charged
        ok, reason = b.can_attempt("2BT12")
        self.assertTrue(ok)
        r2 = b.reserve("2BT12"); b.settle(r2, 0.07)
        self.assertEqual(b.summary()["fish"]["2BT12"]["attempts"], 2)

    def test_third_generation_blocked(self):
        b = self.budget(); b.register_fish("2BT12")
        for _ in range(2):
            r = b.reserve("2BT12"); b.settle(r, 0.07)
        with self.assertRaises(bud.BudgetError):
            b.reserve("2BT12")

    def test_per_fish_budget_exceeded(self):
        b = self.budget(per_fish_usd=0.10); b.register_fish("2BT12")
        r = b.reserve("2BT12")  # 0.07
        with self.assertRaises(bud.BudgetError):
            b.reserve("2BT12")  # 0.07 reserved already, 0.07+0.07>0.10
        b.settle(r, 0.07)

    def test_per_batch_budget_exceeded(self):
        b = self.budget(per_batch_usd=0.10)
        for tank in ("2BT12", "2BT13"):
            b.register_fish(tank)
        b.reserve("2BT12")
        with self.assertRaises(bud.BudgetError):
            b.reserve("2BT13")  # second 0.07 exceeds 0.10 batch cap

    def test_provider_cost_above_estimate_counts_actual(self):
        b = self.budget(); b.register_fish("2BT12")
        rid = b.reserve("2BT12")  # reserves 0.07
        with self.assertRaises(bud.BudgetError):
            b.settle(rid, 0.20)  # billed evidence persists before fail-closed error
        self.assertEqual(b.summary()["batch_spent"], 0.20)
        self.assertTrue(b.summary()["blocked"])
        with self.assertRaises(bud.BudgetError):
            b.reserve("2BT12")  # blocked after provider exceeded reservation/cap

    def test_concurrent_reservations_cannot_bypass_batch_cap(self):
        b = self.budget(per_batch_usd=0.14)
        tanks = [f"9BT{i}" for i in range(20)]
        for t in tanks:
            b.register_fish(t)  # max_fish default 20
        successes, errors = [], []
        lock = threading.Lock()

        def worker(t):
            try:
                rid = b.reserve(t)
                with lock:
                    successes.append(t)
            except bud.BudgetError:
                with lock:
                    errors.append(t)

        threads = [threading.Thread(target=worker, args=(t,)) for t in tanks]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(len(successes), 2)  # 0.14 / 0.07
        self.assertLessEqual(b.summary()["batch_reserved"], 0.14 + 1e-9)

    def test_interrupted_generation_stays_reserved(self):
        b = self.budget(); b.register_fish("2BT12")
        b.reserve("2BT12")  # no settle -> interrupted
        s = b.summary()
        self.assertEqual(s["batch_spent"], 0.0)
        self.assertEqual(s["batch_reserved"], 0.07)

    def test_resume_after_interrupted(self):
        b = self.budget(); b.register_fish("2BT12")
        rid = b.reserve("2BT12")
        b.release(rid, "interrupted, not charged")
        self.assertEqual(b.summary()["batch_reserved"], 0.0)
        r2 = b.reserve("2BT12")  # attempt re-issued after release
        self.assertTrue(r2)

    def test_missing_cost_information_fails_closed(self):
        b = self.budget(fallback_cost_usd=None); b.register_fish("2BT12")
        with self.assertRaises(bud.BudgetError):
            b.reserve("2BT12", None)

    def test_batch_larger_than_limit_rejected(self):
        b = self.budget()
        for i in range(20):
            b.register_fish(f"9BT{i}")
        with self.assertRaises(bud.BudgetError):
            b.register_fish("9BT20")  # 21st fish

    def test_no_extra_attempts_after_completion(self):
        b = self.budget(); b.register_fish("2BT12")
        r = b.reserve("2BT12"); b.settle(r, 0.07)
        # a second call is still permitted (retry ceiling) but a third is not
        r2 = b.reserve("2BT12"); b.settle(r2, 0.07)
        self.assertEqual(b.summary()["fish"]["2BT12"]["attempts"], 2)
        with self.assertRaises(bud.BudgetError):
            b.reserve("2BT12")

    def test_policy_default_budget_values(self):
        data = policy_mod.default_policy()
        gb = data["generation_budget"]
        self.assertEqual(gb["per_fish_usd"], 0.14)
        self.assertEqual(gb["per_batch_usd"], 2.80)
        self.assertEqual(gb["max_attempts_per_fish"], 2)
        self.assertEqual(gb["max_retries_per_fish"], 1)
        self.assertEqual(gb["max_fish_per_batch"], 20)


if __name__ == "__main__":
    unittest.main()
