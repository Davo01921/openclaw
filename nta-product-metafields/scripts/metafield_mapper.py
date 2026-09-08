#!/usr/bin/env python3
import json
import sys
from datetime import date
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "metafields.json"


def load_schema():
    with SCHEMA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_path(data, dotted):
    cur = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None, False
        cur = cur[part]
    return cur, True


def valid_iso_date(value):
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
        return len(value) == 10
    except ValueError:
        return False


def validate_value(rule, value):
    kind = rule.get("validator")
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "enum":
        return isinstance(value, str) and value in rule.get("allowed_values", [])
    if kind == "iso_date":
        return valid_iso_date(value)
    if kind == "nonempty_string":
        return isinstance(value, str) and bool(value.strip())
    return False


def map_metafields(payload):
    schema = load_schema()
    requested = payload.get("requested_fields", [])
    definitions = payload.get("verified_definitions", {})

    if not isinstance(requested, list) or not requested:
        return review(["requested_fields"], ["No metafields requested."])

    proposed = []
    problems = []
    notes = []

    for canonical_name in requested:
        rule = schema["fields"].get(canonical_name)
        if rule is None:
            problems.append(f"unknown_field:{canonical_name}")
            continue

        value, found = get_path(payload, rule["source_path"])
        if not found:
            problems.append(f"missing_source:{rule['source_path']}")
            continue
        if not validate_value(rule, value):
            problems.append(f"invalid_value:{canonical_name}")
            continue

        definition_key = f"{rule['namespace']}.{rule['key']}"
        definition = definitions.get(definition_key)
        if rule.get("definition_metadata_required"):
            if not isinstance(definition, dict):
                problems.append(f"missing_verified_definition:{definition_key}")
                continue
            owner_scope = definition.get("owner_scope")
            value_type = definition.get("type")
            if owner_scope not in {"PRODUCT", "VARIANT"}:
                problems.append(f"invalid_definition_scope:{definition_key}")
                continue
            if not isinstance(value_type, str) or not value_type.strip():
                problems.append(f"invalid_definition_type:{definition_key}")
                continue
        else:
            owner_scope = None
            value_type = None

        proposed.append({
            "canonical_name": canonical_name,
            "namespace": rule["namespace"],
            "key": rule["key"],
            "owner_scope": owner_scope,
            "type": value_type,
            "value": value,
            "source_path": rule["source_path"],
        })

    if problems:
        return review(problems, notes)

    return {
        "status": "READY",
        "metafields": {
            "proposed": proposed,
            "preserve_unrelated": True,
            "notes": notes,
        },
        "missing_or_conflicting_fields": [],
        "notes": [],
    }


def review(problems, notes=None):
    return {
        "status": "REVIEW_REQUIRED",
        "metafields": None,
        "missing_or_conflicting_fields": problems,
        "notes": notes or [],
    }


def main():
    try:
        payload = json.load(sys.stdin)
        print(json.dumps(map_metafields(payload), indent=2, sort_keys=True))
    except Exception as exc:
        print(json.dumps({
            "status": "REVIEW_REQUIRED",
            "metafields": None,
            "missing_or_conflicting_fields": ["runtime_error"],
            "notes": [str(exc)],
        }, indent=2, sort_keys=True))
        sys.exit(1)


if __name__ == "__main__":
    main()
