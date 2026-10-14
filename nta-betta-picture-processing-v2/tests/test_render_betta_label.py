"""Offline tests for the deterministic hero label renderer's tank validation."""

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "render_betta_label.py"
spec = importlib.util.spec_from_file_location("render_betta_label", SCRIPT)
render_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render_mod)


class RenderBettaLabelTests(unittest.TestCase):
    def test_accepts_supported_tank_namespaces(self):
        for tank in ("5BT24", "APE16"):
            with self.subTest(tank=tank):
                self.assertTrue(render_mod.valid_tank_number(tank))

    def test_rejects_malformed_values(self):
        for tank in ("", "APE", "BT16", "5BT"):
            with self.subTest(tank=tank):
                self.assertFalse(render_mod.valid_tank_number(tank))


if __name__ == "__main__":
    unittest.main()
