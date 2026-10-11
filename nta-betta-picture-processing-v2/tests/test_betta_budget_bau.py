"""Offline fail-closed tests for the BAU paid-generation budget ledger."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "betta_budget.py"
SPEC = importlib.util.spec_from_file_location("betta_budget_bau_test", SCRIPT)
budget_mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(budget_mod)


class BudgetBAUSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.ledger = Path(self.temporary.name) / "budget.json"

    def tearDown(self):
        self.temporary.cleanup()

    def budget(self, *, batch_id="batch-a", limits=None):
        return budget_mod.GenerationBudget(
            self.ledger, batch_id=batch_id, limits=limits,
        )

    def test_hard_caps_cannot_be_relaxed(self):
        unsafe = [
            {"per_fish_usd": 0.15},
            {"per_batch_usd": 2.81},
            {"max_attempts_per_fish": 3},
            {"max_retries_per_fish": 2},
            {"max_fish_per_batch": 21},
        ]
        for limits in unsafe:
            with self.subTest(limits=limits):
                with self.assertRaisesRegex(budget_mod.BudgetError, "hard cap|attempt ceiling"):
                    self.budget(limits=limits)

    def test_positive_tighter_limits_are_supported(self):
        limits = {
            "per_fish_usd": 0.10,
            "per_batch_usd": 1.00,
            "max_attempts_per_fish": 1,
            "max_retries_per_fish": 0,
            "max_fish_per_batch": 10,
            "fallback_cost_usd": 0.08,
        }
        budget = self.budget(limits=limits)
        self.assertEqual(limits, budget.limits)
        budget.register_fish("1BT1")
        reservation = budget.reserve("1BT1")
        self.assertEqual(0.08, budget.settle(reservation, 0.08))

        one_attempt = self.budget(
            batch_id="batch-one-attempt", limits={"max_attempts_per_fish": 1},
        )
        self.assertEqual(0, one_attempt.limits["max_retries_per_fish"])

        below_fallback = self.budget(
            batch_id="batch-no-fallback", limits={"per_fish_usd": 0.05},
        )
        self.assertIsNone(below_fallback.limits["fallback_cost_usd"])

    def test_fallback_is_conservative_or_explicitly_disabled(self):
        with self.assertRaisesRegex(budget_mod.BudgetError, "0.07 floor"):
            self.budget(limits={"fallback_cost_usd": 0.06})
        with self.assertRaisesRegex(budget_mod.BudgetError, "cannot exceed per_fish"):
            self.budget(limits={"per_fish_usd": 0.08, "fallback_cost_usd": 0.09})
        budget = self.budget(limits={"fallback_cost_usd": None})
        budget.register_fish("1BT1")
        with self.assertRaisesRegex(budget_mod.BudgetError, "no cost available"):
            budget.reserve("1BT1")

    def test_non_finite_or_non_numeric_reservations_never_touch_ledger(self):
        budget = self.budget()
        budget.register_fish("1BT1")
        for value in (float("nan"), float("inf"), float("-inf"), True, "0.07", 0, -1):
            with self.subTest(value=value):
                with self.assertRaises(budget_mod.BudgetError):
                    budget.reserve("1BT1", value)
        summary = budget.summary()
        self.assertEqual(0, summary["fish"]["1BT1"]["attempts"])
        self.assertEqual(0.0, summary["batch_reserved"])

    def test_non_finite_actual_cost_leaves_reservation_intact(self):
        budget = self.budget()
        budget.register_fish("1BT1")
        reservation = budget.reserve("1BT1")
        for value in (float("nan"), float("inf"), float("-inf"), True, "0.07", -1):
            with self.subTest(value=value):
                with self.assertRaises(budget_mod.BudgetError):
                    budget.settle(reservation, value)
        summary = budget.summary()
        self.assertFalse(summary["blocked"])
        self.assertEqual(0.07, summary["batch_reserved"])
        self.assertEqual(0.0, summary["batch_spent"])

    def test_provider_overage_is_recorded_then_ledger_blocks(self):
        budget = self.budget()
        budget.register_fish("1BT1")
        reservation = budget.reserve("1BT1")
        with self.assertRaisesRegex(budget_mod.BudgetError, "exceeded reservation"):
            budget.settle(reservation, 0.08)

        summary = budget.summary()
        self.assertTrue(summary["blocked"])
        self.assertEqual(0.08, summary["batch_spent"])
        self.assertEqual(0.0, summary["batch_reserved"])
        self.assertIn("exceeded reservation", summary["blocked_reason"])
        with self.assertRaisesRegex(budget_mod.BudgetError, "ledger is blocked"):
            budget.reserve("1BT1", 0.01)
        with self.assertRaisesRegex(budget_mod.BudgetError, "ledger is blocked"):
            budget.register_fish("1BT2")
        self.assertEqual(
            (False, f"budget ledger is blocked: {summary['blocked_reason']}"),
            budget.can_attempt("1BT1"),
        )
        with self.assertRaisesRegex(budget_mod.BudgetError, "exceeded reservation"):
            budget.settle(reservation, 0.08)

    def test_provider_overage_block_survives_reopen(self):
        budget = self.budget()
        budget.register_fish("1BT1")
        reservation = budget.reserve("1BT1")
        with self.assertRaises(budget_mod.BudgetError):
            budget.settle(reservation, 0.20)
        reopened = self.budget()
        self.assertTrue(reopened.summary()["blocked"])
        self.assertEqual(0.20, reopened.summary()["batch_spent"])
        with self.assertRaisesRegex(budget_mod.BudgetError, "ledger is blocked"):
            reopened.reserve("1BT1")

    def test_cost_below_a_larger_reservation_does_not_block(self):
        budget = self.budget()
        budget.register_fish("1BT1")
        reservation = budget.reserve("1BT1", 0.10)
        self.assertEqual(0.08, budget.settle(reservation, 0.08))
        self.assertFalse(budget.summary()["blocked"])

    def test_reopen_rejects_batch_or_limit_drift(self):
        limits = {"per_batch_usd": 1.40}
        budget = self.budget(limits=limits)
        budget.register_fish("1BT1")
        with self.assertRaisesRegex(budget_mod.BudgetError, "batch_id differs"):
            self.budget(batch_id="batch-b", limits=limits).summary()
        with self.assertRaisesRegex(budget_mod.BudgetError, "limits differ"):
            self.budget(limits={"per_batch_usd": 1.00}).summary()
        with self.assertRaisesRegex(budget_mod.BudgetError, "limits differ"):
            self.budget().summary()

    def test_corrupt_non_finite_counters_and_totals_fail_closed(self):
        budget = self.budget()
        budget.register_fish("1BT1")
        original = json.loads(self.ledger.read_text(encoding="utf-8"))
        corruptions = [
            ("batch_spent", float("nan")),
            ("batch_reserved", float("inf")),
        ]
        for key, value in corruptions:
            with self.subTest(key=key):
                data = json.loads(json.dumps(original))
                data[key] = value
                self.ledger.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(budget_mod.BudgetError):
                    budget.summary()
        data = json.loads(json.dumps(original))
        data["fish"]["1BT1"]["spent"] = 0.01
        self.ledger.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(budget_mod.BudgetError, "inconsistent"):
            budget.summary()

    def test_corrupt_block_flag_without_violation_evidence_is_rejected(self):
        budget = self.budget()
        budget.register_fish("1BT1")
        data = json.loads(self.ledger.read_text(encoding="utf-8"))
        data["blocked"] = True
        data["blocked_reason"] = "invented"
        self.ledger.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(budget_mod.BudgetError, "blocked state"):
            budget.summary()


if __name__ == "__main__":
    unittest.main()
