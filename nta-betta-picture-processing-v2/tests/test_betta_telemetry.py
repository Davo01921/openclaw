import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "betta_telemetry.py"
spec = importlib.util.spec_from_file_location("betta_telemetry", SCRIPT)
bt = importlib.util.module_from_spec(spec); spec.loader.exec_module(bt)


class TelemetryTests(unittest.TestCase):
    def ledger(self):
        return {
            "batch_id": "batch-1",
            "items": [{
                "id": "4BT41",
                "history": [
                    {"from": None, "to": "DISCOVERED", "at": "2026-09-13T10:00:00+10:00"},
                    {"from": "DISCOVERED", "to": "SAVED", "at": "2026-09-13T10:05:00+10:00"},
                    {"from": "SAVED", "to": "VISUAL_PENDING", "at": "2026-09-13T10:10:00+10:00"},
                    {"from": "VISUAL_PENDING", "to": "VISUAL_ACCEPTED", "at": "2026-09-13T10:20:00+10:00"},
                    {"from": "VISUAL_ACCEPTED", "to": "PRODUCT_RESOLVED", "at": "2026-09-13T10:25:00+10:00"},
                    {"from": "PRODUCT_RESOLVED", "to": "VERIFIED", "at": "2026-09-13T11:00:00+10:00"},
                    {"from": "VERIFIED", "to": "PASS", "at": "2026-09-13T11:01:00+10:00"},
                    {"from": "PASS", "to": "ARCHIVED", "at": "2026-09-13T11:10:00+10:00"},
                ],
                "catalogue": {
                    "photo_date": "2026-09-04",
                    "title": "4BT41 - Galaxy Koi Halfmoon Male",
                    "evidence": {
                        "provider": "google",
                        "model": "gemini-3.5-flash",
                        "usage": {"tokens_input": 100, "tokens_output": 20},
                        "attempts": [{"model": "other/model", "usage": {"tokens_input": 30, "tokens_output": 5}}],
                    },
                },
                "image_qa": {
                    "visual": {
                        "provider": "openai",
                        "model": "gpt-5.6-sol",
                        "usage": {"tokens_input": 50, "tokens_output": 10},
                        "attempts": [],
                    }
                },
                "product": {"id": "gid://shopify/Product/1"},
            }],
        }

    def test_builds_duration_usage_and_cost(self):
        grok = [{
            "provider": "xai",
            "model": "grok-imagine-image-2.0",
            "tokens_input": 0,
            "tokens_output": 0,
            "grokai_cost": 0.04,
            "grokai_cost_currency": "USD",
            "grokai_cost_source": "provider",
        }]
        row = bt.build_from_ledger(self.ledger(), "4BT41", grok)
        self.assertEqual(row["onboarding_seconds"], 3600.0)
        self.assertEqual(row["end_to_archive_seconds"], 4200.0)
        self.assertEqual(row["tokens_input"], 180)
        self.assertEqual(row["tokens_output"], 35)
        self.assertEqual(row["model_calls"], 4)
        self.assertEqual(row["retry_count"], 1)
        self.assertEqual(row["grok_calls"], 1)
        self.assertEqual(row["grokai_cost"], 0.04)
        self.assertEqual(row["grok_cost_unknown_calls"], 0)

    def test_unknown_grok_cost_is_not_zero(self):
        grok = [{
            "provider": "xai",
            "model": "grok-imagine-image-2.0",
            "tokens_input": 0,
            "tokens_output": 0,
            "grokai_cost": None,
            "grokai_cost_source": "unavailable",
        }]
        row = bt.build_from_ledger(self.ledger(), "4BT41", grok)
        self.assertIsNone(row["grokai_cost"])
        self.assertEqual(row["grokai_cost_source"], "incomplete")
        self.assertEqual(row["grok_cost_unknown_calls"], 1)

    def test_sqlite_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "telemetry.sqlite3"
            con = bt.connect(db)
            row = bt.build_from_ledger(self.ledger(), "4BT41", [])
            bt.upsert(con, row)
            saved = con.execute(
                "SELECT tank_number,onboarding_seconds,model_calls,retry_count,grokai_cost_source "
                "FROM betta_processing_telemetry WHERE tank_number='4BT41'"
            ).fetchone()
            con.close()
            self.assertEqual(saved, ("4BT41", 3600.0, 3, 1, "not_used"))


if __name__ == "__main__":
    unittest.main()
