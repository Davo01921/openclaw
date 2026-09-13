#!/usr/bin/env python3
"""Experimental Grok Imagine 2.0 renderer for NTA Betta catalogue heroes.

This script intentionally creates only the clean fish hero candidate. Exact tank/date
label rendering remains deterministic and outside the generative model.

Required environment:
    XAI_API_KEY

Optional environment:
    BETTA_GROK_COST_USD_PER_IMAGE
        Override the current fallback billed cost per generated image when xAI does
        not return a cost field. Current NTA fallback: USD 0.07 per Grok image call.

Example:
    python scripts/grok_hero.py --source 2BT31.jpg --output 2BT31-grok.png
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_URL = "https://api.x.ai/v1/images/edits"
DEFAULT_MODEL = "grok-imagine-image-2.0"
DEFAULT_GROK_COST_USD_PER_IMAGE = 0.07
DEFAULT_PROMPT = """Create a premium square catalogue hero from this exact Betta photograph.
Preserve this individual fish's identity: head/body proportions, scale layout, unique
markings, regional colour distribution, apparent tail type, fin attachment points,
and any visible identity-relevant traits. Do not substitute a generic Betta. Do not
invent markings, colours, fin rays, anatomy, damage, or micro-detail. A plausible
side-profile display posture and natural fin spread are allowed, but the fish must
remain recognizably the same individual.

Presentation target: one Betta occupying most of a 1:1 frame with comfortable space
around every fin; clean near-black seamless background; no aquarium borders, cards,
reflections, glare, debris, neighbouring tanks, hands, text, logos, labels, or props.
Use realistic clarity, natural texture, balanced exposure, and strong but believable
colour. This is a faithful catalogue representation of the supplied fish, not a new
or idealized specimen. Output no text in the image."""


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def request_candidate(source: Path, model: str, quality: str, timeout: int) -> tuple[bytes, dict]:
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        raise RuntimeError("XAI_API_KEY is not set")

    payload = {
        "model": model,
        "prompt": DEFAULT_PROMPT,
        "image": {"url": data_uri(source), "type": "image_url"},
        "aspect_ratio": "1:1",
        "resolution": "2k",
        "quality": quality,
        "response_format": "b64_json",
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        envelope = json.loads(response.read().decode("utf-8"))

    if not envelope.get("data"):
        raise RuntimeError(f"xAI returned no image data: {json.dumps(envelope)[:1000]}")
    item = envelope["data"][0]
    if item.get("b64_json"):
        image_bytes = base64.b64decode(item["b64_json"])
    elif item.get("url"):
        with urllib.request.urlopen(item["url"], timeout=timeout) as image_response:
            image_bytes = image_response.read()
    else:
        raise RuntimeError("xAI response contained neither b64_json nor url")
    return image_bytes, envelope


def normalize_png(image_bytes: bytes, output: Path) -> None:
    try:
        from PIL import Image
        from io import BytesIO
    except ImportError as exc:
        raise RuntimeError("Pillow is required to normalize the Grok output to 2048x2048 PNG") from exc

    with Image.open(BytesIO(image_bytes)) as image:
        image = image.convert("RGB")
        if image.size != (2048, 2048):
            image = image.resize((2048, 2048), Image.Resampling.LANCZOS)
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output, format="PNG", optimize=True)


def _number(mapping: dict, keys: tuple[str, ...], default: float = 0.0) -> float:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return default


def normalized_usage(envelope: dict) -> dict:
    usage = envelope.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    token_keys = ("input_tokens", "prompt_tokens", "output_tokens", "completion_tokens")
    token_usage_reported = any(key in usage and usage.get(key) is not None for key in token_keys)
    input_tokens = int(_number(usage, ("input_tokens", "prompt_tokens"), 0))
    output_tokens = int(_number(usage, ("output_tokens", "completion_tokens"), 0))

    provider_cost_keys = ("cost_usd", "total_cost_usd", "cost", "total_cost")
    provider_has_cost = any(usage.get(key) is not None for key in provider_cost_keys)
    cost = _number(usage, provider_cost_keys, 0) if provider_has_cost else None
    cost_source = "provider" if provider_has_cost else "unavailable"
    if cost is None:
        configured = os.getenv("BETTA_GROK_COST_USD_PER_IMAGE")
        if configured not in (None, ""):
            try:
                cost = max(0.0, float(configured))
                cost_source = "configured"
            except ValueError:
                cost = None
                cost_source = "invalid_configuration"
        else:
            cost = DEFAULT_GROK_COST_USD_PER_IMAGE
            cost_source = "nta_default_0.07"

    result = dict(usage)
    result.update({
        "tokens_input": input_tokens,
        "tokens_output": output_tokens,
        "token_usage_reported": token_usage_reported,
        "grokai_cost": cost,
        "grokai_cost_currency": "USD",
        "cost_source": cost_source,
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default=os.getenv("BETTA_GROK_IMAGE_MODEL", DEFAULT_MODEL))
    parser.add_argument("--quality", choices=("low", "medium"), default=os.getenv("BETTA_GROK_QUALITY", "low"))
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    if not args.source.is_file():
        print(f"source image not found: {args.source}", file=sys.stderr)
        return 2

    try:
        raw, envelope = request_candidate(args.source, args.model, args.quality, args.timeout)
        normalize_png(raw, args.output)
        usage = normalized_usage(envelope)
        record = {
            "provider": "xai",
            "model": args.model,
            "quality": args.quality,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_path": str(args.source),
            "source_sha256": digest(args.source),
            "output_path": str(args.output),
            "output_sha256": digest(args.output),
            "output_dimensions": [2048, 2048],
            "purpose": "experimental_betta_hero_candidate",
            "qa_required": True,
            "tokens_input": usage["tokens_input"],
            "tokens_output": usage["tokens_output"],
            "token_usage_reported": usage["token_usage_reported"],
            "grokai_cost": usage["grokai_cost"],
            "grokai_cost_currency": usage["grokai_cost_currency"],
            "grokai_cost_source": usage["cost_source"],
            "usage": usage,
        }
        print(json.dumps(record, sort_keys=True))
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
