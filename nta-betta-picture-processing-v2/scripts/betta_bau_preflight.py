"""Read-only readiness probe usable in the launchd user context."""
import argparse
import json
import os
import sqlite3
import subprocess
from pathlib import Path

from betta_bau import load_config, validate_config
from betta_vision_route import resolve_route


def run(config):
    paths = config["paths"]
    checks = {"configuration": not validate_config(config, production=True)}
    from PIL import Image
    checks["image_runtime"] = Image.new("RGB", (1, 1)).size == (1, 1)
    checks["intake_readable"] = Path(paths["intake"]).is_dir() and os.access(paths["intake"], os.R_OK | os.W_OK)
    con = sqlite3.connect(f"file:{paths['telemetry']}?mode=ro", uri=True)
    try:
        checks["telemetry_integrity"] = con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        con.close()
    key = subprocess.run(["/usr/bin/security", "find-generic-password", "-a", "XAI_API_KEY",
                          "-s", "nta-betta-xai", "-w"], capture_output=True, timeout=15)
    checks["keychain_readable"] = key.returncode == 0 and bool(key.stdout.strip())
    del key
    route = resolve_route()
    checks["vision_route"] = bool(route["eligible_routes"])
    environment = dict(os.environ)
    environment["BETTA_SHOPIFY_ENV"] = paths["env"]
    environment["BETTA_EXPECTED_SHOP"] = "nano-tanks-australia-aquarium-shop.myshopify.com"
    result = subprocess.run([paths["node"], str(Path(__file__).parent / "shopify_live.mjs"), "preflight"],
                            capture_output=True, text=True, env=environment, timeout=45)
    shop = json.loads(result.stdout) if result.returncode == 0 else {}
    identity = shop.get("shop", {})
    checks["shopify_identity"] = shop.get("ok") is True and identity.get("id") == "gid://shopify/Shop/60857712849"
    result = subprocess.run([paths["openclaw"], "message", "channel", "info", "--channel", "discord",
                            "--target", config["discord"]["target"], "--json"], capture_output=True,
                            text=True, timeout=45)
    discord = json.loads(result.stdout) if result.returncode == 0 else {}
    channel = discord.get("payload", {}).get("channel", {})
    checks["discord_identity"] = channel.get("id") == "1542019252683546645" and channel.get("name") == "betta-processing"
    return {"ok": all(checks.values()), "checks": checks, "shop": identity,
            "vision_route": route, "paid_calls": 0, "shopify_mutations": 0, "discord_sends": 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = run(load_config(args.config))
    except Exception as exc:
        report = {"ok": False, "error_type": type(exc).__name__, "paid_calls": 0,
                  "shopify_mutations": 0, "discord_sends": 0}
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
