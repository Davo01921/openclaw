"""Read-only resolution of the canonical general vision routing policy."""
import json
import os
import subprocess
from pathlib import Path


def resolve_route(agent="fred", *, config_path=None, inspect=None):
    config_path = Path(config_path or Path.home() / ".openclaw" / "openclaw.json")
    config = json.loads(config_path.read_text())
    agents = config.get("agents", {})
    entry = agents.get("entries", {}).get(agent)
    if not isinstance(entry, dict):
        raise ValueError("configured vision agent is missing")
    model = entry.get("model") or agents.get("defaults", {}).get("model")
    if not isinstance(model, dict):
        raise ValueError("vision route must preserve a configured fallback chain")
    routes = [model.get("primary"), *(model.get("fallbacks") or [])]
    if len(routes) != 3 or [str(x).split("/", 1)[0] for x in routes] != ["openai", "qwen-token-plan", "qwen"]:
        raise ValueError("vision route must preserve OpenAI, Qwen Token Plan, Qwen API order")
    def inspect_live(route):
        result = subprocess.run([os.getenv("BETTA_OPENCLAW", "/opt/homebrew/bin/openclaw"),
                                 "infer", "model", "inspect", "--model", route, "--json"],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise ValueError("vision model catalogue unavailable")
        return json.loads(result.stdout)
    capabilities = [(inspect or inspect_live)(route) for route in routes]
    for route, capability in zip(routes, capabilities):
        if capability.get("status") != "available" or "image" not in capability.get("input", []):
            raise ValueError(f"vision capability unavailable for configured route {route}")
    return {"class": "STANDARD", "capability_requirements": ["image", "structured_output"],
            "agent": agent, "requested_route": routes[0], "eligible_routes": routes,
            "authority": "adaptive-model-router/v2.1", "execution_attested": False}


def attest(route, provider, model):
    if not isinstance(route, dict) or route.get("execution_attested") is not False:
        raise ValueError("vision route is not an unresolved canonical route")
    if not isinstance(provider, str) or not provider.strip() or provider.casefold() == "unknown":
        raise ValueError("executed vision provider is unavailable")
    if not isinstance(model, str) or not model.strip() or model.casefold() == "unknown":
        raise ValueError("executed vision model is unavailable")
    actual = f"{provider}/{model}"
    if actual not in route["eligible_routes"]:
        raise ValueError("executed vision model is outside the resolved route")
    return {**route, "actual_provider": provider, "actual_model": model,
            "fallback_used": actual != route["requested_route"], "execution_attested": True}


def validate_attestation(routing, provider, model):
    """Validate a persisted execution attestation without resolving live config again."""
    if not isinstance(routing, dict) or routing.get("execution_attested") is not True:
        raise ValueError("vision execution attestation is missing")
    if routing.get("override") is True:
        raise ValueError("vision model overrides are outside the BAU route")
    if not isinstance(provider, str) or not provider.strip() or provider.casefold() == "unknown":
        raise ValueError("executed vision provider is unavailable")
    if not isinstance(model, str) or not model.strip() or model.casefold() == "unknown":
        raise ValueError("executed vision model is unavailable")
    if routing.get("actual_provider") != provider or routing.get("actual_model") != model:
        raise ValueError("vision route actual provider/model does not match the call receipt")
    eligible = routing.get("eligible_routes")
    if (not isinstance(eligible, list) or not eligible or
            any(not isinstance(value, str) or not value for value in eligible)):
        raise ValueError("vision eligible route set is invalid")
    actual = f"{provider}/{model}"
    if actual not in eligible:
        raise ValueError("executed vision model is outside the resolved route")
    requested = routing.get("requested_route")
    if requested not in eligible:
        raise ValueError("requested vision route is outside the eligible route set")
    if routing.get("fallback_used") is not (actual != requested):
        raise ValueError("vision fallback attestation is inconsistent")
    return routing
