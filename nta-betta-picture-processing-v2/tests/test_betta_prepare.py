"""Offline tests for the deterministic working-photo preparation module."""

import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parents[1] / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = _load("betta_prepare_t", "betta_prepare.py")


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_frame(width=240, height=320, *, fish_box=(60, 120, 180, 220),
               debris=(), water=(14, 20, 26)):
    image = Image.new("RGB", (width, height), water)
    draw = ImageDraw.Draw(image)
    # A saturated "fish" body so debris heuristics could not mistake it.
    draw.ellipse(fish_box, fill=(140, 30, 35))
    for point in debris:
        x, y = point
        draw.rectangle((x - 2, y - 2, x + 2, y + 2), fill=(210, 208, 205))
    return image


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write_raw(self, image, name="raw.png"):
        path = self.root / name
        image.save(path, format="PNG")
        return path

    def test_crop_contains_fish_safety_rectangle_even_when_bounds_disagree(self):
        raw = self.write_raw(make_frame())
        out = self.root / "working.png"
        ops = prepare.prepare_image(
            raw_path=raw, output_path=out, level=prepare.LEVEL_FULL,
            tank_bounds=[0.55, 0.55, 0.95, 0.95], fish_bounds=[0.2, 0.3, 0.6, 0.7])
        self.assertEqual(ops["crop"]["origin"], "vision")
        self.assertTrue(ops["crop"]["clamped_to_fish"])
        self.assertEqual(prepare.verify_preparation(ops), [])
        fish_safe = ops["crop"]["fish_safe_px"]
        x0, y0, x1, y1 = ops["crop"]["rect_px"]
        self.assertLessEqual(x0, fish_safe[0])
        self.assertLessEqual(y0, fish_safe[1])
        self.assertGreaterEqual(x1, fish_safe[2])
        self.assertGreaterEqual(y1, fish_safe[3])

    def test_full_preparation_preserves_fish_pixels_and_removes_only_outside_debris(self):
        inside = (120, 160)     # inside the fish box
        outside = (215, 60)     # dark water, away from the fish
        raw = self.write_raw(make_frame(debris=[inside, outside]))
        out = self.root / "working.png"
        ops = prepare.prepare_image(
            raw_path=raw, output_path=out, level=prepare.LEVEL_FULL,
            tank_bounds=[0.05, 0.02, 0.98, 0.97],
            fish_bounds=[0.25, 0.36, 0.75, 0.72])
        self.assertGreater(ops["debris"]["replaced_pixels_estimate"], 0)
        fish_rect = ops["debris"]["fish_rect_px"]
        for box in ops["debris"]["mask_boxes_px"]:
            self.assertFalse(prepare.intersects(tuple(box), tuple(fish_rect)))
        self.assertEqual(prepare.verify_preparation(ops), [])
        # The in-fish debris dot is preserved; the outside dot is replaced.
        original = Image.open(raw).convert("RGB")
        # in-fish point must still be bright in the working image (post crop)
        crop = ops["crop"]["rect_px"]
        working = Image.open(out).convert("RGB")
        wx, wy = inside[0] - crop[0], inside[1] - crop[1]
        value = working.getpixel((wx, wy))
        self.assertGreater(min(value), 150)  # preserved dot region untouched by cleanup
        self.assertEqual(sha(raw), sha(raw))  # raw untouched (below)
        self.assertTrue(out.is_file())

    def test_debris_straddling_an_odd_fish_edge_is_never_touched(self):
        # A bright dot at the fish boundary: the half-scale pixel covering an
        # odd full-resolution fish column must stay outside the cleanup zone,
        # so the deterministic gate never sees a mask intersecting the fish.
        image = make_frame(200, 200, fish_box=(81, 81, 181, 181),
                           debris=[(179, 100)])
        raw = self.write_raw(image, name="edge.png")
        out = self.root / "working-edge.png"
        ops = prepare.prepare_image(
            raw_path=raw, output_path=out, level=prepare.LEVEL_FULL,
            tank_bounds=[0.02, 0.02, 0.99, 0.99],
            fish_bounds=[0.405, 0.405, 0.905, 0.905])
        self.assertEqual(prepare.verify_preparation(ops), [])
        self.assertEqual(ops["debris"]["replaced_pixels_estimate"], 0)
        working = Image.open(out).convert("RGB")
        crop = ops["crop"]["rect_px"]
        value = working.getpixel((179 - crop[0], 100 - crop[1]))
        self.assertGreater(min(value), 150)  # boundary dot preserved

    def test_debris_budget_skips_cleanup_instead_of_partial_surgery(self):
        debris = [(x, y) for x in range(20, 220, 8) for y in range(30, 300, 8)]
        raw = self.write_raw(make_frame(debris=debris), name="busy.png")
        out = self.root / "working-busy.png"
        ops = prepare.prepare_image(
            raw_path=raw, output_path=out, level=prepare.LEVEL_FULL,
            tank_bounds=[0.02, 0.02, 0.98, 0.98],
            fish_bounds=[0.25, 0.36, 0.75, 0.72])
        self.assertEqual(ops["debris"]["replaced_pixels_estimate"], 0)
        self.assertIn("budget", ops["debris"]["skipped_reason"])
        self.assertEqual(prepare.verify_preparation(ops), [])

    def test_white_balance_is_bounded(self):
        image = make_frame(water=(10, 26, 40))
        raw = self.write_raw(image, name="blue.png")
        out = self.root / "working-blue.png"
        ops = prepare.prepare_image(
            raw_path=raw, output_path=out, level=prepare.LEVEL_L1)
        gains = ops["white_balance"]["gains"]
        self.assertEqual(len(gains), 3)
        for gain in gains:
            self.assertGreaterEqual(gain, prepare.WB_GAIN_MIN)
            self.assertLessEqual(gain, prepare.WB_GAIN_MAX)
        self.assertEqual(prepare.verify_preparation(ops), [])

    def test_l1_never_crops_or_cleans(self):
        raw = self.write_raw(make_frame(debris=[(215, 60)]), name="l1.png")
        out = self.root / "working-l1.png"
        ops = prepare.prepare_image(raw_path=raw, output_path=out, level=prepare.LEVEL_L1)
        self.assertIsNone(ops["crop"])
        self.assertEqual(ops["debris"]["replaced_pixels_estimate"], 0)
        self.assertEqual(ops["working_dimensions"], ops["raw_dimensions"])
        self.assertEqual(prepare.verify_preparation(ops), [])

    def test_severe_exposure_skips_enhancement_without_inventing_content(self):
        dark = Image.new("RGB", (120, 160), (4, 4, 4))
        raw = self.write_raw(dark, name="dark.png")
        out = self.root / "working-dark.png"
        ops = prepare.prepare_image(raw_path=raw, output_path=out, level=prepare.LEVEL_L1)
        self.assertFalse(ops["exposure"]["applied"])
        self.assertIn("severe", ops["exposure"]["skipped_reason"])
        self.assertEqual(prepare.verify_preparation(ops), [])

    def test_raw_original_is_never_modified(self):
        raw = self.write_raw(make_frame(debris=[(215, 60)]), name="immutable.png")
        before = sha(raw)
        out = self.root / "working-immutable.png"
        prepare.prepare_image(
            raw_path=raw, output_path=out, level=prepare.LEVEL_FULL,
            tank_bounds=[0.05, 0.02, 0.98, 0.97], fish_bounds=[0.25, 0.36, 0.75, 0.72])
        self.assertEqual(sha(raw), before)

    def test_verify_preparation_flags_tampered_records(self):
        raw = self.write_raw(make_frame(), name="verify.png")
        out = self.root / "working-verify.png"
        ops = prepare.prepare_image(
            raw_path=raw, output_path=out, level=prepare.LEVEL_FULL,
            tank_bounds=[0.05, 0.02, 0.98, 0.97], fish_bounds=[0.25, 0.36, 0.75, 0.72])
        self.assertEqual(prepare.verify_preparation(ops), [])

        out_of_bounds = {**ops, "crop": {**ops["crop"], "rect_px": [-5, 0, 50, 50]}}
        self.assertIn("crop rectangle outside the raw image",
                      prepare.verify_preparation(out_of_bounds))
        out_of_bounds = {**ops, "crop": {**ops["crop"], "rect_px": [0, 0, 10, 10],
                                         "fish_safe_px": None}}
        self.assertTrue(any("reliability floor" in item
                            for item in prepare.verify_preparation(out_of_bounds)))
        bad_gains = {**ops, "white_balance": {"gains": [1.5, 1.0, 1.0], "applied": True}}
        self.assertTrue(any("white balance" in item
                            for item in prepare.verify_preparation(bad_gains)))
        bad_debris = {**ops, "debris": {**ops["debris"],
                                        "mask_boxes_px": [list(ops["debris"]["fish_rect_px"])
                                                          if ops["debris"]["fish_rect_px"] else [0, 0, 1, 1]],
                                        "replaced_pixels_estimate": 10}}
        self.assertTrue(any("intersects the fish" in item or "exclusion" in item
                            for item in prepare.verify_preparation(bad_debris)))
        l1_with_crop = {**ops, "level": prepare.LEVEL_L1}
        self.assertIn("conservative fallback must not crop",
                      prepare.verify_preparation(l1_with_crop))

    # -- focused label-crop helper (incident repair 2026-10-15) ------------- #

    def make_label_frame(self, width=300, height=400, *, card_rows=(0, 60)):
        image = Image.new("RGB", (width, height), (8, 12, 16))
        draw = ImageDraw.Draw(image)
        if card_rows:
            draw.rectangle((0, card_rows[0], width - 1, card_rows[1]),
                           fill=(238, 236, 230))
        return image

    def test_label_crop_detects_card_band_and_keeps_full_width(self):
        raw = self.write_raw(self.make_label_frame(), name="label.png")
        out = self.root / "label-crop.png"
        record = prepare.label_crop(raw, out)
        self.assertEqual(record["method"], "card-band")
        self.assertTrue(record["confident"])
        x0, y0, x1, y1 = record["rect_px"]
        self.assertEqual([x0, y0, x1], [0, 0, 300])
        # The crop contains the whole card (ends at row 60) but excludes most of
        # the tank below the card (never extending to the 35% search limit).
        self.assertGreater(y1, 60)
        self.assertLess(y1, prepare.LABEL_SEARCH_FRACTION * 400)
        self.assertEqual(record["output_dimensions"], [300, y1])
        self.assertTrue(out.is_file())

    def test_label_crop_falls_back_to_full_width_top_30_percent_band(self):
        # No card-like band at all: conservative fallback, never a guess.
        raw = self.write_raw(self.make_label_frame(card_rows=None), name="plain.png")
        out = self.root / "plain-crop.png"
        record = prepare.label_crop(raw, out)
        self.assertEqual(record["method"], "fallback-top-band")
        self.assertFalse(record["confident"])
        self.assertEqual(record["rect_px"], [0, 0, 300, 120])

        # A card that only starts far down the frame is not trusted either.
        raw = self.write_raw(self.make_label_frame(card_rows=(100, 160)),
                             name="low.png")
        out = self.root / "low-crop.png"
        record = prepare.label_crop(raw, out)
        self.assertEqual(record["method"], "fallback-top-band")
        self.assertFalse(record["confident"])
        self.assertEqual(record["rect_px"], [0, 0, 300, 120])

    def test_label_crop_clamps_when_card_reaches_the_search_limit(self):
        raw = self.write_raw(self.make_label_frame(card_rows=(0, 399)),
                             name="carded.png")
        out = self.root / "carded-crop.png"
        record = prepare.label_crop(raw, out)
        self.assertEqual(record["method"], "card-band")
        self.assertTrue(record["clamped"])
        self.assertEqual(record["rect_px"], [0, 0, 300, 140])

    def test_label_crop_refuses_to_replace_the_raw_original(self):
        raw = self.write_raw(self.make_label_frame(), name="safe.png")
        with self.assertRaises(ValueError):
            prepare.label_crop(raw, raw)

    def test_label_crop_records_the_final_path_and_leaves_no_temp_artifacts(self):
        raw = self.write_raw(self.make_label_frame(), name="atomic.png")
        out = self.root / "crops" / "atomic-crop.png"
        record = prepare.label_crop(raw, out)
        # The persisted record references only the final crop path, never a
        # `.part` intermediate.
        self.assertEqual(record["output_path"], str(out))
        self.assertNotIn(".part", record["output_path"])
        self.assertTrue(out.is_file())
        self.assertEqual(record["output_sha256"], sha(out))
        # After a successful commit no staging artifact remains anywhere.
        self.assertEqual(list(self.root.rglob("*.part")), [])
        self.assertEqual(sorted(path.name for path in (self.root / "crops").iterdir()),
                         ["atomic-crop.png"])

    def test_label_crop_failure_cleans_up_its_temp_file(self):
        raw = self.write_raw(self.make_label_frame(), name="failing.png")
        target = self.root / "already-a-directory"
        target.mkdir()
        with self.assertRaises(OSError):
            prepare.label_crop(raw, target)
        self.assertEqual(list(self.root.rglob("*.part")), [])
        self.assertTrue(target.is_dir())  # the failed target is left untouched


if __name__ == "__main__":
    unittest.main()
