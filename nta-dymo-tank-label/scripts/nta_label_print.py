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


def _render_validated_text(text: str) -> Image.Image:
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
    # The LT-200B pixels are twice as tall as they are wide; match the vendor
    # app/driver convention by doubling the horizontal raster only.
    return image.resize((image.width * 2, image.height), Image.Resampling.NEAREST)


def render_image(text: str) -> Image.Image:
    return _render_validated_text(validate_text(text))


def format_livestock_label(payload: dict[str, Any]) -> str:
    """Use this skill's canonical deterministic formatter, not a model."""
    result = render_label(payload)
    if result.get("status") != "READY" or not result.get("text"):
        fields = ", ".join(result.get("missing_or_invalid_fields", [])) or "unknown"
        raise LabelError(f"livestock label requires review; missing or invalid: {fields}")
    return validate_text(result["text"])


def resolve_label_text(args: argparse.Namespace) -> str:
    if args.text is not None:
        return validate_text(args.text)
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


def save_preview(text: str, output: Path) -> dict[str, Any]:
    text = validate_text(text)
    image = _render_validated_text(text)
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG")
    return {
        "operation": "preview",
        "status": "READY",
        "dry_run": True,
        "text": text,
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


async def print_operation(text: str, timeout: int) -> tuple[dict[str, Any], int]:
    BleakError, Result, convert_image_to_canvas, discover_printers = _driver()
    text = validate_text(text)
    image = _render_validated_text(text)
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
    preview.add_argument("--output", type=Path, required=True)
    printing = sub.add_parser("print", help="Print over BLE, or render only with --dry-run")
    print_input = printing.add_mutually_exclusive_group(required=True)
    print_input.add_argument("--text")
    print_input.add_argument("--label-json", help="Structured livestock label JSON")
    print_input.add_argument("--label-file", type=Path, help="Path to structured livestock label JSON")
    printing.add_argument("--timeout", type=int, default=SCAN_TIMEOUT)
    printing.add_argument("--confirm", action="store_true", help="Required for a physical print")
    printing.add_argument("--dry-run", action="store_true", help="Render and validate without scanning or printing")
    printing.add_argument("--preview-output", type=Path, default=Path("/tmp/nta-label-print-preview.png"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.operation == "preview":
            emit(save_preview(resolve_label_text(args), args.output))
            return 0
        if args.operation == "printer-status":
            if not 1 <= args.timeout <= 60:
                raise LabelError("timeout must be between 1 and 60 seconds")
            payload, code = asyncio.run(status_operation(args.timeout))
            emit(payload, error=code != 0)
            return code
        text = resolve_label_text(args)
        if args.dry_run:
            payload = save_preview(text, args.preview_output)
            payload.update({"operation": "print", "status": "DRY_RUN", "physical_print": False})
            emit(payload)
            return 0
        if not args.confirm:
            raise LabelError("physical printing requires --confirm; use --dry-run to validate safely")
        if not 1 <= args.timeout <= 60:
            raise LabelError("timeout must be between 1 and 60 seconds")
        payload, code = asyncio.run(print_operation(text, args.timeout))
        emit(payload, error=code != 0)
        return code
    except LabelError as exc:
        emit({"operation": args.operation, "status": "REVIEW_REQUIRED", "code": "INVALID_LABEL", "message": str(exc)}, error=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
