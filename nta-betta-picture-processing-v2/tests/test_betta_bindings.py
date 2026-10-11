"""Offline tests for the Shopify bridge/uploader bindings."""

import importlib.util
import hashlib
import json
import tempfile
import unittest
from pathlib import Path


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bnd = _load("betta_bindings_t", "betta_bindings.py")


RESOLVE_JSON = json.dumps({"ok": True, "status": "RESOLVED", "snapshot": {
    "id": "gid://shopify/Product/1", "variant_id": "gid://shopify/ProductVariant/2",
    "location_id": "gid://shopify/Location/3", "inventory_item_id": "gid://shopify/InventoryItem/4",
    "source": "FRESH_SHOPIFY_READ", "tank_id": "2BT12",
    "before": {"inventory": 1, "price": "35.00", "status": "ACTIVE"}}})


class BindingTests(unittest.TestCase):
    def test_resolve_parses_snapshot(self):
        resolve = bnd.shopify_resolve_runner(runner=lambda argv: RESOLVE_JSON)
        result = resolve({"tank_id": "2BT12"})
        self.assertEqual(result["status"], "RESOLVED")
        product = result["product"]
        self.assertEqual(product["id"], "gid://shopify/Product/1")
        self.assertEqual(product["variant_id"], "gid://shopify/ProductVariant/2")
        self.assertEqual(product["before"]["inventory"], 1)

    def test_resolve_ambiguous_on_failure(self):
        resolve = bnd.shopify_resolve_runner(runner=lambda argv: json.dumps({"ok": False}))
        self.assertEqual(resolve({"tank_id": "2BT12"})["status"], "AMBIGUOUS")

    def test_execute_dry_run_never_calls_or_writes(self):
        calls = []
        execute = bnd.shopify_execute_runner(runner=lambda argv: calls.append(argv) or "{}")
        result = execute({"tank_id": "2BT12"}, Path("/tmp/m.json"), "abc")
        self.assertEqual(result["status"], "AWAITING_LIVE")
        self.assertEqual(calls, [])

    def test_execute_live_requires_matching_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "m.json"
            manifest.write_bytes(b'{"persisted":true}\n')
            digest = hashlib.sha256(manifest.read_bytes()).hexdigest()

            def runner(argv):
                command = argv[2]
                if command == "status":
                    return json.dumps({"manifest_sha256": digest, "items": [{
                        "tank_id": "2BT12", "stage": "NEW", "status": "PENDING",
                    }]})
                return json.dumps({"manifest_sha256": digest, "report_path": f"/{command}.json",
                                   "items": [{"tank_id": "2BT12",
                                              "status": bnd.READBACK_PASS,
                                              "receipt": "r"}]})

            execute = bnd.shopify_execute_runner(live=True, runner=runner)
            with self.assertRaises(bnd.BindingError):
                execute({"tank_id": "2BT12"}, manifest, "different")
            result = execute({"tank_id": "2BT12"}, manifest, digest)
            self.assertEqual(result["status"], "VERIFIED")

    def test_execute_live_non_verified_is_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "m.json"
            manifest.write_bytes(b'{"persisted":true}\n')
            digest = hashlib.sha256(manifest.read_bytes()).hexdigest()

            def runner(argv):
                command = argv[2]
                if command == "status":
                    return {"manifest_sha256": digest, "items": [{
                        "tank_id": "2BT12", "stage": "NEW", "status": "PENDING",
                    }]}
                return {"manifest_sha256": digest, "items": [{
                    "tank_id": "2BT12", "status": "BLOCKED",
                }]}

            execute = bnd.shopify_execute_runner(live=True, runner=runner)
            self.assertEqual(execute({"tank_id": "2BT12"}, manifest, digest)["status"],
                             "FAILED")

    def test_bind_runners_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            runners = bnd.bind_runners(archive_root=Path(tmp))
        self.assertEqual(set(runners), {"resolve", "execute", "archive"})


if __name__ == "__main__":
    unittest.main()
