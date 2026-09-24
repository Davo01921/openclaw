#!/usr/bin/env python3
"""Local NTA label previewer and DYMO LetraTag 200B BLE printer client."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from label_formatter import render_label


FONT_PATH = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")
MAX_LINES = 2
MAX_TEXT_CHARS = 240
SCAN_TIMEOUT = 12
PRINT_REPLY_TIMEOUT = 35
ONE_LINE_FONT_SIZE = 20
TWO_LINE_FONT_SIZE = 15
BARCODE_BAR_HEIGHT = 30
BARCODE_GAP = 12
BARCODE_QUIET_MODULES = 12

# Code 128 symbol widths, indexed by symbol value. Each digit is the width of
# the next alternating bar/space run in modules. Symbol 106 is the stop code.
CODE128_PATTERNS = (
    "212222", "222122", "222221", "121223", "121322", "131222",
    "122213", "122312", "132212", "221213", "221312", "231212",
    "112232", "122132", "122231", "113222", "123122", "123221",
    "223211", "221132", "221231", "213212", "223112", "312131",
    "311222", "321122", "321221", "312212", "322112", "322211",
    "212123", "212321", "232121", "111323", "131123", "131321",
    "112313", "132113", "132311", "211313", "231113", "231311",
    "112133", "112331", "132131", "113123", "113321", "133121",
    "313121", "211331", "231131", "213113", "213311", "213131",
    "311123", "311321", "331121", "312113", "312311", "332111",
    "314111", "221411", "431111", "111224", "111422", "121124",
    "121421", "141122", "141221", "112214", "112412", "122114",
    "122411", "142112", "142211", "241211", "221114", "413111",
    "241112", "134111", "111242", "121142", "121241", "114212",
    "124112", "124211", "411212", "421112", "421211", "212141",
    "214121", "412121", "111143", "111341", "131141", "114113",
    "114311", "411113", "411311", "113141", "114131", "311141",
    "411131", "211412", "211214", "211232", "2331112",
)


class LabelError(ValueError):
    pass


def emit(payload: dict[str, Any], *, error: bool = False) -> None:
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr if error else sys.stdout)


def validate_text(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise LabelError("label text must not be empty")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if len(normalized) > MAX_TEXT_CHARS:
        raise LabelError(f"label text exceeds {MAX_TEXT_CHARS} characters")
    if len(normalized.split("\n")) > MAX_LINES:
        raise LabelError("LetraTag labels support at most two text lines")
    for run in re.findall(r"\|+", normalized):
        if len(run) not in (1, 3):
            raise LabelError("pipe runs must be either | (field separator) or ||| (manual cut marker)")
    return normalized


def _font(size: int) -> ImageFont.FreeTypeFont:
    if not FONT_PATH.exists():
        raise LabelError(f"required local font is missing: {FONT_PATH}")
    return ImageFont.truetype(str(FONT_PATH), size=size)


def _render_text_raster(text: str) -> Image.Image:
    lines = text.split("\n")
    # Arial Bold at 15 px uses the full 30-row head for the standard two-line
    # NTA layout: 15 rows + a one-row gap + 14 rows.
    font_size = TWO_LINE_FONT_SIZE if len(lines) == 2 else ONE_LINE_FONT_SIZE
    line_gap = 1
    font = _font(font_size)
    probe = Image.new("1", (1, 1), 1)
    draw = ImageDraw.Draw(probe)
    boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    widths = [box[2] - box[0] for box in boxes]
    heights = [box[3] - box[1] for box in boxes]
    content_height = sum(heights) + line_gap * (len(lines) - 1)
    image = Image.new("1", (max(widths, default=1) + 8, 30), 1)
    draw = ImageDraw.Draw(image)
    y = max(0, (30 - content_height) // 2)
    for line, box, height in zip(lines, boxes, heights):
        draw.text((4 - box[0], y - box[1]), line, font=font, fill=0)
        y += height + line_gap
    return image


def validate_barcode(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise LabelError("Shopify barcode must be a non-empty string")
    value = value.strip()
    if len(value) > 48:
        raise LabelError("Shopify barcode exceeds 48 characters")
    if any(ord(char) < 32 or ord(char) > 126 for char in value):
        raise LabelError("Code 128-B barcode supports printable ASCII only")
    return value


def code128b_symbols(value: str) -> list[int]:
    value = validate_barcode(value)
    assert value is not None
    data = [ord(char) - 32 for char in value]
    checksum = (104 + sum(position * code for position, code in enumerate(data, 1))) % 103
    return [104, *data, checksum, 106]


def _barcode_modules(value: str) -> str:
    runs: list[str] = []
    for symbol in code128b_symbols(value):
        black = True
        for width in CODE128_PATTERNS[symbol]:
            runs.append(("1" if black else "0") * int(width))
            black = not black
    quiet = "0" * BARCODE_QUIET_MODULES
    return quiet + "".join(runs) + quiet


def _render_barcode_raster(value: str) -> Image.Image:
    value = validate_barcode(value)
    assert value is not None
    modules = _barcode_modules(value)
    image = Image.new("1", (len(modules), 30), 1)
    draw = ImageDraw.Draw(image)
    for x, module in enumerate(modules):
        if module == "1":
            draw.line((x, 0, x, BARCODE_BAR_HEIGHT - 1), fill=0)
    return image


def _render_validated_content(text: str, barcode: str | None = None) -> Image.Image:
    text_image = _render_text_raster(text)
    barcode = validate_barcode(barcode)
    if barcode is not None:
        barcode_image = _render_barcode_raster(barcode)
        image = Image.new(
            "1", (text_image.width + BARCODE_GAP + barcode_image.width, 30), 1
        )
        image.paste(text_image, (0, 0))
        image.paste(barcode_image, (text_image.width + BARCODE_GAP, 0))
    else:
        image = text_image
    # The LT-200B pixels are twice as tall as they are wide; match the vendor
    # app/driver convention by doubling the horizontal raster only.
    return image.resize((image.width * 2, image.height), Image.Resampling.NEAREST)


def render_image(text: str, barcode: str | None = None) -> Image.Image:
    return _render_validated_content(validate_text(text), validate_barcode(barcode))


def format_livestock_label(payload: dict[str, Any]) -> tuple[str, str | None]:
    """Use this skill's canonical deterministic formatter, not a model."""
    result = render_label(payload)
    if result.get("status") != "READY" or not result.get("text"):
        fields = ", ".join(result.get("missing_or_invalid_fields", [])) or "unknown"
        raise LabelError(f"livestock label requires review; missing or invalid: {fields}")
    return validate_text(result["text"]), validate_barcode(result.get("shopify_barcode"))


def resolve_label_content(args: argparse.Namespace) -> tuple[str, str | None]:
    if args.text is not None:
        return validate_text(args.text), validate_barcode(getattr(args, "barcode", None))
    try:
        if args.label_file is not None:
            payload = json.loads(args.label_file.expanduser().read_text(encoding="utf-8"))
        else:
            payload = json.loads(args.label_json)
    except (OSError, json.JSONDecodeError) as exc:
        raise LabelError(f"invalid livestock label JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise LabelError("livestock label JSON must be an object")
    return format_livestock_label(payload)


def resolve_label_text(args: argparse.Namespace) -> str:
    """Backward-compatible helper for callers that only need label text."""
    return resolve_label_content(args)[0]


def save_preview(text: str, output: Path, barcode: str | None = None) -> dict[str, Any]:
    text = validate_text(text)
    barcode = validate_barcode(barcode)
    image = _render_validated_content(text, barcode)
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG")
    return {
        "operation": "preview",
        "status": "READY",
        "dry_run": True,
        "text": text,
        "shopify_barcode": barcode,
        "barcode_format": "CODE128_B" if barcode else None,
        "barcode_human_readable": False if barcode else None,
        "manual_cut_markers": text.count("|||"),
        "cutter_action": "NONE",
        "preview_path": str(output),
        "raster_pixels": {"width": image.width, "height": image.height},
    }


def bluetooth_error(exc: Exception) -> tuple[str, str]:
    message = str(exc)
    lowered = message.lower()
    if "not authorized" in lowered:
        return "BLUETOOTH_PERMISSION_REQUIRED", "Allow Bluetooth access for the OpenClaw/terminal host in macOS Privacy & Security > Bluetooth."
    if "turned off" in lowered:
        return "BLUETOOTH_OFF", "Bluetooth is off or unavailable to the local process."
    if "unsupported" in lowered:
        return "BLE_UNSUPPORTED", "CoreBluetooth did not expose a usable BLE controller to the local process."
    return "BLE_ERROR", message or exc.__class__.__name__


def _driver():
    """Load BLE dependencies only for operations that actually use Bluetooth."""
    try:
        from bleak.exc import BleakError
        from dymo_bluetooth import Result, convert_image_to_canvas, discover_printers
    except ImportError as exc:
        raise LabelError(
            "BLE dependencies are not installed; run the skill installation command"
        ) from exc
    return BleakError, Result, convert_image_to_canvas, discover_printers


async def find_printer(timeout: int, discover_printers):
    printers = await discover_printers(max_timeout=timeout, ensure_mac=False)
    return printers[0] if printers else None


def printer_identity(printer: Any) -> dict[str, Any]:
    device = printer._impl
    return {"name": getattr(device, "name", None), "address": getattr(device, "address", None)}


async def status_operation(timeout: int) -> tuple[dict[str, Any], int]:
    BleakError, _, _, discover_printers = _driver()
    try:
        printer = await find_printer(timeout, discover_printers)
        if printer is None:
            return ({
                "operation": "printer-status",
                "status": "UNAVAILABLE",
                "code": "PRINTER_NOT_FOUND",
                "message": "No advertising LetraTag 200B was found. Turn it on and keep it nearby.",
            }, 1)
        try:
            await asyncio.wait_for(printer.connect(), timeout=15)
            return ({
                "operation": "printer-status",
                "status": "READY",
                "connection": "BLE_DIRECT",
                "printer": printer_identity(printer),
                "limitations": ["Cassette presence and battery condition are confirmed only by a print result."],
            }, 0)
        finally:
            await printer.disconnect()
    except (BleakError, asyncio.TimeoutError, OSError) as exc:
        code, message = bluetooth_error(exc)
        return ({"operation": "printer-status", "status": "UNAVAILABLE", "code": code, "message": message}, 1)


async def print_operation(text: str, barcode: str | None, timeout: int) -> tuple[dict[str, Any], int]:
    BleakError, Result, convert_image_to_canvas, discover_printers = _driver()
    text = validate_text(text)
    barcode = validate_barcode(barcode)
    image = _render_validated_content(text, barcode)
    canvas = convert_image_to_canvas(image, dither=False, trim=False)
    try:
        printer = await find_printer(timeout, discover_printers)
        if printer is None:
            return ({
                "operation": "print",
                "status": "FAILED",
                "code": "PRINTER_NOT_FOUND",
                "message": "No advertising LetraTag 200B was found. No print data was sent.",
            }, 1)
        try:
            await asyncio.wait_for(printer.connect(), timeout=15)
            result = await asyncio.wait_for(printer.print(canvas), timeout=PRINT_REPLY_TIMEOUT)
        finally:
            await printer.disconnect()
    except (BleakError, asyncio.TimeoutError, OSError) as exc:
        code, message = bluetooth_error(exc)
        return ({"operation": "print", "status": "FAILED", "code": code, "message": message}, 1)
    except Exception as exc:
        return ({"operation": "print", "status": "FAILED", "code": "PRINT_ERROR", "message": str(exc)}, 1)

    success = result in (Result.SUCCESS, Result.SUCCESS_LOW_BATTERY)
    payload = {
        "operation": "print",
        "status": "PRINTED" if success else "FAILED",
        "driver_result": result.name,
        "printer": printer_identity(printer),
        "text": text,
        "shopify_barcode": barcode,
        "barcode_format": "CODE128_B" if barcode else None,
        "barcode_human_readable": False if barcode else None,
        "manual_cut_markers": text.count("|||"),
        "cutter_action": "NONE",
    }
    if result == Result.SUCCESS_LOW_BATTERY:
        payload["warning"] = "Print completed, but the printer reported low battery."
    elif not success:
        payload["message"] = "The printer returned a failure result. Check lid, cassette, and all four batteries."
    return payload, 0 if success else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nta-label-print")
    sub = parser.add_subparsers(dest="operation", required=True)
    status = sub.add_parser("printer-status", help="Scan and connect without printing")
    status.add_argument("--timeout", type=int, default=SCAN_TIMEOUT)
    preview = sub.add_parser("preview", help="Render a PNG without Bluetooth or printing")
    preview_input = preview.add_mutually_exclusive_group(required=True)
    preview_input.add_argument("--text")
    preview_input.add_argument("--label-json", help="Structured livestock label JSON")
    preview_input.add_argument("--label-file", type=Path, help="Path to structured livestock label JSON")
    preview.add_argument("--barcode", help="Code 128-B value; used only with --text")
    preview.add_argument("--output", type=Path, required=True)
    printing = sub.add_parser("print", help="Print over BLE, or render only with --dry-run")
    print_input = printing.add_mutually_exclusive_group(required=True)
    print_input.add_argument("--text")
    print_input.add_argument("--label-json", help="Structured livestock label JSON")
    print_input.add_argument("--label-file", type=Path, help="Path to structured livestock label JSON")
    printing.add_argument("--barcode", help="Code 128-B value; used only with --text")
    printing.add_argument("--timeout", type=int, default=SCAN_TIMEOUT)
    printing.add_argument("--confirm", action="store_true", help="Required for a physical print")
    printing.add_argument("--dry-run", action="store_true", help="Render and validate without scanning or printing")
    printing.add_argument("--preview-output", type=Path, default=Path("/tmp/nta-label-print-preview.png"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.operation == "preview":
            text, barcode = resolve_label_content(args)
            emit(save_preview(text, args.output, barcode))
            return 0
        if args.operation == "printer-status":
            if not 1 <= args.timeout <= 60:
                raise LabelError("timeout must be between 1 and 60 seconds")
            payload, code = asyncio.run(status_operation(args.timeout))
            emit(payload, error=code != 0)
            return code
        text, barcode = resolve_label_content(args)
        if args.dry_run:
            payload = save_preview(text, args.preview_output, barcode)
            payload.update({"operation": "print", "status": "DRY_RUN", "physical_print": False})
            emit(payload)
            return 0
        if not args.confirm:
            raise LabelError("physical printing requires --confirm; use --dry-run to validate safely")
        if not 1 <= args.timeout <= 60:
            raise LabelError("timeout must be between 1 and 60 seconds")
        payload, code = asyncio.run(print_operation(text, barcode, args.timeout))
        emit(payload, error=code != 0)
        return code
    except LabelError as exc:
        emit({"operation": args.operation, "status": "REVIEW_REQUIRED", "code": "INVALID_LABEL", "message": str(exc)}, error=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
