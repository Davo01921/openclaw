"""Offline critical-gate tests for the BAU bindings."""

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def _load():
    script = Path(__file__).parents[1] / "scripts" / "betta_bindings.py"
    spec = importlib.util.spec_from_file_location("betta_bindings_bau_t", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bnd = _load()
TANK = "2BT12"


class BindingBauTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.batch = self.root / "batch"
        (self.batch / "manifest").mkdir(parents=True)
        self.manifest = self.batch / "manifest" / "shopify-production.json"
        self.manifest.write_text(
            json.dumps({"batch_id": "bau-bindings", "items": []}),
            encoding="utf-8",
        )
        self.digest = hashlib.sha256(self.manifest.read_bytes()).hexdigest()

    def write_verify_report(self, path, *, status=None, created_at="2026-10-11T00:00:00+00:00"):
        path = Path(path)
        path.write_text(json.dumps({
            "command": "verify", "batch_id": "bau-bindings",
            "manifest_sha256": self.digest, "created_at": created_at,
            "items": [{"tank_id": TANK, "status": status or bnd.READBACK_PASS,
                       "assertions": {"protected": {"status": "PASS"}}}],
        }), encoding="utf-8")
        return path

    def tearDown(self):
        self.tmp.cleanup()

    def test_resolve_preserves_full_raw_snapshot_and_fetch_evidence(self):
        raw = {
            "id": "gid://shopify/Product/1",
            "variants": {"pageInfo": {"hasNextPage": False}, "nodes": [{
                "id": "gid://shopify/ProductVariant/2",
                "inventoryItem": {
                    "id": "gid://shopify/InventoryItem/3",
                    "inventoryLevels": {
                        "pageInfo": {"hasNextPage": False},
                        "nodes": [{
                            "location": {"id": "gid://shopify/Location/4", "name": "NTA"},
                            "quantities": [
                                {"name": "available", "quantity": 1},
                                {"name": "on_hand", "quantity": 1},
                                {"name": "committed", "quantity": 0},
                            ],
                        }],
                    },
                },
            }]},
            "media": {"pageInfo": {"hasNextPage": False}, "nodes": []},
        }
        snapshot = {
            "id": raw["id"],
            "variant_id": "gid://shopify/ProductVariant/2",
            "inventory_item_id": "gid://shopify/InventoryItem/3",
            "location_id": "gid://shopify/Location/4",
            "source": "FRESH_SHOPIFY_READ",
            "tank_id": TANK,
            "fetched_at": "2026-10-11T00:00:00.000Z",
            "query": TANK,
            "location": {"id": "gid://shopify/Location/4", "name": "NTA"},
            "before": {"inventory": 1, "on_hand": 1, "committed": 0},
            "raw_product": raw,
        }
        resolve = bnd.shopify_resolve_runner(
            runner=lambda argv: {"ok": True, "status": "RESOLVED", "snapshot": snapshot}
        )
        product = resolve({"tank_id": TANK})["product"]
        self.assertEqual(product["raw_snapshot"], raw)
        self.assertEqual(product["fetched_at"], snapshot["fetched_at"])
        self.assertEqual(product["query"], TANK)
        self.assertEqual(product["before"]["committed"], 0)

    def test_preflight_hashes_persisted_bytes_and_requires_exact_digest(self):
        calls = []

        def runner(argv):
            calls.append(argv)
            return {
                "manifest_sha256": self.digest,
                "report_path": "/tmp/preflight.json",
                "shopify_writes_performed": False,
                "items": [{"tank_id": TANK, "status": "PREFLIGHTED"}],
            }

        preflight = bnd.shopify_preflight_runner(runner=runner)
        result = preflight(self.manifest, self.digest, TANK)
        self.assertEqual(result["status"], "PREFLIGHT_PASS")
        self.assertIn("preflight", calls[0])
        with self.assertRaises(bnd.BindingError):
            preflight(self.manifest, "0" * 64, TANK)
        self.assertEqual(len(calls), 1)

    def test_execute_uses_exact_dynamic_digest_then_independently_verifies(self):
        calls = []

        def runner(argv):
            command = argv[2]
            calls.append((command, list(argv)))
            if command == "status":
                return {"manifest_sha256": self.digest,
                        "items": [{"tank_id": TANK, "stage": "NEW", "status": "PENDING"}]}
            if command == "execute":
                return {
                    "manifest_sha256": self.digest,
                    "report_path": "/tmp/execute.json",
                    "items": [{"tank_id": TANK, "status": bnd.READBACK_PASS,
                               "receipt": {"status": bnd.READBACK_PASS}}],
                }
            if command == "verify":
                report_path = self.write_verify_report(self.root / "execute-verify.json")
                return {
                    "manifest_sha256": self.digest,
                    "report_path": str(report_path),
                    "items": [{"tank_id": TANK, "status": bnd.READBACK_PASS,
                               "assertions": {"protected": {"status": "PASS"}}}],
                }
            raise AssertionError(command)

        execute = bnd.shopify_execute_runner(live=True, runner=runner)
        result = execute({"tank_id": TANK}, self.manifest, self.digest)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual([call[0] for call in calls], ["status", "execute", "verify"])
        execute_argv = calls[1][1]
        digest_at = execute_argv.index("--confirm-manifest-sha256") + 1
        self.assertEqual(execute_argv[digest_at], self.digest)
        self.assertEqual(
            result["receipt"]["verify_report_path"],
            str((self.root / "execute-verify.json").resolve()),
        )
        self.assertEqual(
            result["receipt"]["verify_report_sha256"],
            hashlib.sha256((self.root / "execute-verify.json").read_bytes()).hexdigest(),
        )

    def test_execute_never_promotes_root_status_without_item_readback_pass(self):
        def runner(argv):
            command = argv[2]
            if command == "status":
                return {"manifest_sha256": self.digest,
                        "items": [{"tank_id": TANK, "stage": "NEW", "status": "PENDING"}]}
            return {
                "status": "VERIFIED",
                "manifest_sha256": self.digest,
                "report_path": f"/tmp/{command}.json",
                "items": [{"tank_id": TANK, "status": "FINAL_SHOPIFY_READBACK_FAIL"}],
            }

        result = bnd.shopify_execute_runner(live=True, runner=runner)(
            {"tank_id": TANK}, self.manifest, self.digest,
        )
        self.assertEqual(result["status"], "FAILED")

    def test_uncertain_write_gets_one_reconcile_only_resume_and_no_retry(self):
        calls = []

        def runner(argv):
            command = argv[2]
            calls.append(command)
            if command == "status":
                return {"manifest_sha256": self.digest,
                        "items": [{"tank_id": TANK, "stage": "MEDIA_ORDERED",
                                    "pending_operation": "betta_batch_delete_media"}]}
            if command == "resume":
                return {
                    "manifest_sha256": self.digest,
                    "report_path": "/tmp/resume-reconcile.json",
                    "items": [{"tank_id": TANK, "status": "UNCERTAIN_REQUIRES_DECISION"}],
                }
            if command == "verify":
                return {
                    "manifest_sha256": self.digest,
                    "report_path": "/tmp/reconcile-verify.json",
                    "items": [{"tank_id": TANK,
                               "status": "FINAL_SHOPIFY_READBACK_FAIL"}],
                }
            raise AssertionError("an uncertain mutation must not be replayed")

        result = bnd.shopify_execute_runner(live=True, runner=runner)(
            {"tank_id": TANK}, self.manifest, self.digest,
        )
        self.assertEqual(result["status"], "PENDING_RECONCILIATION")
        self.assertEqual(calls, ["status", "resume", "verify"])

    def test_reconcile_runner_never_enables_a_shopify_write(self):
        calls = []

        def runner(argv):
            command = argv[2]
            calls.append(list(argv))
            if command == "status":
                return {"manifest_sha256": self.digest, "items": [{
                    "tank_id": TANK, "stage": "DETAILS_UPDATED",
                    "pending_operation": "betta_batch_set_inventory",
                }]}
            if command == "resume":
                self.assertNotIn("--live", argv)
                self.assertNotIn("--confirm-manifest-sha256", argv)
                return {"manifest_sha256": self.digest, "items": [{
                    "tank_id": TANK, "status": "UNCERTAIN_REQUIRES_DECISION",
                }]}
            if command == "verify":
                self.assertNotIn("--live", argv)
                return {"manifest_sha256": self.digest, "items": [{
                    "tank_id": TANK, "status": "FINAL_SHOPIFY_READBACK_FAIL",
                }]}
            raise AssertionError(command)

        reconcile = bnd.shopify_reconcile_runner(runner=runner)
        result = reconcile({"tank_id": TANK}, self.manifest, self.digest)
        self.assertEqual(result["status"], "PENDING_RECONCILIATION")
        self.assertEqual([argv[2] for argv in calls], ["status", "resume", "verify"])

    def test_archive_passes_real_args_and_validates_actual_result(self):
        verify = self.write_verify_report(self.root / "verify.json")
        verify_digest = hashlib.sha256(verify.read_bytes()).hexdigest()
        inventory = self.batch / "reports" / "betta-inventory.csv"
        inventory.parent.mkdir(parents=True)
        inventory.write_text("Tank\n2BT12\n", encoding="utf-8")
        telemetry = self.batch / "reports" / "betta-call-telemetry.csv"
        telemetry.write_text("stage,outcome\nqa,OK\n", encoding="utf-8")
        catalogue = self.batch / "evidence" / "catalogue" / "2BT12.json"
        catalogue.parent.mkdir(parents=True)
        catalogue.write_text('{"tank_id":"2BT12"}\n', encoding="utf-8")
        authority = self.batch / "state" / "authority.json"
        authority.parent.mkdir(parents=True)
        authority.write_text('{"receipt":"bau"}\n', encoding="utf-8")
        budget = self.batch / "state" / "gen-budget.json"
        budget.write_text('{"spent":0.07}\n', encoding="utf-8")
        process = self.batch / "state" / "process.json"
        process.write_text('{"stage":"ARCHIVING"}\n', encoding="utf-8")
        archive_manifest = self.root / "archive-manifest.json"
        archive_manifest.write_text("{}", encoding="utf-8")
        archive_digest = hashlib.sha256(archive_manifest.read_bytes()).hexdigest()
        calls = []

        def runner(argv):
            calls.append(argv)
            audit_sources = [
                Path(argv[index + 1]).resolve()
                for index, value in enumerate(argv) if value == "--audit-path"
            ]
            sources = [
                verify.resolve(), self.manifest.resolve(), inventory.resolve(),
                *audit_sources,
            ]
            return {
                "mode": "execute", "batch_status": "COMPLETE",
                "manifest": str(archive_manifest), "manifest_sha256": archive_digest,
                "state": str(self.root / "archive-state.json"),
                "results": [{
                    "source": str(path), "status": "COPIED",
                    "source_sha256": "a", "destination_sha256": "a",
                } for path in sources],
            }

        state = {
            "batch_id": "bau-bindings",
            "fish": {TANK: {
                "tank_id": TANK, "status": "VERIFIED",
                "shopify_receipt": {
                    "tank_id": TANK, "batch_id": "bau-bindings",
                    "manifest_sha256": self.digest,
                    "verify_report_path": str(verify),
                    "verify_report_sha256": verify_digest,
                    "verify_report_created_at": "2026-10-11T00:00:00+00:00",
                },
            }},
        }
        result = bnd.archive_runner(
            archive_root=self.root / "Archived", date="2026-10-11",
            live=True, runner=runner,
        )(state, self.batch)
        self.assertEqual(result["status"], "ARCHIVED")
        argv = calls[0]
        self.assertEqual(argv[2], "execute")
        self.assertNotIn("--batch", argv)
        self.assertIn("--verify", argv)
        audit_values = [
            Path(argv[index + 1]) for index, value in enumerate(argv)
            if value == "--audit-path"
        ]
        self.assertTrue({
            telemetry.resolve(), catalogue.resolve(), authority.resolve(),
            budget.resolve(),
            (self.batch / "state" / "archive-process-snapshot.json").resolve(),
            (self.batch / "state" / "archive-audit-inputs.json").resolve(),
        } <= set(audit_values))
        self.assertIn("--inventory-csv", argv)
        self.assertIn("--state-root", argv)
        self.assertIn("--apply", argv)

    def test_archive_rejects_replaced_verify_report(self):
        verify = self.write_verify_report(self.root / "verify.json")
        receipt = {
            "tank_id": TANK, "batch_id": "bau-bindings",
            "manifest_sha256": self.digest,
            "verify_report_path": str(verify),
            "verify_report_sha256": hashlib.sha256(verify.read_bytes()).hexdigest(),
            "verify_report_created_at": "2026-10-11T00:00:00+00:00",
        }
        verify.write_text('{}\n', encoding="utf-8")
        state = {"fish": {TANK: {
            "tank_id": TANK, "status": "VERIFIED", "shopify_receipt": receipt,
        }}}
        with self.assertRaisesRegex(bnd.BindingError, "replaced"):
            bnd.archive_runner(
                archive_root=self.root / "Archived", live=True,
                runner=lambda _argv: self.fail("archiver must not run"),
            )(state, self.batch)

    def test_frozen_audit_selection_reuses_snapshot_on_resume(self):
        reports = self.batch / "reports"
        reports.mkdir()
        telemetry = reports / "betta-call-telemetry.csv"
        telemetry.write_text("stage,outcome\nqa,OK\n", encoding="utf-8")
        state_dir = self.batch / "state"
        state_dir.mkdir()
        process = state_dir / "process.json"
        process.write_text('{"stage":"ARCHIVING","revision":1}\n', encoding="utf-8")
        first = bnd._batch_audit_paths(
            {}, self.batch, [], None, batch_id="bau-bindings",
        )
        snapshot = state_dir / "archive-process-snapshot.json"
        snapshot_bytes = snapshot.read_bytes()
        process.write_text('{"stage":"ARCHIVED","revision":2}\n', encoding="utf-8")
        (reports / "archive-later.json").write_text('{}\n', encoding="utf-8")
        second = bnd._batch_audit_paths(
            {}, self.batch, [], None, batch_id="bau-bindings",
        )
        self.assertEqual(first, second)
        self.assertEqual(snapshot.read_bytes(), snapshot_bytes)
        self.assertNotIn((reports / "archive-later.json").resolve(), second)

    def test_live_bindings_expose_preflight(self):
        runners = bnd.bind_runners(archive_root=self.root, live=True)
        self.assertEqual(
            set(runners), {"resolve", "preflight", "execute", "reconcile", "archive"},
        )

    def test_configured_runtime_paths_are_forwarded_to_real_runners(self):
        python = self.root / "configured-python"
        node = self.root / "configured-node"
        bridge = self.root / "configured-bridge.mjs"
        env_file = self.root / "configured.env"
        for path in (python, node, bridge, env_file):
            path.write_text("fixture", encoding="utf-8")
        runners = bnd.bind_runners(
            archive_root=self.root, live=True,
            python=str(python), python_executable=str(python),
            node=str(node), bridge=bridge, env_file=env_file,
        )
        calls = []

        def uploader(argv):
            calls.append(argv)
            return {
                "manifest_sha256": self.digest,
                "shopify_writes_performed": False,
                "items": [{"tank_id": TANK, "status": "PREFLIGHTED"}],
            }

        preflight = bnd.shopify_preflight_runner(
            python_executable=str(python), node=str(node), bridge=bridge,
            env_file=env_file, runner=uploader,
        )
        self.assertEqual(preflight(self.manifest, self.digest)["status"], "PREFLIGHT_PASS")
        argv = calls[0]
        self.assertEqual(argv[0], str(python))
        self.assertEqual(argv[argv.index("--node") + 1], str(node))
        self.assertEqual(argv[argv.index("--bridge") + 1], str(bridge.resolve()))
        self.assertEqual(argv[argv.index("--env-file") + 1], str(env_file.resolve()))
        self.assertEqual(
            set(runners), {"resolve", "preflight", "execute", "reconcile", "archive"},
        )

        resolve_calls = []
        resolver = bnd.shopify_resolve_runner(
            node=str(node), env_file=env_file,
            runner=lambda argv: resolve_calls.append(argv) or {
                "ok": True, "status": "RESOLVED", "snapshot": {
                    "id": "gid://shopify/Product/1",
                    "variant_id": "gid://shopify/ProductVariant/2",
                    "inventory_item_id": "gid://shopify/InventoryItem/3",
                    "location_id": "gid://shopify/Location/4",
                    "source": "FRESH_SHOPIFY_READ", "tank_id": TANK,
                    "query": TANK, "fetched_at": "2026-10-11T00:00:00Z",
                    "location": {"id": "gid://shopify/Location/4", "name": "NTA"},
                    "before": {"inventory": 1, "on_hand": 1, "committed": 0},
                    "raw_product": {
                        "id": "gid://shopify/Product/1",
                        "media": {"pageInfo": {"hasNextPage": False}, "nodes": []},
                        "variants": {"pageInfo": {"hasNextPage": False}, "nodes": [{
                            "id": "gid://shopify/ProductVariant/2",
                            "inventoryItem": {
                                "id": "gid://shopify/InventoryItem/3",
                                "inventoryLevels": {
                                    "pageInfo": {"hasNextPage": False},
                                    "nodes": [{"location": {
                                        "id": "gid://shopify/Location/4", "name": "NTA",
                                    }}],
                                },
                            },
                        }]},
                    },
                },
            },
        )
        resolver({"tank_id": TANK})
        self.assertEqual(resolve_calls[0][0], str(node))
        self.assertEqual(resolve_calls[0][1], str(bnd.SHOPIFY_LIVE.resolve()))
        self.assertNotEqual(resolve_calls[0][1], str(bridge.resolve()))

        with self.assertRaisesRegex(bnd.BindingError, "disagree"):
            bnd.bind_runners(
                archive_root=self.root, python="/one", python_executable="/two",
            )


if __name__ == "__main__":
    unittest.main()
