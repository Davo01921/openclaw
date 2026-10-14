#!/usr/bin/env python3
"""Deterministic working-photo preparation for the Betta BAU pipeline.

Ports the owner-reviewed local preparation pipeline (tank-boundary crop, bounded
exposure and white balance, isolated neutral water-debris cleanup) together with
the prototype preflight's fish-protection rules:

* the crop always contains the expanded fish safety rectangle;
* debris is never removed inside the expanded fish rectangle;
* debris cleanup is capped at 2.5% of the frame and skipped over budget;
* tone and white-balance corrections are bounded and never invent content;
* every operation is recorded so the adapter can re-verify the invariants.

This module performs no external calls and never modifies the raw original.
Vision geometry and the prepared-image visual QA are supplied by the caller as
evidence; the deterministic gate here is what makes the receipt auditable.
"""

from __future__ import annotations

import hashlib
from collections import deque
from pathlib import Path
from typing import Optional

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

LEVEL_FULL = "FULL"
LEVEL_L1 = "L1"  # conservative fallback: no crop, no debris cleanup
LEVELS = (LEVEL_FULL, LEVEL_L1)

FISH_MARGIN_FRACTION = 0.012
CROP_PAD_FRACTION = 0.018
MIN_TANK_AREA_FRACTION = 0.08
MAX_DEBRIS_FRACTION = 0.025
DEBRIS_MAX_COMPONENT = 18      # half-scale pixels
DEBRIS_MASK_BOX_LIMIT = 64
WB_GAIN_MIN, WB_GAIN_MAX = 0.94, 1.06
WB_NEUTRAL_TOLERANCE = 0.02
SEVERE_DARK_MEDIAN, SEVERE_BRIGHT_MEDIAN = 15.0, 248.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_rect(value, width: int, height: int, *, label: str) -> tuple[int, int, int, int]:
    """Normalized xyxy bounds in [0, 1] to integer pixel bounds (x1y1x2y2)."""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"{label}: need [left,top,right,bottom]")
    try:
        left, top, right, bottom = (float(item) for item in value)
    except (TypeError, ValueError):
        raise ValueError(f"{label}: nonnumeric bounds") from None
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError(f"{label}: invalid normalized bounds")
    x0 = min(width - 1, int(left * width))
    y0 = min(height - 1, int(top * height))
    x1 = max(x0 + 1, min(width, int(right * width)))
    y1 = max(y0 + 1, min(height, int(bottom * height)))
    return (x0, y0, x1, y1)


def expand(rect, pad: int, width: int, height: int) -> tuple[int, int, int, int]:
    return (max(0, rect[0] - pad), max(0, rect[1] - pad),
            min(width, rect[2] + pad), min(height, rect[3] + pad))


def union(a, b) -> tuple[int, int, int, int]:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def contains(outer, inner) -> bool:
    return (outer[0] <= inner[0] and outer[1] <= inner[1]
            and outer[2] >= inner[2] and outer[3] >= inner[3])


def intersects(a, b) -> bool:
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def rect_area(rect) -> int:
    return max(0, rect[2] - rect[0]) * max(0, rect[3] - rect[1])


def detect_tank_bounds_cyan(image: Image.Image) -> tuple[tuple[int, int, int, int], bool]:
    """Conservative tank bounds from cyan glass edges (reference utility only).

    Retained from the owner-reviewed local flow for offline comparison; the
    automatic ladder crops only from fish-verified vision bounds.  Returns the
    bounds and whether the detection was confident.  The full width is retained
    when the heuristics cannot find reliable edges, and the label area at the
    top of the frame is always retained.
    """
    w, h = image.size
    sample = image.resize((max(1, w // 6), max(1, h // 6)), Image.Resampling.BILINEAR)
    sw, sh = sample.size
    pix = sample.load()

    def cyan(r: int, g: int, b: int) -> bool:
        return g > 50 and b > 45 and g > r * 1.03 and b > r * 0.92

    cols = []
    for x in range(sw):
        score = sum(cyan(*pix[x, y]) for y in range(int(sh * .12), int(sh * .83)))
        cols.append(score)
    left_candidates = range(0, max(1, int(sw * .42)))
    right_candidates = range(min(sw - 1, int(sw * .58)), sw)
    left = max(left_candidates, key=lambda x: cols[x])
    right = max(right_candidates, key=lambda x: cols[x])
    confident = True
    if right - left < sw * .45:
        left, right = int(sw * .04), int(sw * .96)
        confident = False

    rows = []
    for y in range(sh):
        score = sum(cyan(*pix[x, y]) for x in range(left, right + 1))
        rows.append(score)
    lower = range(int(sh * .55), min(sh, int(sh * .95)))
    bottom = max(lower, key=lambda y: rows[y])
    if bottom < sh * .62:
        bottom = int(sh * .83)
        confident = False

    scale_x, scale_y = w / sw, h / sh
    pad_x = int(w * .018)
    x0 = max(0, int(left * scale_x) - pad_x)
    x1 = min(w, int((right + 1) * scale_x) + pad_x)
    y0 = 0
    y1 = min(h, int((bottom + 1) * scale_y) + int(h * .025))
    return (x0, y0, x1, y1), confident


def _white_balance(image: Image.Image) -> tuple[Image.Image, list[float], bool]:
    """Bounded neutral-pixel white balance; skipped when already neutral."""
    small = image.resize((max(1, image.width // 4), max(1, image.height // 4)),
                         Image.Resampling.BILINEAR)
    pix = small.load()
    sw, sh = small.size
    r_total = g_total = b_total = 0
    count = 0
    for y in range(0, sh, 2):
        for x in range(0, sw, 2):
            r, g, b = pix[x, y]
            if max(r, g, b) - min(r, g, b) < 36:
                r_total += r
                g_total += g
                b_total += b
                count += 1
    if count < 50:
        return image, [1.0, 1.0, 1.0], False
    means = [r_total / count, g_total / count, b_total / count]
    target = sum(means) / 3
    gains = [min(WB_GAIN_MAX, max(WB_GAIN_MIN, target / max(mean, 1.0))) for mean in means]
    if all(abs(gain - 1.0) <= WB_NEUTRAL_TOLERANCE for gain in gains):
        return image, [1.0, 1.0, 1.0], False
    channels = image.split()
    balanced = [
        channel.point(lambda value, gain=gain: min(255, int(value * gain + 0.5)))
        for channel, gain in zip(channels, gains)
    ]
    return Image.merge("RGB", balanced), [round(gain, 4) for gain in gains], True


def _enhance_validated(image: Image.Image) -> Image.Image:
    """The owner-reviewed bounded enhancement profile (unchanged constants)."""
    image = ImageOps.autocontrast(image, cutoff=(0.4, 0.15), preserve_tone=True)
    image = ImageEnhance.Brightness(image).enhance(1.10)
    image = ImageEnhance.Contrast(image).enhance(1.06)
    image = ImageEnhance.Color(image).enhance(1.035)
    image = ImageEnhance.Sharpness(image).enhance(1.12)
    return image


def _median_luminance(image: Image.Image) -> float:
    sample = image.resize((max(1, image.width // 8), max(1, image.height // 8)),
                          Image.Resampling.BILINEAR)
    pix = sample.load()
    sw, sh = sample.size
    values = []
    for y in range(0, sh, 2):
        for x in range(0, sw, 2):
            r, g, b = pix[x, y]
            values.append((r * 54 + g * 183 + b * 19) // 256)
    values.sort()
    return float(values[len(values) // 2]) if values else 0.0


def _clean_isolated_bright_debris(
    image: Image.Image, *, fish_rect_crop: Optional[tuple[int, int, int, int]],
) -> tuple[Image.Image, int, list[list[int]]]:
    """Replace tiny neutral bright components over dark water, never on the fish.

    Only runs when the expanded fish rectangle is known; candidates inside it are
    never touched.  Returns the cleaned image, the estimated replaced pixel count
    and the replaced mask boxes in crop pixels.
    """
    rgb = image.convert("RGB")
    w, h = rgb.size
    small = rgb.resize((max(1, w // 2), max(1, h // 2)), Image.Resampling.BILINEAR)
    median = small.filter(ImageFilter.MedianFilter(7))
    pix = small.load()
    med = median.load()
    sw, sh = small.size
    fish_half = None
    if fish_rect_crop is not None:
        # One half-scale pixel covers a 2x2 full-resolution block, so expand the
        # exclusion ring by one cell on every side: a dot straddling the fish
        # edge must never be touched.
        fish_half = (max(0, fish_rect_crop[0] // 2 - 1),
                     max(0, fish_rect_crop[1] // 2 - 1),
                     min(sw, fish_rect_crop[2] // 2 + 1),
                     min(sh, fish_rect_crop[3] // 2 + 1))
    candidates: set[tuple[int, int]] = set()
    for y in range(int(sh * .15), int(sh * .92)):
        for x in range(int(sw * .03), int(sw * .97)):
            if fish_half is not None and (fish_half[0] <= x < fish_half[2]
                                          and fish_half[1] <= y < fish_half[3]):
                continue
            r, g, b = pix[x, y]
            mr, mg, mb = med[x, y]
            lum = (r * 54 + g * 183 + b * 19) // 256
            mlum = (mr * 54 + mg * 183 + mb * 19) // 256
            chroma = max(r, g, b) - min(r, g, b)
            if mlum < 92 and lum - mlum > 42 and chroma < 48:
                candidates.add((x, y))

    seen: set[tuple[int, int]] = set()
    boxes: list[list[int]] = []
    replace: set[tuple[int, int]] = set()
    for seed in candidates:
        if seed in seen:
            continue
        component: list[tuple[int, int]] = []
        queue = deque([seed])
        seen.add(seed)
        while queue:
            x, y = queue.popleft()
            component.append((x, y))
            for nx in (x - 1, x, x + 1):
                for ny in (y - 1, y, y + 1):
                    if (nx, ny) in candidates and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        queue.append((nx, ny))
        if len(component) <= DEBRIS_MAX_COMPONENT:
            replace.update(component)
            xs = [point[0] for point in component]
            ys = [point[1] for point in component]
            if len(boxes) < DEBRIS_MASK_BOX_LIMIT:
                boxes.append([min(xs) * 2, min(ys) * 2,
                              (max(xs) + 1) * 2, (max(ys) + 1) * 2])

    out = small.copy()
    op = out.load()
    for x, y in replace:
        op[x, y] = med[x, y]
    out = out.resize((w, h), Image.Resampling.LANCZOS)
    return out, len(replace) * 4, boxes


def prepare_image(
    *, raw_path: Path, output_path: Path, level: str,
    tank_bounds: Optional[list] = None, fish_bounds: Optional[list] = None,
) -> dict:
    """Produce the working photo and the deterministic operations record.

    ``tank_bounds``/``fish_bounds`` are normalized xyxy fractions from the vision
    preflight (already validated by the caller).  On ``L1`` the frame is never
    cropped and debris is never removed.
    """
    if level not in LEVELS:
        raise ValueError(f"unsupported preparation level: {level}")
    raw_path = Path(raw_path)
    output_path = Path(output_path)
    if raw_path.resolve() == output_path.resolve():
        raise ValueError("working output cannot replace the raw original")
    with Image.open(raw_path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    width, height = image.size
    notes: list[str] = []
    crop_record: Optional[dict] = None
    fish_safe: Optional[tuple[int, int, int, int]] = None
    image_for_ops = image

    if level == LEVEL_FULL:
        crop: Optional[tuple[int, int, int, int]] = None
        origin = "none"
        clamped = False
        if tank_bounds is not None:
            try:
                tank_rect = normalized_rect(tank_bounds, width, height, label="tank_bounds")
                if rect_area(tank_rect) >= MIN_TANK_AREA_FRACTION * width * height:
                    pad = max(6, int(min(width, height) * CROP_PAD_FRACTION))
                    crop = expand(tank_rect, pad, width, height)
                    origin = "vision"
                    if fish_bounds is not None:
                        try:
                            fish_rect = normalized_rect(fish_bounds, width, height, label="fish_bounds")
                            margin = max(6, int(min(width, height) * FISH_MARGIN_FRACTION))
                            fish_safe = expand(fish_rect, margin, width, height)
                            if not contains(crop, fish_safe):
                                crop = union(crop, fish_safe)
                                clamped = True
                                notes.append("crop expanded to contain the fish safety rectangle")
                        except ValueError as exc:
                            notes.append(f"fish bounds unusable ({exc}); crop not fish-verified")
                            crop = None
                            origin = "none"
                else:
                    notes.append("tank bounds too small to be reliable")
            except ValueError as exc:
                notes.append(f"tank bounds unusable ({exc})")
        # The owner-reviewed cyan-edge heuristic is retained as a reference
        # utility (``detect_tank_bounds_cyan``), but the automatic ladder crops
        # only from vision bounds that passed the fish-safety checks; anything
        # less reliable keeps the full frame.
        if crop is not None:
            image_for_ops = image.crop(crop)
            crop_record = {
                "rect_px": list(crop), "origin": origin, "clamped_to_fish": clamped,
                "fish_safe_px": list(fish_safe) if fish_safe else None,
            }
        else:
            notes.append("no reliable tank bounds; frame retained")

    working = image_for_ops
    working, wb_gains, wb_applied = _white_balance(working)
    median_before = _median_luminance(working)
    exposure_applied = False
    skipped_reason = None
    if median_before < SEVERE_DARK_MEDIAN or median_before > SEVERE_BRIGHT_MEDIAN:
        skipped_reason = "severe exposure; enhancement skipped"
        notes.append(skipped_reason)
    else:
        working = _enhance_validated(working)
        exposure_applied = True
    median_after = _median_luminance(working)

    debris_record = {
        "replaced_pixels_estimate": 0, "replaced_fraction_estimate": 0.0,
        "mask_boxes_px": [], "fish_rect_px": None, "skipped_reason": None,
    }
    if level == LEVEL_FULL and crop_record is not None and fish_safe is not None:
        fish_rect_crop = (fish_safe[0] - crop_record["rect_px"][0],
                          fish_safe[1] - crop_record["rect_px"][1],
                          fish_safe[2] - crop_record["rect_px"][0],
                          fish_safe[3] - crop_record["rect_px"][1])
        cleaned, replaced, boxes = _clean_isolated_bright_debris(
            working, fish_rect_crop=fish_rect_crop)
        frame_area = working.width * working.height
        fraction = replaced / frame_area if frame_area else 0.0
        if fraction > MAX_DEBRIS_FRACTION:
            debris_record["skipped_reason"] = (
                "isolated debris exceeds the cleanup budget; cleanup skipped")
            notes.append(debris_record["skipped_reason"])
        else:
            working = cleaned
            debris_record.update({
                "replaced_pixels_estimate": replaced,
                "replaced_fraction_estimate": round(fraction, 6),
                "mask_boxes_px": boxes,
                "fish_rect_px": list(fish_rect_crop),
            })
    elif level == LEVEL_FULL and fish_safe is None:
        debris_record["skipped_reason"] = "fish rectangle unavailable; cleanup skipped"
    elif level == LEVEL_L1:
        debris_record["skipped_reason"] = "conservative fallback; cleanup skipped"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    working.save(output_path, format="PNG", optimize=True)
    operations = {
        "level": level,
        "raw_dimensions": [width, height],
        "crop": crop_record,
        "white_balance": {"gains": wb_gains, "applied": wb_applied},
        "exposure": {"median_before": median_before, "median_after": median_after,
                     "applied": exposure_applied, "skipped_reason": skipped_reason},
        "debris": debris_record,
        "working_dimensions": [working.width, working.height],
        "notes": notes,
    }
    return operations


def verify_preparation(operations: dict) -> list[str]:
    """Re-verify every fish-protection invariant from the operations record."""
    violations: list[str] = []
    if not isinstance(operations, dict):
        return ["operations record missing"]
    level = operations.get("level")
    if level not in LEVELS:
        return [f"invalid preparation level: {level!r}"]
    raw_dims = operations.get("raw_dimensions")
    working_dims = operations.get("working_dimensions")
    if (not isinstance(raw_dims, list) or len(raw_dims) != 2
            or not all(isinstance(value, int) and value > 0 for value in raw_dims)):
        violations.append("raw dimensions invalid")
        raw_dims = [0, 0]
    if (not isinstance(working_dims, list) or len(working_dims) != 2
            or not all(isinstance(value, int) and value > 0 for value in working_dims)):
        violations.append("working dimensions invalid")
        working_dims = [0, 0]

    crop = operations.get("crop")
    if level == LEVEL_L1 and crop is not None:
        violations.append("conservative fallback must not crop")
    if crop is not None:
        rect = crop.get("rect_px")
        if (not isinstance(rect, list) or len(rect) != 4
                or not all(isinstance(value, int) for value in rect)):
            violations.append("crop rectangle invalid")
        else:
            x0, y0, x1, y1 = rect
            if not (0 <= x0 < x1 <= raw_dims[0] and 0 <= y0 < y1 <= raw_dims[1]):
                violations.append("crop rectangle outside the raw image")
            if (x1 - x0) * (y1 - y0) < MIN_TANK_AREA_FRACTION * raw_dims[0] * raw_dims[1]:
                violations.append("crop rectangle smaller than the reliability floor")
            if working_dims != [x1 - x0, y1 - y0]:
                violations.append("working dimensions do not match the crop")
            fish_safe = crop.get("fish_safe_px")
            if fish_safe is not None:
                if (not isinstance(fish_safe, list) or len(fish_safe) != 4
                        or not all(isinstance(value, int) for value in fish_safe)):
                    violations.append("fish safety rectangle invalid")
                elif not contains((x0, y0, x1, y1), tuple(fish_safe)):
                    violations.append("crop does not contain the fish safety rectangle")
    elif working_dims != raw_dims:
        violations.append("uncropped working image must keep the raw dimensions")

    wb = operations.get("white_balance") or {}
    gains = wb.get("gains")
    if (not isinstance(gains, list) or len(gains) != 3
            or not all(isinstance(value, (int, float))
                       and WB_GAIN_MIN <= float(value) <= WB_GAIN_MAX for value in gains)):
        violations.append("white balance gains outside the bounded range")

    exposure = operations.get("exposure") or {}
    if not isinstance(exposure.get("applied"), bool):
        violations.append("exposure applied flag missing")
    median_before = exposure.get("median_before")
    if (not isinstance(median_before, (int, float)) or not 0 <= median_before <= 255):
        violations.append("exposure median invalid")
    elif exposure.get("applied") and not (SEVERE_DARK_MEDIAN < median_before < SEVERE_BRIGHT_MEDIAN):
        violations.append("enhancement applied to a severely exposed frame")

    debris = operations.get("debris") or {}
    replaced = debris.get("replaced_pixels_estimate")
    boxes = debris.get("mask_boxes_px")
    fish_rect = debris.get("fish_rect_px")
    if not isinstance(replaced, int) or replaced < 0:
        violations.append("debris replaced-pixel count invalid")
        replaced = 0
    if not isinstance(boxes, list):
        violations.append("debris mask boxes invalid")
        boxes = []
    if replaced > 0:
        if not boxes:
            violations.append("debris removed without a recorded mask")
        if fish_rect is None:
            violations.append("debris removed without a fish exclusion rectangle")
        else:
            for box in boxes:
                if not isinstance(box, list) or len(box) != 4:
                    violations.append("debris mask box malformed")
                    break
                if intersects(tuple(box), tuple(fish_rect)):
                    violations.append("debris mask intersects the fish rectangle")
                    break
        frame_area = working_dims[0] * working_dims[1]
        if frame_area and replaced / frame_area > MAX_DEBRIS_FRACTION:
            violations.append("debris cleanup exceeded the frame budget")
    elif boxes:
        violations.append("debris mask recorded without replaced pixels")
    if level == LEVEL_L1 and replaced:
        violations.append("conservative fallback must not clean debris")
    return violations
