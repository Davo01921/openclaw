"""Generate a Phase 1A Gumtree configuration review report from JSON input.

Input: JSON array of normalized Shopify product objects.
Output: JSON report to stdout. Read-only; no external calls.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from gumtree_config import classify_product


def build_report(products: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = [classify_product(product).to_dict() for product in products]
    counts: dict[str, int] = {
        "UNCONFIGURED": 0,
        "CONFIGURED": 0,
        "EXCLUDED": 0,
        "CONFIG_ERROR": 0,
    }
    for decision in decisions:
        counts[decision["config_state"]] += 1

    return {
        "schema_version": "1.0",
        "mode": "READ_ONLY",
        "counts": counts,
        "products": decisions,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="Normalized Shopify products JSON file")
    args = parser.parse_args()

    products = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(products, list):
        raise SystemExit("Input must be a JSON array of products")

    print(json.dumps(build_report(products), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
