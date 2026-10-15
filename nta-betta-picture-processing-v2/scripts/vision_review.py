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

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import label_identity  # noqa: E402

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

QA_PROMPT_TEMPLATE = (
    "JSON only. Order: prepared working photo (the fish as photographed, cropped and "
    "tone-adjusted), hero candidate, untouched camera original. Return {{\"assertions\":{{"
    "\"same_identity\":\"PASS|FAIL\",\"body_anatomy\":\"PASS|FAIL\","
    "\"scale_markings\":\"PASS|FAIL\",\"regional_colour\":\"PASS|FAIL\","
    "\"tail_fins_pose\":\"PASS|FAIL\",\"complete_framing\":\"PASS|FAIL\","
    "\"realistic_texture\":\"PASS|FAIL\",\"hero_composition\":\"PASS|FAIL\","
    "\"label\":\"PASS|FAIL\",\"reference_integrity\":\"PASS|FAIL\"}},"
    "\"overall\":\"PASS|FAIL\",\"reasons\":[]}}. "
    "The hero is a generated studio catalogue representation of the SAME individual fish "
    "shown in the prepared and original photographs. Judge it as a professional product "
    "photograph, not a forensic copy. The source photo may be dark, small, angled or "
    "partially obscured inside an aquarium; that alone is not a failure. The hero is "
    "produced under studio lighting on a near-black background, so it will generally "
    "appear deeper, darker, richer and more contrasty than the in-tank source; treat "
    "those tonal rendering differences as presentation, never as colour or marking "
    "failures. "
    "ACCEPTABLE and never a failure: a natural display posture with more spread fins than "
    "the source; sharper detail, cleaner texture and deeper saturation of the SAME hues; "
    "professional studio lighting; removal of tank water, debris, glare and background; "
    "fine detail that the source cannot resolve when it does not contradict visible "
    "evidence (note it in reasons instead). "
    "same_identity FAILS only when the hero contradicts visible evidence: a different "
    "colour family or swapped regional colour distribution; a different pattern class "
    "(for example solid vs marble); a different body or tail form class; or, where the "
    "source clearly shows distinctive individual markings, materially different markings. "
    "body_anatomy FAILS for structural fabrication or distortion: extra or missing fins, "
    "eyes or structures; duplicated parts; grossly changed proportions beyond what pose "
    "or angle explains. "
    "scale_markings FAILS when discrete markings visible in the source are missing or "
    "moved, or prominent new discrete patterns are added where the source visibly shows "
    "a plain coat; sharper, darker or more contrasted rendering of the SAME markings and "
    "visible scale texture is never a failure. "
    "regional_colour FAILS when the hue direction or its regional distribution is "
    "contradicted (for example red body with blue fins becoming blue body with red fins), "
    "or new dominant HUE families appear that the source visibly refutes; a darker, "
    "richer or more saturated rendering of the same hues is never a failure. "
    "tail_fins_pose FAILS only for fin-form class contradictions or malformed, torn or "
    "duplicated fin structures; pose and spread differences are acceptable. "
    "complete_framing FAILS if any fin or tail tip is cut off by the frame, or the fish "
    "is partial or too small. "
    "realistic_texture FAILS for clearly synthetic artefacts (plastic smoothing, "
    "repeating geometry, warped anatomy), not for clean professional texture. "
    "hero_composition: one centred fish on a clean near-black background with "
    "comfortable margins and no props. "
    "label: the hero's bottom label must read exactly {tank} and photo date {date}; "
    "FAIL on any label mismatch or unreadable label. "
    "reference_integrity FAILS if the hero contains tank borders, cards, hands, text, "
    "watermarks or other clutter. "
    "The third image must be the full original source. No invented evidence; no markdown."
)

PREFLIGHT_PROMPT = (
    "Inspect this *unmodified* Betta photo and return JSON only: "
    "{\"tank_id\":\"\", \"photo_date\":\"YYYY-MM-DD\", \"tank_confidence\":0.0, "
    "\"date_confidence\":0.0, \"fish_confidence\":0.0, \"one_fish_visible\":true, "
    "\"tank_bounds\":[left,top,right,bottom], \"fish_bounds\":[left,top,right,bottom], "
    "\"debris_boxes\":[], \"needs_retake\":false, \"reason\":\"\"}. "
    "Bounds are XYXY normalized fractions of the full oriented photo in [0,1]. "
    "Tank bounds must include only the photographed aquarium/water scene, not "
    "neighbouring tanks, room background or unrelated objects. Fish bounds must include "
    "*all* fins and tail extensions. Read the tank/date label from the RAW image: tank "
    "IDs are digits then BT then digits (for example 2BT14), or APE then digits (for "
    "example APE16); dates are Australian day/month/year. Never infer an adjacent tank. "
    "Debris boxes may mark only small isolated contaminant patches *well away from the "
    "fish*; never glass reflections or regions crossing fish or fins; if uncertain, "
    "return empty debris_boxes. Never propose removing disease signs, injuries, egg "
    "spots, fish colour or unique markings. If the whole tank or fish cannot be safely "
    "bounded, set confidence low or needs_retake true. Do not invent fish colour, tank "
    "number or date. No markdown."
)

PREP_QA_PROMPT = (
    "Compare the two images: (1) the unmodified camera original (it may be dark, "
    "low-detail and taken through aquarium glass); (2) the prepared working photo "
    "derived only by cropping outside the tank, bounded exposure and white-balance "
    "correction, and removal of small isolated neutral water debris outside the fish. "
    "Return JSON only: {\"overall\":\"PASS|FAIL\", \"same_fish\":true, "
    "\"full_fins\":true, \"faithful_colours\":true, \"tank_only\":true, "
    "\"lighting_usable\":true, \"no_identity_alteration\":true, \"reason\":\"\"}. "
    "PASS only if every criterion is true. same_fish: the prepared photo still shows "
    "the same individual/class of fish. full_fins: no fin or tail appears clipped by "
    "the crop. faithful_colours: no colour shift beyond mild exposure correction. "
    "tank_only: no neighbouring tanks or unrelated room scenes remain prominent "
    "(aquarium glass edges are acceptable). lighting_usable: exposure is suitable for "
    "professional reprocessing. no_identity_alteration: no fish pixels were "
    "structurally altered, no detail invented, no markings, scales or defects removed. "
    "Tone and exposure differences from the bounded correction are acceptable. "
    "Fail if uncertain. No markdown."
)

QA_FAILURE_CATEGORIES = {
    "same_identity": "identity",
    "scale_markings": "identity",
    "regional_colour": "identity",
    "label": "identity",
    "body_anatomy": "anatomy",
    "tail_fins_pose": "anatomy",
    "complete_framing": "presentation",
    "realistic_texture": "presentation",
    "hero_composition": "presentation",
    "reference_integrity": "presentation",
}


def categorise_assertions(assertions: dict) -> dict:
    """Group failed assertions by the documented calibration taxonomy (reporting only)."""
    categories = {"identity": [], "anatomy": [], "presentation": []}
    for name, value in (assertions or {}).items():
        if value != "FAIL":
            continue
        categories[QA_FAILURE_CATEGORIES.get(name, "presentation")].append(name)
    return {key: sorted(value) for key, value in categories.items()}


LABEL_PROMPT = (
    "JSON only. This is a crop of an Australian handwritten Betta tank card. "
    "Return {\"tank_id\":\"\",\"tank_confidence\":0.0,"
    "\"photo_date\":\"D/M/YYYY\",\"date_confidence\":0.0,"
    "\"visible_price\":\"\",\"reasons\":[]}. "
    "Tank IDs are digits then BT then digits (for example 2BT14), or APE then "
    "digits (for example APE16); do not turn a handwritten 5 into S. Dates are "
    "Australian day/month/year, so 9/10/2026 means 9 October 2026. "
    "visible_price is the price actually written on the card as digits only "
    "(for example 35), with no currency symbol; return an empty string when no "
    "price is clearly visible on the card. Never invent a price and never copy "
    "a price from anywhere other than the physical card. "
    "Read only the physical card. Never infer from adjacent tanks."
)


def normalize_label_output(output: dict) -> dict:
    """Canonicalise the focused label-mode output contract.

    ``visible_price`` is parsed strictly (digits/decimal only, never invented)
    and returned as a canonical string or ``None``.  Tank/date values are left
    untouched for the caller's own normalisation gates.
    """
    if not isinstance(output, dict):
        raise ValueError("label output must be a JSON object")
    result = dict(output)
    result["visible_price"] = label_identity.parse_visible_price(
        result.get("visible_price"))
    return result


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


def failed_attempts(envelope: dict) -> list[dict]:
    """Preserve provider retry usage exposed by the inference envelope."""
    candidates = envelope.get("attempts") or []
    outputs = envelope.get("outputs") or []
    if outputs and isinstance(outputs[0], dict):
        candidates = [*candidates, *(outputs[0].get("attempts") or [])]
    result = []
    for attempt in candidates:
        if not isinstance(attempt, dict):
            continue
        status = str(attempt.get("status") or attempt.get("outcome") or "").upper()
        error = attempt.get("error")
        failed = bool(error) or attempt.get("ok") is False or status in {
            "ERROR", "FAIL", "FAILED", "TIMEOUT", "UNAVAILABLE",
        }
        if not failed:
            continue
        if isinstance(error, dict):
            error = error.get("message") or json.dumps(error, sort_keys=True)
        result.append({
            "provider": attempt.get("provider"), "model": attempt.get("model"),
            "error": str(error or status or "provider attempt failed"),
            "usage": normalized_usage(attempt),
        })
    return result


def run_review(files: list[Path], mode: str, agent: str, models: list[str],
               *, expect_tank: str = "", expect_date: str = "") -> dict:
    from betta_vision_route import resolve_route, attest
    if models:
        raise RuntimeError("vision model overrides are disabled for attested BAU review")
    route = resolve_route(agent)
    if mode == "qa":
        prompt = QA_PROMPT_TEMPLATE.format(
            tank=expect_tank or "<tank shown in the source label>",
            date=expect_date or "<photo date shown in the source label>")
    else:
        prompt = {"catalogue": CATALOGUE_PROMPT, "label": LABEL_PROMPT,
                  "preflight": PREFLIGHT_PROMPT, "prep": PREP_QA_PROMPT}[mode]
    errors = []
    child_env = os.environ.copy()
    preferred = ["/opt/homebrew/opt/node/bin", "/opt/homebrew/bin"]
    child_env["PATH"] = os.pathsep.join(preferred + child_env.get("PATH", "").split(os.pathsep))
    # Multimodal structured-output calls can legitimately exceed one minute; the
    # caller applies its own bounded retries.  Keep this a hard ceiling only.
    timeout_seconds = int(os.getenv("BETTA_VISION_TIMEOUT_SECONDS", "180"))
    for model in [None]:
        cmd = [os.getenv("BETTA_OPENCLAW", "/opt/homebrew/bin/openclaw"), "infer", "model", "run", "--agent", agent]
        if model:
            cmd.extend(["--model", model])
        cmd.extend(["--prompt", prompt, "--json"])
        for path in files:
            cmd.extend(["--file", str(path)])
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds, env=child_env)
        try:
            envelope = json.loads(completed.stdout)
        except json.JSONDecodeError:
            envelope = {}
        usage = normalized_usage(envelope)
        envelope_failures = failed_attempts(envelope)
        if completed.returncode == 0 and envelope.get("ok") and envelope.get("outputs"):
            try:
                output = json.loads(envelope["outputs"][0]["text"])
                if mode == "catalogue":
                    output = compose_title(output)
                elif mode == "label":
                    output = normalize_label_output(output)
            except (KeyError, json.JSONDecodeError, TypeError, ValueError) as exc:
                errors.extend(envelope_failures)
                errors.append({
                    "provider": envelope.get("provider"),
                    "model": envelope.get("model"),
                    "error": f"invalid structured output: {exc}", "usage": usage,
                })
                continue
            # Attest what actually executed; the requested override is not proof.
            provider = envelope.get("provider") or "unknown"
            resolved_model = envelope.get("model") or "unknown"
            return {
                "provider": provider,
                "model": resolved_model,
                "call_id": str(uuid.uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "routing": attest(route, provider, resolved_model),
                "input_hashes": [digest(path) for path in files],
                "usage": usage,
                "output": output,
                **({
                    "assertions": output.get("assertions"),
                    "overall": output.get("overall"),
                } if mode == "qa" else {}),
                "attempts": [*errors, *envelope_failures],
            }
        message = envelope.get("error", {}).get("message") or completed.stderr[-1000:] or "unknown provider failure"
        errors.extend(envelope_failures)
        errors.append({"provider": envelope.get("provider"),
                       "model": envelope.get("model"),
                       "error": message, "usage": usage})
    raise RuntimeError(json.dumps({"error": "no vision reviewer succeeded", "attempts": errors}))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("catalogue", "qa", "label", "preflight", "prep"),
                        required=True)
    parser.add_argument("--file", action="append", type=Path, required=True)
    parser.add_argument("--agent", default="fred")
    parser.add_argument("--models", default=os.getenv("BETTA_VISION_MODELS", DEFAULT_MODELS))
    parser.add_argument("--expect-tank", default="")
    parser.add_argument("--expect-date", default="")
    args = parser.parse_args()
    expected = {"catalogue": 1, "label": 1, "preflight": 1, "prep": 2, "qa": 3}[args.mode]
    if len(args.file) != expected or not all(path.is_file() for path in args.file):
        print(f"expected {expected} existing image file(s)", file=sys.stderr)
        return 2
    try:
        print(json.dumps(run_review(args.file, args.mode, args.agent,
                                    [m.strip() for m in args.models.split(",") if m.strip()],
                                    expect_tank=args.expect_tank, expect_date=args.expect_date),
                         sort_keys=True))
        return 0
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
