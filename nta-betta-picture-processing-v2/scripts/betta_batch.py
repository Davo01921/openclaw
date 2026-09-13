#!/usr/bin/env python3
"""Fail-closed state/ledger engine for NTA Betta processing.

This helper never calls Shopify. It validates evidence, controls state transitions,
and emits an authorised mutation envelope for the OpenClaw Shopify adapter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ITEM_STATES = (
    "DISCOVERED", "SAVED", "VISUAL_PENDING", "VISUAL_ACCEPTED",
    "PRODUCT_RESOLVED", "CSV_READY", "IMAGE_CANDIDATE_READY",
    "IMAGE_QA_PENDING", "IMAGES_READY", "MUTATION_PENDING", "MUTATED",
    "VERIFIED", "PASS", "ARCHIVED",
)
TERMINAL = {"BLOCKED_VISUAL", "BLOCKED_PRODUCT", "FIX_REQUIRED"}
NEXT = dict(zip(ITEM_STATES, ITEM_STATES[1:]))
QA_DETERMINISTIC = {"dimensions", "filenames", "label", "framing", "original_reference_hash"}
QA_VISUAL = {
    "same_identity", "body_anatomy", "scale_markings", "regional_colour",
    "tail_fins_pose", "complete_framing", "realistic_texture",
    "hero_composition", "label", "reference_integrity",
}
PROTECTED = {"description", "price", "cost", "vendor", "product_type", "handle", "status"}
AUTHORISED = {"title", "arrival_date", "inventory", "media"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SEX_RE = re.compile(r"\b(?:male|female)\b", re.IGNORECASE)
FEMALE_ACCEPT = 0.85


class LedgerError(ValueError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise LedgerError(message)


def confidence(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def canonical_sex(cat: dict) -> str:
    """NTA rule: only a confident Female classification changes the default; otherwise Male."""
    value = cat.get("sex")
    if (
        isinstance(value, str)
        and value.strip().casefold() == "female"
        and confidence(cat.get("sex_confidence")) >= FEMALE_ACCEPT
    ):
        return "Female"
    return "Male"


def expected_catalogue_title(cat: dict) -> str:
    """Build the only Shopify title shape allowed for an individual Betta."""
    tank_id = str(cat.get("tank_id") or "").strip()
    fish_name = " ".join(str(cat.get("fish_name") or "").split())
    tail_type = " ".join(str(cat.get("tail_type") or "").split())
    require(tank_id, "catalogue tank_id required for title")
    require(fish_name, "catalogue fish_name required for title")
    require(tail_type, "catalogue tail_type required for title")
    require(" - " not in fish_name and " - " not in tail_type, "title components must not contain title separator")
    require(SEX_RE.search(fish_name) is None, "fish_name must not contain Male/Female")
    require(SEX_RE.search(tail_type) is None, "tail_type must not contain Male/Female")
    require(not fish_name.casefold().endswith(tail_type.casefold()), "fish_name must not duplicate tail_type")
    return f"{tank_id} - {fish_name} {tail_type} {canonical_sex(cat)}"


def validate_file(asset: dict, role: str) -> None:
    require(isinstance(asset, dict), f"{role}: missing asset record")
    path = asset.get("path")
    digest = asset.get("sha256")
    require(path and digest, f"{role}: path/hash required")
    require(Path(path).is_file(), f"{role}: file missing: {path}")
    require(sha256(path) == digest, f"{role}: hash mismatch")


def product_snapshot_ready(item: dict) -> bool:
    product = item.get("product", {})
    before = product.get("before")
    return bool(product.get("id") and isinstance(before, dict) and PROTECTED <= set(before))


def hero_asset_ready(item: dict) -> bool:
    try:
        validate_file(item.get("images", {}).get("hero", {}), "hero")
        return True
    except (LedgerError, OSError):
        return False


def parallel_preparation_plan(data: dict, workers: int = 4) -> dict:
    """Plan independent Shopify-resolution and Grok-hero work after visual acceptance.

    Existing valid outputs are never scheduled again. This makes a rerun resume from
    the missing/failed branch instead of repeating already successful work.
    """
    workers = max(1, min(int(workers), 4))
    tasks: list[dict] = []
    ready_to_join: list[str] = []

    for item in data.get("items", []):
        if item.get("state") != "VISUAL_ACCEPTED":
            continue
        product_ready = product_snapshot_ready(item)
        hero_ready = hero_asset_ready(item)
        if product_ready and hero_ready:
            ready_to_join.append(item["id"])
            continue
        if not product_ready:
            tasks.append({
                "item_id": item["id"],
                "operation": "shopify_resolve",
                "checkpoint": "VISUAL_ACCEPTED",
            })
        if not hero_ready:
            tasks.append({
                "item_id": item["id"],
                "operation": "grok_hero",
                "checkpoint": "VISUAL_ACCEPTED",
            })

    return {
        "max_concurrency": workers,
        "tasks": tasks,
        "ready_to_join": ready_to_join,
        "join_target": "PRODUCT_RESOLVED",
    }


def validate_vision_call(call: dict, required_assertions: set[str] | None = None) -> None:
    for key in ("provider", "model", "call_id", "timestamp", "input_hashes", "output"):
        require(call.get(key), f"vision: {key} required")
    require(isinstance(call["input_hashes"], list) and call["input_hashes"], "vision: input hashes required")
    if required_assertions is not None:
        assertions = call.get("assertions")
        require(isinstance(assertions, dict), "vision: assertions required")
        require(set(assertions) == required_assertions, "vision: assertion set mismatch")
        require(all(value == "PASS" for value in assertions.values()), "vision: every assertion must PASS")
        require(call.get("overall") == "PASS", "vision: overall must PASS")


def validate_item(item: dict) -> None:
    require(item.get("id"), "item id required")
    require(item.get("state") in set(ITEM_STATES) | TERMINAL, "invalid item state")
    require(isinstance(item.get("history"), list) and item["history"], "state history required")
    validate_file(item["source"], "source")
    if item["state"] in ITEM_STATES[ITEM_STATES.index("VISUAL_ACCEPTED"):]:
        cat = item.get("catalogue", {})
        require(cat.get("tank_id") and cat.get("title"), "accepted catalogue tank/title required")
        require(cat.get("tank_id") == item.get("id"), "catalogue tank_id must equal item id")
        require(DATE_RE.match(cat.get("photo_date", "")) is not None, "accepted physical photo date required")
        require(cat.get("title") == expected_catalogue_title(cat),
                "catalogue title must exactly match '<Tank Number> - <Fish Name> <Tail Type> <Male/Female>'")
        validate_vision_call(cat.get("evidence", {}))
    if item["state"] in ITEM_STATES[ITEM_STATES.index("PRODUCT_RESOLVED"):]:
        require(product_snapshot_ready(item), "product id/snapshot required")
        # PRODUCT_RESOLVED is also the join point for parallel preparation. A valid
        # hero must already exist so Shopify resolution and Grok generation can run
        # independently while the item remains VISUAL_ACCEPTED.
        validate_file(item.get("images", {}).get("hero", {}), "hero")
    if item["state"] in ITEM_STATES[ITEM_STATES.index("IMAGE_CANDIDATE_READY"):]:
        validate_file(item["images"]["hero"], "hero")
    if item["state"] in ITEM_STATES[ITEM_STATES.index("IMAGES_READY"):]:
        qa = item.get("image_qa", {})
        require(set(qa.get("deterministic", {})) == QA_DETERMINISTIC, "QA deterministic assertion set mismatch")
        require(all(v == "PASS" for v in qa["deterministic"].values()), "deterministic QA failed")
        validate_vision_call(qa.get("visual", {}), QA_VISUAL)
        require(qa.get("outcome") == "PASS", "image QA outcome must PASS")
        expected = [item["source"]["sha256"], item["images"]["hero"]["sha256"], item["source"]["sha256"]]
        require(qa["visual"]["input_hashes"] == expected, "QA input hashes/version mismatch")
    if item["state"] in ITEM_STATES[ITEM_STATES.index("MUTATION_PENDING"):]:
        validate_mutation(item)
    if item["state"] in ITEM_STATES[ITEM_STATES.index("VERIFIED"):]:
        verify_readback(item)


def validate_mutation(item: dict) -> None:
    mutation = item.get("mutation", {})
    require(set(mutation) == AUTHORISED, "mutation contains missing or unauthorised keys")
    cat = item["catalogue"]
    required_title = expected_catalogue_title(cat)
    require(cat["title"] == required_title, "catalogue title violates deterministic title contract")
    require(mutation["title"] == required_title, "mutation title violates deterministic title contract")
    require(mutation["arrival_date"] == cat["photo_date"], "arrival date must equal physical photo date")
    require(mutation["inventory"] == 1, "inventory must equal 1")
    approved = [item["images"]["hero"]["sha256"], item["source"]["sha256"]]
    require(mutation["media"] == approved, "mutation media must be approved hero/source hashes in order")


def verify_readback(item: dict) -> None:
    before = item["product"]["before"]
    after = item.get("readback", {})
    require(after.get("product_id") == item["product"]["id"], "read-back product id mismatch")
    for key in PROTECTED:
        require(after.get(key) == before.get(key), f"protected field changed: {key}")
    require(after.get("title") == expected_catalogue_title(item["catalogue"]), "read-back title mismatch")
    require(after.get("title") == item["mutation"]["title"], "read-back mutation title mismatch")
    require(after.get("arrival_date") == item["mutation"]["arrival_date"], "read-back arrival date mismatch")
    require(after.get("inventory") == 1, "read-back inventory mismatch")
    require(
        after.get("media_hashes", [])[:2] == [item["images"]["hero"]["sha256"], item["source"]["sha256"]],
        "read-back media/order mismatch",
    )


def validate_ledger(data: dict) -> None:
    require(data.get("schema_version") == 2, "unsupported ledger schema")
    require(data.get("batch_id") and isinstance(data.get("items"), list) and data["items"], "batch/items required")
    ids, calls, product_ids = set(), set(), set()
    for item in data["items"]:
        validate_item(item)
        require(item["id"] not in ids, "duplicate item id")
        ids.add(item["id"])
        product_id = item.get("product", {}).get("id")
        if product_id:
            require(product_id not in product_ids, "duplicate Shopify product id across batch")
            product_ids.add(product_id)
        for call in (item.get("catalogue", {}).get("evidence"), item.get("image_qa", {}).get("visual")):
            if call:
                require(call["call_id"] not in calls, "vision call_id reused across evidence records")
                calls.add(call["call_id"])
    if data.get("batch_state") == "DONE":
        require(all(i["state"] == "ARCHIVED" for i in data["items"]), "DONE requires every item archived")


def advance(data: dict, item_id: str, target: str) -> None:
    item = next((i for i in data["items"] if i["id"] == item_id), None)
    require(item is not None, "unknown item")
    current = item["state"]
    require(target in TERMINAL or NEXT.get(current) == target, f"illegal transition {current} -> {target}")
    old = current
    item["state"] = target
    item["history"].append({"from": old, "to": target, "at": now()})
    try:
        validate_item(item)
    except Exception:
        item["state"] = old
        item["history"].pop()
        raise


def execution_plan(data: dict, workers: int) -> dict:
    validate_ledger(data)
    workers = max(1, min(workers, 4))
    prep = parallel_preparation_plan(data, workers)
    runnable = [
        i for i in data["items"]
        if i["state"] not in TERMINAL
        and i["state"] not in {"ARCHIVED", "VISUAL_ACCEPTED"}
    ]
    waves = []
    for state in ITEM_STATES:
        group = [i["id"] for i in runnable if i["state"] == state]
        for start in range(0, len(group), workers):
            waves.append({"state": state, "items": group[start:start + workers]})
    return {
        "batch_id": data["batch_id"],
        "workers": workers,
        "parallel_preparation": prep,
        "waves": waves,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("validate"); p.add_argument("ledger", type=Path)
    p = sub.add_parser("advance"); p.add_argument("ledger", type=Path); p.add_argument("item"); p.add_argument("target")
    p = sub.add_parser("mutation-envelope"); p.add_argument("ledger", type=Path); p.add_argument("item")
    p = sub.add_parser("parallel-plan"); p.add_argument("ledger", type=Path); p.add_argument("--workers", type=int, default=4)
    p = sub.add_parser("execution-plan"); p.add_argument("ledger", type=Path); p.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    try:
        data = load(args.ledger)
        if args.cmd == "advance":
            advance(data, args.item, args.target); save(args.ledger, data)
        elif args.cmd == "mutation-envelope":
            validate_ledger(data)
            item = next(i for i in data["items"] if i["id"] == args.item)
            require(item["state"] == "MUTATION_PENDING", "item is not mutation-ready")
            print(json.dumps({"batch_id": data["batch_id"], "item_id": item["id"], "product_id": item["product"]["id"], "changes": item["mutation"]}, sort_keys=True))
        elif args.cmd == "parallel-plan":
            validate_ledger(data)
            print(json.dumps(parallel_preparation_plan(data, args.workers), sort_keys=True))
        elif args.cmd == "execution-plan":
            print(json.dumps(execution_plan(data, args.workers), sort_keys=True))
        else:
            validate_ledger(data)
        return 0
    except (LedgerError, KeyError, StopIteration, json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
