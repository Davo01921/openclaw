#!/usr/bin/env python3

import importlib.util
import argparse
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "nta_label_print.py"
SPEC = importlib.util.spec_from_file_location("nta_label_print", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class LabelPrintTests(unittest.TestCase):
    def test_one_and_three_pipes_are_preserved(self):
        text = "Name | $8ea ||| 090926 | Q20"
        self.assertEqual(MODULE.validate_text(text), text)

    def test_ambiguous_pipe_runs_are_rejected(self):
        for text in ("A || B", "A |||| B"):
            with self.subTest(text=text), self.assertRaises(MODULE.LabelError):
                MODULE.validate_text(text)

    def test_two_line_preview_is_exact_head_height(self):
        self.assertEqual(MODULE.FONT_PATH.name, "Arial Bold.ttf")
        self.assertEqual(MODULE.TWO_LINE_FONT_SIZE, 15)
        image = MODULE.render_image("Cardinal Tetra | $8ea\n090926 | Q20")
        self.assertEqual(image.height, 30)
        self.assertGreater(image.width, 0)
        self.assertIn(0, image.getdata())
        ink_rows = [
            y
            for y in range(image.height)
            if any(image.getpixel((x, y)) == 0 for x in range(image.width))
        ]
        self.assertEqual(max(ink_rows) - min(ink_rows) + 1, 30)

    def test_standard_dollar_symbol_is_preserved(self):
        text = "Cardinal Tetra | $8ea\n090926 | Q20"
        self.assertEqual(MODULE.validate_text(text), text)
        self.assertNotIn("＄", text)

    def test_preview_writes_png_without_bluetooth(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "preview.png"
            result = MODULE.save_preview("NTA TEST", output)
            self.assertTrue(output.exists())
            self.assertTrue(result["dry_run"])
            self.assertEqual(result["cutter_action"], "NONE")

    def test_structured_livestock_input_uses_canonical_python_formatter(self):
        payload = {
            "product_name": "Cardinal Tetra",
            "retail_price": "8.00",
            "bulk_price": None,
            "bulk_min_quantity": None,
            "shopify_arrival_date": "2026-09-09",
            "quantity": 20,
            "source": "shopify_readback",
            "shopify_barcode": "X12ENA3C59",
        }
        args = argparse.Namespace(text=None, label_file=None, label_json=json.dumps(payload))
        self.assertEqual(
            MODULE.resolve_label_text(args),
            "Cardinal Tetra | $8ea\n090926 | Q20",
        )
        _, barcode = MODULE.resolve_label_content(args)
        self.assertEqual(barcode, "X12ENA3C59")

    def test_shopify_barcode_is_encoded_as_code128_b(self):
        symbols = MODULE.code128b_symbols("X12ENA3C59")
        self.assertEqual(symbols[0], 104)
        self.assertEqual(symbols[-1], 106)
        expected_checksum = (
            104 + sum(i * code for i, code in enumerate(symbols[1:-2], 1))
        ) % 103
        self.assertEqual(symbols[-2], expected_checksum)
        modules = MODULE._barcode_modules("X12ENA3C59")
        self.assertTrue(modules.startswith("0" * MODULE.BARCODE_QUIET_MODULES))
        self.assertTrue(modules.endswith("0" * MODULE.BARCODE_QUIET_MODULES))

    def test_barcode_preview_appends_to_text_and_keeps_head_height(self):
        text_only = MODULE.render_image("RCS Red Cherry Shrimp | $5ea\n240926 | Q100")
        with_barcode = MODULE.render_image(
            "RCS Red Cherry Shrimp | $5ea\n240926 | Q100", "X12ENA3C59"
        )
        self.assertEqual(with_barcode.height, 30)
        self.assertGreater(with_barcode.width, text_only.width)

    def test_barcode_uses_full_height_without_human_readable_text(self):
        image = MODULE._render_barcode_raster("X12ENA3C59")
        self.assertEqual(image.height, 30)
        ink_rows = [
            y
            for y in range(image.height)
            if any(image.getpixel((x, y)) == 0 for x in range(image.width))
        ]
        self.assertEqual(ink_rows, list(range(30)))

    def test_structured_input_requires_verified_shopify_barcode(self):
        payload = {
            "product_name": "Cardinal Tetra",
            "retail_price": "8.00",
            "shopify_arrival_date": "2026-09-09",
            "quantity": 20,
            "source": "shopify_readback",
        }
        result = MODULE.render_label(payload)
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertIn("shopify_barcode", result["missing_or_invalid_fields"])

    def test_structured_input_never_invents_missing_date(self):
        payload = {
            "product_name": "Cardinal Tetra",
            "retail_price": "8.00",
            "quantity": 20,
            "source": "shopify_readback",
            "shopify_barcode": "X12ENA3C59",
        }
        args = argparse.Namespace(text=None, label_file=None, label_json=json.dumps(payload))
        with self.assertRaises(MODULE.LabelError):
            MODULE.resolve_label_text(args)


if __name__ == "__main__":
    unittest.main()
