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
    actual = f"{provider}/{model}"
    if actual not in route["eligible_routes"]:
        raise ValueError("executed vision model is outside the resolved route")
    return {**route, "actual_provider": provider, "actual_model": model,
            "fallback_used": actual != route["requested_route"], "execution_attested": True}
