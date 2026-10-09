#!/usr/bin/env python3
"""Run auditable Betta image review through OpenClaw's provider inference CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Empty means adaptive-model-router resolves the live general inference route.
# BETTA_VISION_MODELS/--models is an explicit one-off operator override.
DEFAULT_MODELS = ""
FEMALE_ACCEPT = 0.85

CATALOGUE_PROMPT = (
    "JSON only. Labelled Betta source. Return {\"tank_id\":\"\",\"tank_confidence\":0.0,"
    "\"photo_date\":\"YYYY-MM-DD\",\"date_confidence\":0.0,\"one_fish_visible\":true,"
    "\"fish_name\":\"\",\"tail_type\":\"\",\"sex\":null,\"sex_confidence\":0.0,"
    "\"uncertainty_reasons\":[]}. Visible evidence only. No adjacent-label inference. "
    "fish_name is the colour/pattern/descriptive fish name only: never include tank number, tail type, Male, or Female. "
    "tail_type is the visible tail/form name only, written in full (for example Halfmoon or Halfmoon Plakat), never an abbreviation. "
    "Return sex as Female only when confidently supported by the image; otherwise return null. "
    "Do not compose the Shopify title; deterministic code owns title formatting."
)

QA_PROMPT = (
    "JSON only. Order: source, hero, original. Return {\"assertions\":{"
    "\"same_identity\":\"PASS|FAIL\",\"body_anatomy\":\"PASS|FAIL\","
    "\"scale_markings\":\"PASS|FAIL\",\"regional_colour\":\"PASS|FAIL\","
    "\"tail_fins_pose\":\"PASS|FAIL\",\"complete_framing\":\"PASS|FAIL\","
    "\"realistic_texture\":\"PASS|FAIL\",\"hero_composition\":\"PASS|FAIL\","
    "\"label\":\"PASS|FAIL\",\"reference_integrity\":\"PASS|FAIL\"},"
    "\"overall\":\"PASS|FAIL\",\"reasons\":[]}. Third image must be full original source. "
    "Fail uncertain identity. Apply NTA Betta image standard. No invented evidence."
)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _confidence(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def compose_title(output: dict) -> dict:
    tank_id = "".join(str(output.get("tank_id") or "").split())
    fish_name = " ".join(str(output.get("fish_name") or "").split())
    tail_type = " ".join(str(output.get("tail_type") or "").split())
    if not tank_id or not fish_name or not tail_type:
        raise ValueError("tank_id, fish_name and tail_type are required to compose Betta title")
    female_supported = (
        str(output.get("sex") or "").strip().casefold() == "female"
        and _confidence(output.get("sex_confidence")) >= FEMALE_ACCEPT
    )
    sex = "Female" if female_supported else "Male"
    title = f"{tank_id} - {fish_name} {tail_type} {sex}"
    output = dict(output)
    output["tank_id"] = tank_id
    output["fish_name"] = fish_name
    output["tail_type"] = tail_type
    output["sex"] = sex
    output["proposed_title"] = title
    output["title"] = title
    return output


def normalized_usage(envelope: dict) -> dict:
    outputs = envelope.get("outputs") or []
    output_usage = outputs[0].get("usage", {}) if outputs and isinstance(outputs[0], dict) else {}
    usage = envelope.get("usage") or output_usage or {}
    if not isinstance(usage, dict):
        usage = {}
    token_keys = ("input_tokens", "prompt_tokens", "output_tokens", "completion_tokens")
    token_usage_reported = any(key in usage and usage.get(key) is not None for key in token_keys)
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
    result = dict(usage)
    try:
        result["tokens_input"] = max(0, int(input_tokens))
    except (TypeError, ValueError):
        result["tokens_input"] = 0
    try:
        result["tokens_output"] = max(0, int(output_tokens))
    except (TypeError, ValueError):
        result["tokens_output"] = 0
    result["token_usage_reported"] = token_usage_reported
    return result


def run_review(files: list[Path], mode: str, agent: str, models: list[str]) -> dict:
    prompt = CATALOGUE_PROMPT if mode == "catalogue" else QA_PROMPT
    errors = []
    child_env = os.environ.copy()
    preferred = ["/opt/homebrew/opt/node/bin", "/opt/homebrew/bin"]
    child_env["PATH"] = os.pathsep.join(preferred + child_env.get("PATH", "").split(os.pathsep))
    for model in (models or [None]):
        cmd = ["openclaw", "infer", "model", "run", "--agent", agent]
        if model:
            cmd.extend(["--model", model])
        cmd.extend(["--prompt", prompt, "--json"])
        for path in files:
            cmd.extend(["--file", str(path)])
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=child_env)
        try:
            envelope = json.loads(completed.stdout)
        except json.JSONDecodeError:
            envelope = {}
        usage = normalized_usage(envelope)
        if completed.returncode == 0 and envelope.get("ok") and envelope.get("outputs"):
            try:
                output = json.loads(envelope["outputs"][0]["text"])
                if mode == "catalogue":
                    output = compose_title(output)
            except (KeyError, json.JSONDecodeError, TypeError, ValueError) as exc:
                errors.append({"model": model, "error": f"invalid structured output: {exc}", "usage": usage})
                continue
            # Attest what actually executed; the requested override is not proof.
            provider = envelope.get("provider") or "unknown"
            resolved_model = envelope.get("model") or "unknown"
            return {
                "provider": provider,
                "model": resolved_model,
                "call_id": str(uuid.uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "input_hashes": [digest(path) for path in files],
                "usage": usage,
                "output": output,
                **({
                    "assertions": output.get("assertions"),
                    "overall": output.get("overall"),
                } if mode == "qa" else {}),
                "attempts": errors,
            }
        message = envelope.get("error", {}).get("message") or completed.stderr[-1000:] or "unknown provider failure"
        errors.append({"model": model, "error": message, "usage": usage})
    raise RuntimeError(json.dumps({"error": "no vision reviewer succeeded", "attempts": errors}))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("catalogue", "qa"), required=True)
    parser.add_argument("--file", action="append", type=Path, required=True)
    parser.add_argument("--agent", default="fred")
    parser.add_argument("--models", default=os.getenv("BETTA_VISION_MODELS", DEFAULT_MODELS))
    args = parser.parse_args()
    expected = 1 if args.mode == "catalogue" else 3
    if len(args.file) != expected or not all(path.is_file() for path in args.file):
        print(f"expected {expected} existing image file(s)", file=sys.stderr)
        return 2
    try:
        print(json.dumps(run_review(args.file, args.mode, args.agent, [m.strip() for m in args.models.split(",") if m.strip()]), sort_keys=True))
        return 0
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
