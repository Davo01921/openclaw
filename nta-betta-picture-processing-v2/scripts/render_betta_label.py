#!/usr/bin/env python3
"""Render deterministic tank/date labels onto approved Betta hero candidates."""

import argparse
import re
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def render(source, output, tank, photo_date):
    tank = tank.upper().replace(" ", "")

    if not re.fullmatch(r"[0-9]+BT[0-9]+", tank):
        raise ValueError("Invalid tank number")

    date = datetime.strptime(photo_date, "%Y-%m-%d")
    display_date = f"{date.day}/{date.month}/{date.year}"

    with Image.open(source) as original:
        image = original.convert("RGB")

    if image.size != (2048, 2048):
        raise ValueError("Hero image must be 2048 x 2048")

    draw = ImageDraw.Draw(image)

    font_path = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
    regular_path = "/System/Library/Fonts/Supplemental/Arial.ttf"

    font_tank = ImageFont.truetype(font_path, 56)
    font_date = ImageFont.truetype(regular_path, 34)

    x, y = 70, 1830
    width, height = 610, 155

    draw.rounded_rectangle(
        (x, y, x + width, y + height),
        radius=20,
        fill=(12, 14, 18),
        outline=(90, 95, 105),
        width=2,
    )

    draw.text(
        (x + 28, y + 15),
        tank,
        font=font_tank,
        fill=(255, 255, 255),
    )

    draw.text(
        (x + 28, y + 93),
        f"PHOTO DATE: {display_date}",
        font=font_date,
        fill=(210, 215, 220),
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tank", required=True)
    parser.add_argument("--photo-date", required=True)
    args = parser.parse_args()

    render(args.source, args.output, args.tank, args.photo_date)

    print(f"PASS: Labelled hero saved to {args.output}")
