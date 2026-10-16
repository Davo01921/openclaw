"""Tests for the trusted Shopify write boundary bindings + deploy artefacts.

Hermetic: no root, no UNIX sockets, no Shopify, no network. The pinned
``WriteBoundaryClient`` surface is injected as an in-memory fake so the suite
runs even while the real client module is being built in parallel; when
``scripts/betta_write_client.py`` exists an interface-compatibility check runs
against it instead of skipping.

Covered here:
  * the manifest-item -> daemon operation mapping (update details -> update
    details, inventory -> set_inventory, hero+original -> media_append, and
    verify -> verify);
  * fail-closed behaviour for unmappable intents (merch/reorder/delete/extra
    media) and for missing sockets / per-call flag contradictions;
  * the default no-boundary path staying identical to the legacy uploader path;
  * deploy artefacts: bash -n, --dry-run plans, plist render + plutil -lint,
    sudoers visudo -c -f lint, conservative production policy, and the policy
    passing the pinned daemon validator when that module is on disk.
"""

import hashlib
import importlib.util
import inspect
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path


PROJECT = Path(__file__).parents[1]
DEPLOY = PROJECT / "deploy"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, PROJECT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bnd = _load("betta_bindings_boundary_t", "betta_bindings.py")

TANK = "2BT12"
BATCH_ID = "trusted-boundary-test"
READBACK_PASS = bnd.READBACK_PASS


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


class FakeBoundaryClient:
    """In-memory implementation of the pinned WriteBoundaryClient surface."""

    def __init__(self, *, outcomes=None, verify_outcome="VERIFIED",
                 verify_readbacks=None):
        self.requests = []
        self.verify_calls = []
        self._outcomes = list(outcomes or [])
        self.verify_outcome = verify_outcome
        self._readbacks = list(verify_readbacks or [])

    def build_request(self, *, operation, mode, target, evidence, operations,
                      authorisation, request_id=None):
        return {
            "schema": bnd.BOUNDARY_REQUEST_SCHEMA,
            "request_id": request_id,
            "operation": operation,
            "mode": mode,
            "authorisation": authorisation,
            "target": target,
            "evidence": evidence,
            "operations": operations,
        }

    def _ok(self, outcome, **extra):
        response = {
            "schema": bnd.BOUNDARY_RESPONSE_SCHEMA,
            "ok": True,
            "outcome": outcome,
            "receipt_sha256": "a" * 64,
            "receipt_signature": "hmac-sha256:" + "ab" * 16,
        }
        response.update(extra)
        return response

    def _err(self, outcome, code, detail):
        return {
            "schema": bnd.BOUNDARY_RESPONSE_SCHEMA,
            "ok": False,
            "outcome": outcome,
            "error_code": code,
            "detail": detail,
        }

    def request(self, payload):
        self.requests.append(payload)
        outcome = self._outcomes.pop(0) if self._outcomes else "APPLIED"
        if outcome == "APPLIED":
            return self._ok("APPLIED", receipt={"operation": payload["operation"]})
        if outcome == "RECONCILIATION_REQUIRED":
            return self._err(
                "RECONCILIATION_REQUIRED", "reconciliation_required",
                "mutation intent was persisted but the outcome is unresolved; "
                "run verify for a fresh read-back")
        if outcome == "REFUSED":
            return self._err("REFUSED", "policy_refused", "operation not allowed")
        raise AssertionError(outcome)

    def verify(self, target, evidence):
        self.verify_calls.append({"target": target, "evidence": evidence})
        if self.verify_outcome == "VERIFIED":
            if self._readbacks:
                readback = self._readbacks.pop(0)
            else:
                readback = {"product": {}, "reconciliations": []}
            return self._ok("VERIFIED", receipt={"kind": "verify"},
                            readback=readback)
        if self.verify_outcome == "REFUSED":
            return self._err("REFUSED", "evidence_invalid", "read-back failed")
        if self.verify_outcome == "RECONCILIATION_REQUIRED":
            return self._err(
                "RECONCILIATION_REQUIRED", "reconciliation_required",
                "unresolved")
        raise AssertionError(self.verify_outcome)

    def status(self):
        return self._ok("STATUS", readback={"disabled": False})


class BoundaryFixtureMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.batch = self.root / "batch"
        self.item = self._make_item()
        self.manifest, self.digest = self._write_manifest()

    def tearDown(self):
        self._tmp.cleanup()

    def _make_item(self):
        hero = self.batch / "images" / "hero.png"
        original = self.batch / "images" / "original.jpg"
        hero.parent.mkdir(parents=True, exist_ok=True)
        hero.write_bytes(b"\x89PNG\r\n\x1a\nhero-bytes")
        original.write_bytes(b"\xff\xd8\xfforiginal-bytes")
        hero_sha = _sha256(hero.read_bytes())
        original_sha = _sha256(original.read_bytes())
        return {
            "tank_id": TANK,
            "product_id": "gid://shopify/Product/11",
            "variant_id": "gid://shopify/ProductVariant/22",
            "inventory_item_id": "gid://shopify/InventoryItem/33",
            "location_id": "gid://shopify/Location/44",
            "approved_title": f"{TANK} - Betta splendens Halfmoon Male",
            "arrival_date": "2026-10-16",
            "quantity": 1,
            "inventory_reason": "received",
            "source_reference": "bau:trusted-boundary-test:abc",
            "identity": {
                "source_sha256": original_sha,
                "detected_tank": TANK,
                "requested_tank": TANK,
                "accepted_tank": TANK,
                "correction_sha256": None,
            },
            "hero": {"path": str(hero), "sha256": hero_sha,
                      "mime_type": "image/png"},
            "original": {"path": str(original), "sha256": original_sha,
                          "mime_type": "image/jpeg"},
            "working": {"path": str(original), "sha256": original_sha,
                         "mime_type": "image/jpeg"},
            "image_qa": {"path": str(hero), "sha256": "d" * 64,
                          "exception": None},
            "write_authorised": True,
        }

    def _write_manifest(self, item=None):
        manifest = {
            "schema": "nta-betta-shopify-batch-v1",
            "batch_id": BATCH_ID,
            "shopify_write_authorised": True,
            "state_dir": str(self.batch / "state" / "shopify"),
            "report_dir": str(self.batch / "reports" / "shopify"),
            "items": [item if item is not None else self.item],
        }
        path = _write_json(
            self.batch / "manifest" / "shopify-production.json", manifest)
        return path, _sha256(path.read_bytes())

    def _entry(self, *, inventory=0, title=None, arrival="2026-10-01"):
        return {
            "tank_id": TANK,
            "product": {
                "before": {
                    "title": title or f"{TANK} - Old Title",
                    "arrival_date": arrival,
                    "inventory": inventory,
                },
            },
        }

    def _readback(self, *, title=None, arrival_date=None, available=1,
                  media=True):
        hero_alt = f"NTA|{BATCH_ID}|{TANK}|HERO|sha256={self.item['hero']['sha256']}"
        original_alt = (
            f"NTA|{BATCH_ID}|{TANK}|ORIGINAL|sha256="
            f"{self.item['original']['sha256']}")
        nodes = []
        if media:
            nodes = [
                {"id": "gid://shopify/MediaImage/1", "alt": hero_alt},
                {"id": "gid://shopify/MediaImage/2", "alt": original_alt},
            ]
        product = {
            "product_id": self.item["product_id"],
            "title": title or self.item["approved_title"],
            "arrival_date": arrival_date or self.item["arrival_date"],
            "available": available,
            "inventory_quantity": available,
            "media": nodes,
        }
        return {"product": product, "reconciliations": []}

    def _execute(self, client, *, live=True, reconcile_only=False,
                 trusted_writer=None):
        runner = bnd.shopify_execute_runner(
            live=live, trusted_writer_client=client)
        return runner(
            self._entry(), self.manifest, self.digest,
            reconcile_only=reconcile_only, trusted_writer=trusted_writer)


class BoundaryMappingTests(BoundaryFixtureMixin, unittest.TestCase):
    def test_operation_plan_maps_details_inventory_media(self):
        plan = bnd.boundary_operation_plan(
            self.item, baseline=self._entry()["product"]["before"])
        self.assertEqual(
            [op["type"] for op in plan["operations"]],
            ["update_details", "set_inventory", "media_append"])
        self.assertEqual(plan["skipped"], [])

        details = plan["operations"][0]
        self.assertEqual(details["title"], self.item["approved_title"])
        self.assertEqual(details["arrival_date"], self.item["arrival_date"])
        self.assertEqual(
            details["expected"],
            {"title": f"{TANK} - Old Title", "arrival_date": "2026-10-01"})

        inventory = plan["operations"][1]
        self.assertEqual(inventory["quantity"], 1)
        self.assertEqual(inventory["reason"], "received")
        self.assertEqual(inventory["expected"]["available"], 0)
        self.assertEqual(
            inventory["expected"]["inventory_item_id"],
            self.item["inventory_item_id"])
        self.assertEqual(
            inventory["expected"]["location_id"], self.item["location_id"])

        media = plan["operations"][2]
        self.assertEqual([asset["role"] for asset in media["assets"]],
                         ["hero", "original"])
        self.assertEqual(media["assets"][0]["sha256"],
                         self.item["hero"]["sha256"])
        self.assertEqual(media["assets"][1]["sha256"],
                         self.item["original"]["sha256"])
        self.assertNotIn("expected", media)

    def test_operation_plan_skips_inventory_when_already_at_target(self):
        plan = bnd.boundary_operation_plan(
            self.item, baseline=self._entry(inventory=1)["product"]["before"])
        self.assertEqual(
            [op["type"] for op in plan["operations"]],
            ["update_details", "media_append"])
        self.assertEqual(
            plan["skipped"],
            [{"type": "set_inventory", "reason": "already_at_target",
              "available": 1}])

    def test_operation_plan_refuses_unmappable_merch_intent(self):
        item = dict(self.item)
        item["merch_update"] = {"vendor": "X", "price": "1.00", "cost": "0.50"}
        with self.assertRaisesRegex(bnd.BindingError, "cannot express"):
            bnd.boundary_operation_plan(
                item, baseline=self._entry()["product"]["before"])

    def test_operation_plan_refuses_unmappable_media_ops(self):
        for key in ("delete_media", "reorder_media", "additional_images"):
            item = dict(self.item)
            item[key] = True
            with self.assertRaisesRegex(bnd.BindingError, "cannot express"):
                bnd.boundary_operation_plan(
                    item, baseline=self._entry()["product"]["before"])

    def test_operation_plan_refuses_null_arrival_baseline(self):
        baseline = {"title": f"{TANK} - Old Title", "arrival_date": None,
                    "inventory": 0}
        with self.assertRaisesRegex(bnd.BindingError,
                                    "absent->date transition"):
            bnd.boundary_operation_plan(self.item, baseline=baseline)

    def test_operation_plan_refuses_non_one_quantity(self):
        item = dict(self.item)
        item["quantity"] = 2
        with self.assertRaisesRegex(bnd.BindingError, "quantity 1"):
            bnd.boundary_operation_plan(
                item, baseline=self._entry()["product"]["before"])

    def test_operation_plan_refuses_missing_asset_bytes(self):
        item = dict(self.item)
        item["hero"] = dict(self.item["hero"])
        item["hero"]["path"] = str(self.root / "missing.png")
        with self.assertRaisesRegex(bnd.BindingError, "missing on disk"):
            bnd.boundary_operation_plan(
                item, baseline=self._entry()["product"]["before"])

    def test_boundary_evidence_binds_manifest_and_identity(self):
        evidence = bnd.boundary_evidence(
            self.item, manifest_path=str(self.manifest),
            manifest_sha256=self.digest, idempotency_detail="update_details:x:y")
        self.assertEqual(evidence["manifest_path"],
                         str(self.manifest.resolve()))
        self.assertEqual(evidence["manifest_sha256"], self.digest)
        self.assertEqual(evidence["source_sha256"],
                         self.item["identity"]["source_sha256"])
        self.assertEqual(evidence["identity"], self.item["identity"])
        self.assertIsNone(evidence["correction_sha256"])
        self.assertEqual(evidence["qa_receipt_sha256"], "d" * 64)
        self.assertRegex(evidence["idempotency_key"], r"^[0-9a-f]{64}$")
        self.assertEqual(set(evidence), {
            "manifest_path", "manifest_sha256", "source_sha256", "identity",
            "correction_sha256", "qa_receipt_sha256", "idempotency_key"})

    def test_boundary_evidence_refuses_broken_identity(self):
        item = dict(self.item)
        item["identity"] = dict(self.item["identity"])
        item["identity"]["accepted_tank"] = "5BT43"
        with self.assertRaisesRegex(bnd.BindingError, "accepted_tank"):
            bnd.boundary_evidence(
                item, manifest_path=str(self.manifest),
                manifest_sha256=self.digest, idempotency_detail="verify")

    def test_request_id_is_deterministic_version_4(self):
        first = bnd._boundary_request_id("update_details", self.digest, TANK, "d")
        second = bnd._boundary_request_id("update_details", self.digest, TANK, "d")
        other = bnd._boundary_request_id("set_inventory", self.digest, TANK, "d")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        parsed = uuid.UUID(first)
        self.assertEqual(parsed.version, 4)
        self.assertEqual(parsed.variant, uuid.RFC_4122)


class BoundaryExecuteTests(BoundaryFixtureMixin, unittest.TestCase):
    def test_execute_routes_three_ops_plus_verify_through_boundary(self):
        client = FakeBoundaryClient(verify_readbacks=[self._readback()])
        result = self._execute(client)

        self.assertEqual(result["status"], "VERIFIED")
        self.assertTrue(result["boundary"])
        self.assertEqual(
            [payload["operation"] for payload in client.requests],
            ["update_details", "set_inventory", "media_append"])
        self.assertEqual(len(client.verify_calls), 1)

        details = client.requests[0]
        self.assertEqual(details["schema"], bnd.BOUNDARY_REQUEST_SCHEMA)
        self.assertEqual(details["mode"], "apply")
        self.assertEqual(details["authorisation"], {"kind": "standing"})
        self.assertEqual(set(details["target"]), {
            "product_id", "variant_id", "inventory_item_id", "location_id"})
        self.assertEqual(details["target"]["product_id"],
                         self.item["product_id"])
        self.assertEqual(details["evidence"]["manifest_sha256"], self.digest)
        self.assertEqual(details["evidence"]["identity"], self.item["identity"])
        self.assertEqual(len(details["operations"]), 1)
        self.assertEqual(details["operations"][0]["type"], "update_details")
        self.assertEqual(uuid.UUID(details["request_id"]).version, 4)

        media = client.requests[2]["operations"][0]
        self.assertEqual([asset["role"] for asset in media["assets"]],
                         ["hero", "original"])
        self.assertEqual(client.verify_calls[0]["target"],
                         details["target"])

    def test_execute_receipt_binds_written_verify_report(self):
        client = FakeBoundaryClient(verify_readbacks=[self._readback()])
        result = self._execute(client)
        receipt = result["receipt"]
        report_path = Path(receipt["verify_report_path"])
        self.assertTrue(report_path.is_file())
        self.assertEqual(receipt["manifest_sha256"], self.digest)
        self.assertEqual(receipt["verify_report_sha256"],
                         _sha256(report_path.read_bytes()))
        self.assertEqual(receipt["tank_id"], TANK)
        self.assertEqual(receipt["batch_id"], BATCH_ID)

        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["command"], "verify")
        self.assertEqual(report["batch_id"], BATCH_ID)
        self.assertEqual(report["manifest_sha256"], self.digest)
        self.assertEqual(len(report["items"]), 1)
        self.assertEqual(report["items"][0]["tank_id"], TANK)
        self.assertEqual(report["items"][0]["status"], READBACK_PASS)
        self.assertEqual(
            report["items"][0]["boundary"]["receipt_sha256"], "a" * 64)
        self.assertEqual(
            report["items"][0]["boundary"]["receipt_signature"],
            "hmac-sha256:" + "ab" * 16)
        self.assertEqual(
            [entry["operation"] for entry in report["items"][0]["boundary_operations"]],
            ["update_details", "set_inventory", "media_append", "verify"])

        # The existing archive validation must accept the artefact unchanged.
        validated, digest = bnd._verified_report(
            report_path, tank=TANK, batch_id=BATCH_ID,
            manifest_sha256=self.digest)
        self.assertEqual(validated["command"], "verify")
        self.assertEqual(digest, receipt["verify_report_sha256"])

    def test_execute_request_ids_are_deterministic_across_reruns(self):
        first = FakeBoundaryClient(verify_readbacks=[self._readback()])
        self._execute(first)
        second = FakeBoundaryClient(verify_readbacks=[self._readback()])
        self._execute(second)
        self.assertEqual(
            [(payload["operation"], payload["request_id"])
             for payload in first.requests],
            [(payload["operation"], payload["request_id"])
             for payload in second.requests])
        self.assertEqual(
            [(payload["operation"], payload["evidence"]["idempotency_key"])
             for payload in first.requests],
            [(payload["operation"], payload["evidence"]["idempotency_key"])
             for payload in second.requests])

    def test_execute_refused_fails_closed_without_legacy_fallback(self):
        client = FakeBoundaryClient(outcomes=["REFUSED"])
        runner = bnd.shopify_execute_runner(
            live=True, trusted_writer_client=client,
            runner=lambda argv: self.fail("legacy uploader must not run"))
        result = runner(self._entry(), self.manifest, self.digest)
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["error_code"], "policy_refused")
        self.assertIn("refused update_details", result["error"])
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(client.verify_calls, [])

    def test_execute_reconciliation_required_maps_to_pending(self):
        client = FakeBoundaryClient(
            outcomes=["APPLIED", "RECONCILIATION_REQUIRED"])
        result = self._execute(client)
        self.assertEqual(result["status"], "PENDING_RECONCILIATION")
        self.assertIn("unresolved", result["reason"])
        self.assertEqual(client.verify_calls, [])
        self.assertEqual(
            [entry["outcome"] for entry in result["boundary_operations"]],
            ["APPLIED", "RECONCILIATION_REQUIRED"])

    def test_execute_verify_refused_fails(self):
        client = FakeBoundaryClient(verify_outcome="REFUSED")
        result = self._execute(client)
        self.assertEqual(result["status"], "FAILED")
        self.assertIn("verify refused", result["error"])
        self.assertEqual(
            [payload["operation"] for payload in client.requests],
            ["update_details", "set_inventory", "media_append"])

    def test_execute_missing_end_state_fails_closed(self):
        readback = self._readback()
        readback["product"]["title"] = "something else"
        client = FakeBoundaryClient(verify_readbacks=[readback])
        result = self._execute(client)
        self.assertEqual(result["status"], "FAILED")
        self.assertIn("missing: title", result["error"])
        report_dir = self.batch / "reports" / "shopify"
        reports = list(report_dir.glob("*-boundary-verify.json")) \
            if report_dir.is_dir() else []
        self.assertEqual(reports, [])

    def test_execute_awaits_live_without_boundary_traffic(self):
        client = FakeBoundaryClient()
        result = self._execute(client, live=False)
        self.assertEqual(result["status"], "AWAITING_LIVE")
        self.assertEqual(client.requests, [])
        self.assertEqual(client.verify_calls, [])

    def test_missing_socket_fails_closed(self):
        runner = bnd.shopify_execute_runner(
            live=True,
            trusted_writer_socket=str(self.root / "missing.sock"))
        with self.assertRaisesRegex(bnd.BindingError, "not available"):
            runner(self._entry(), self.manifest, self.digest)

    def test_per_call_flag_consistency(self):
        plain = bnd.shopify_execute_runner(live=True)
        with self.assertRaisesRegex(bnd.BindingError,
                                    "no trusted_writer_socket"):
            plain(self._entry(), self.manifest, self.digest,
                  trusted_writer=True)

        client = FakeBoundaryClient()
        configured = bnd.shopify_execute_runner(
            live=True, trusted_writer_client=client)
        with self.assertRaisesRegex(bnd.BindingError, "opt-out"):
            configured(self._entry(), self.manifest, self.digest,
                       trusted_writer=False)
        self.assertEqual(client.requests, [])

    def test_reconcile_settles_and_returns_verified_when_end_state_present(self):
        client = FakeBoundaryClient(verify_readbacks=[self._readback()])
        runner = bnd.shopify_reconcile_runner(trusted_writer_client=client)
        result = runner(self._entry(), self.manifest, self.digest)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(client.requests, [])
        self.assertEqual(len(client.verify_calls), 1)
        self.assertIn("boundary_operations", result["receipt"]["uploader_receipt"])

    def test_reconcile_reapplies_identical_requests_when_unsatisfied(self):
        unsatisfied = self._readback(title="drifted title")
        satisfied = self._readback()
        client = FakeBoundaryClient(verify_readbacks=[unsatisfied, satisfied])
        runner = bnd.shopify_reconcile_runner(trusted_writer_client=client)
        result = runner(self._entry(), self.manifest, self.digest)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(
            [payload["operation"] for payload in client.requests],
            ["update_details", "set_inventory", "media_append"])
        self.assertEqual(len(client.verify_calls), 2)

    def test_reconcile_refusal_is_pending_never_failed(self):
        client = FakeBoundaryClient(verify_outcome="REFUSED")
        runner = bnd.shopify_reconcile_runner(trusted_writer_client=client)
        result = runner(self._entry(), self.manifest, self.digest)
        self.assertEqual(result["status"], "PENDING_RECONCILIATION")
        self.assertEqual(client.requests, [])

    def test_bind_runners_forwards_boundary_configuration(self):
        client = FakeBoundaryClient(verify_readbacks=[self._readback()])
        runners = bnd.bind_runners(
            archive_root=self.root / "Archived", live=True,
            trusted_writer_client=client)
        self.assertEqual(
            set(runners),
            {"resolve", "preflight", "execute", "reconcile", "archive"})
        result = runners["execute"](self._entry(), self.manifest, self.digest)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(
            [payload["operation"] for payload in client.requests],
            ["update_details", "set_inventory", "media_append"])

    def test_default_no_boundary_path_unchanged(self):
        calls = []

        def uploader(argv):
            command = argv[2]
            calls.append(command)
            if command == "status":
                return {"manifest_sha256": self.digest, "items": [
                    {"tank_id": TANK, "stage": "NEW", "status": "PENDING"}]}
            if command == "execute":
                return {"manifest_sha256": self.digest,
                        "report_path": str(self.root / "execute.json"),
                        "items": [{"tank_id": TANK, "status": READBACK_PASS,
                                   "receipt": {"status": READBACK_PASS}}]}
            if command == "verify":
                report_path = _write_json(self.root / "verify.json", {
                    "command": "verify", "batch_id": BATCH_ID,
                    "manifest_sha256": self.digest,
                    "created_at": "2026-10-11T00:00:00+00:00",
                    "items": [{"tank_id": TANK, "status": READBACK_PASS}]})
                return {"manifest_sha256": self.digest,
                        "report_path": str(report_path),
                        "items": [{"tank_id": TANK, "status": READBACK_PASS}]}
            raise AssertionError(command)

        runner = bnd.shopify_execute_runner(live=True, runner=uploader)
        result = runner(self._entry(), self.manifest, self.digest)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(calls, ["status", "execute", "verify"])
        self.assertNotIn("boundary", result)
        self.assertTrue(
            Path(result["receipt"]["verify_report_path"]).is_file())

    def test_pinned_client_module_interface_when_present(self):
        path = PROJECT / "scripts" / "betta_write_client.py"
        if not path.is_file():
            self.skipTest(
                "R1 client module not on disk yet (concurrent build); "
                "interface is pinned by the brief and exercised via the "
                "injected fake")
        spec = importlib.util.spec_from_file_location("bwc_iface_t", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        client_class = getattr(module, "WriteBoundaryClient", None)
        self.assertIsNotNone(client_class, "WriteBoundaryClient must exist")
        init_params = set(inspect.signature(client_class.__init__).parameters)
        self.assertIn("socket_path", init_params)
        self.assertIn("timeout", init_params)
        for name in ("request", "status", "verify", "build_request"):
            self.assertTrue(callable(getattr(client_class, name, None)),
                            f"{name} must be callable")
        build_params = set(
            inspect.signature(client_class.build_request).parameters)
        self.assertTrue({
            "operation", "mode", "target", "evidence", "operations",
            "authorisation", "request_id"} <= build_params)


class PinnedDaemonSeamTests(BoundaryFixtureMixin, unittest.TestCase):
    """Cross-module seam: R2 payloads must satisfy R1's real daemon validators.

    Runs in-process against scripts/betta_write_client.py +
    scripts/betta_write_boundary.py when they are on disk (they are separate
    agents' files; while a parallel build is in flight this skips with reason).
    """

    def _modules(self):
        client_path = PROJECT / "scripts" / "betta_write_client.py"
        core_path = PROJECT / "scripts" / "betta_write_boundary.py"
        if not client_path.is_file() or not core_path.is_file():
            self.skipTest(
                "R1 client/core not on disk yet (concurrent build)")
        return (_load("bwc_seam_t", "betta_write_client.py"),
                _load("bwb_seam_t", "betta_write_boundary.py"))

    def test_built_requests_pass_the_pinned_daemon_validators(self):
        client_mod, core = self._modules()
        policy = json.loads(
            (DEPLOY / "boundary-policy.production.json").read_text(
                encoding="utf-8"))
        self.assertIsNone(core.validate_policy(policy))
        plan = bnd.boundary_operation_plan(
            self.item, baseline=self._entry()["product"]["before"])
        target = {
            field: self.item[field] for field in bnd._BOUNDARY_GID_PATTERNS}
        client = client_mod.WriteBoundaryClient("/nonexistent.sock")

        class _Ledger:
            def writes_today(self):
                return 0

            def idempotency_owner(self, fingerprint):
                return None

        for operation in plan["operations"]:
            detail = bnd._boundary_operation_detail(operation)
            evidence = bnd.boundary_evidence(
                self.item, manifest_path=str(self.manifest),
                manifest_sha256=self.digest, idempotency_detail=detail)
            payload = client.build_request(
                operation=operation["type"], mode="apply", target=target,
                evidence=evidence, operations=[operation],
                authorisation=dict(bnd.BOUNDARY_STANDING),
                request_id=bnd._boundary_request_id(
                    operation["type"], self.digest, TANK, detail))
            request, request_id = core._validate_request_shape(payload)
            self.assertEqual(uuid.UUID(request_id).version, 4)
            core.validate_operations(request)
            core._validate_target_for_operation(request)
            bindings = []
            if operation["type"] == "media_append":
                bindings = [
                    {"role": "hero", "size_bytes": 1234,
                     "mime_type": "image/png",
                     "sha256": self.item["hero"]["sha256"]},
                    {"role": "original", "size_bytes": 1234,
                     "mime_type": "image/jpeg",
                     "sha256": self.item["original"]["sha256"]},
                ]
            core.validate_operation_caps(
                request, policy, _Ledger(), media_bindings=bindings)
            before = {
                "product_id": target["product_id"],
                "variant_id": target["variant_id"],
                "title": f"{TANK} - Old Title",
                "arrival_date": "2026-10-01",
                "available": 0,
                "inventory_item_id": target["inventory_item_id"],
                "location_id": target["location_id"],
                "media": [],
            }
            core.assert_readback_target(request, before)
            core.cas_expectation(request, before)

        verify_payload = client.build_request(
            operation="verify", mode="apply", target=target,
            evidence=bnd.boundary_evidence(
                self.item, manifest_path=str(self.manifest),
                manifest_sha256=self.digest, idempotency_detail="verify"),
            operations=[], authorisation=None)
        request, _ = core._validate_request_shape(verify_payload)
        core._validate_target_for_operation(request)


class DeployArtifactTests(unittest.TestCase):
    INSTALLER = DEPLOY / "install-trusted-writer.sh"
    UNINSTALLER = DEPLOY / "uninstall-trusted-writer.sh"
    PLIST = DEPLOY / "com.nanotanksaustralia.betta-write.plist.template"
    SUDOERS = DEPLOY / "nta-betta-write.sudoers.template"
    POLICY = DEPLOY / "boundary-policy.production.json"

    def _run(self, argv, timeout=180):
        return subprocess.run(
            argv, cwd=str(PROJECT), capture_output=True, text=True,
            timeout=timeout)

    def test_installer_and_uninstaller_are_bash_valid(self):
        for script in (self.INSTALLER, self.UNINSTALLER):
            self.assertTrue(script.is_file(), f"missing {script}")
            result = self._run(["/bin/bash", "-n", str(script)])
            self.assertEqual(
                result.returncode, 0,
                f"bash -n failed for {script}: {result.stderr}")

    def test_installer_dry_run_prints_full_plan(self):
        result = self._run(["/bin/bash", str(self.INSTALLER), "--dry-run"])
        self.assertIn(result.returncode, (0, 1), result.stderr)
        output = result.stdout
        self.assertIn("DRY-RUN", output)
        self.assertIn("no changes were made", output.lower())
        self.assertIn("/usr/local/libexec/nta-betta-write", output)
        self.assertIn(
            "/Library/LaunchDaemons/com.nanotanksaustralia.betta-write.plist",
            output)
        self.assertIn("launchctl bootstrap", output)
        self.assertIn("version.json", output)
        self.assertIn("shopify.env", output)
        self.assertIn("sudoers", output)
        self.assertIn("/usr/local/bin/nta-betta-write", output)
        # The credential value / client secret must never appear, and the
        # installer must never read the credential file.
        self.assertNotIn("SHOPIFY_CLIENT_SECRET", output)
        script_text = self.INSTALLER.read_text(encoding="utf-8")
        self.assertIsNone(re.search(
            r"(cat|grep|awk|sed|tail|head|less|more|python3?)\s[^\n]*shopify\.env",
            script_text))

    def test_installer_dry_run_consent_mentions_sudoers_install(self):
        result = self._run([
            "/bin/bash", str(self.INSTALLER), "--dry-run",
            "--consent-timestamp-timeout"])
        self.assertIn(result.returncode, (0, 1), result.stderr)
        output = result.stdout
        self.assertIn("/etc/sudoers.d/nta-betta-write", output)
        self.assertIn("timestamp_timeout", self.SUDOERS.read_text())
        self.assertIn("visudo", output)

    def test_installer_refuses_without_root(self):
        if os.geteuid() == 0:
            self.skipTest("running as root")
        result = self._run(["/bin/bash", str(self.INSTALLER)])
        self.assertEqual(result.returncode, 2)
        self.assertIn("REFUSED", result.stdout)
        self.assertIn("root", result.stdout)

    def test_uninstaller_dry_run_plan(self):
        result = self._run(["/bin/bash", str(self.UNINSTALLER), "--dry-run"])
        self.assertIn(result.returncode, (0, 1), result.stderr)
        output = result.stdout
        self.assertIn("DRY-RUN", output)
        self.assertIn("bootout", output)
        self.assertIn("keep-state", output)
        self.assertIn("/usr/local/libexec/nta-betta-write", output)
        self.assertIn("state dir", output)
        self.assertIn("no changes were made", output.lower())

    def test_uninstaller_purge_state_requires_force(self):
        result = self._run([
            "/bin/bash", str(self.UNINSTALLER), "--dry-run", "--purge-state"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("--force", result.stdout)

    def test_uninstaller_refuses_without_root(self):
        if os.geteuid() == 0:
            self.skipTest("running as root")
        result = self._run(["/bin/bash", str(self.UNINSTALLER)])
        self.assertEqual(result.returncode, 2)
        self.assertIn("REFUSED", result.stdout)

    def test_plist_template_lints_and_stays_in_root_paths(self):
        text = self.PLIST.read_text(encoding="utf-8")
        for forbidden in ("/Users/", "~", "$HOME", "/tmp"):
            self.assertNotIn(forbidden, text)
        self.assertIn("<key>Label</key>", text)
        self.assertIn("com.nanotanksaustralia.betta-write", text)
        self.assertIn("/usr/bin/python3", text)
        self.assertIn(
            "/usr/local/libexec/nta-betta-write/betta_write_daemon.py", text)
        # R1's daemon requires explicit absolute arguments; pin them so the
        # plist can never start the daemon against the wrong paths.
        for argument in (
            "--socket", "/var/run/nta-betta-write/boundary.sock",
            "--state-dir", "/var/db/nta-betta-write",
            "--code-root", "/usr/local/libexec/nta-betta-write",
            "--socket-group", "staff",
        ):
            self.assertIn(argument, text)
        self.assertIn("/var/log/nta-betta-write.out.log", text)
        self.assertIn("/var/log/nta-betta-write.err.log", text)
        self.assertIn("<key>KeepAlive</key>", text)
        self.assertIn("<key>RunAtLoad</key>", text)
        self.assertIn("<key>ProcessType</key>", text)
        self.assertNotIn("<key>EnvironmentVariables</key>", text)
        if not shutil.which("plutil"):
            self.skipTest("plutil unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            rendered = Path(tmp) / "boundary.plist"
            rendered.write_text(text, encoding="utf-8")
            result = self._run(["/usr/bin/plutil", "-lint", str(rendered)])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sudoers_template_lints_when_visudo_available(self):
        visudo = shutil.which("visudo") or (
            "/usr/sbin/visudo" if Path("/usr/sbin/visudo").is_file() else None)
        if not visudo:
            self.skipTest("visudo unavailable on this host")
        text = self.SUDOERS.read_text(encoding="utf-8")
        self.assertIn("Defaults:davidlo timestamp_timeout=0", text)
        self.assertIn("timestamp_timeout=0", text)
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "nta-betta-write.sudoers"
            candidate.write_text(text, encoding="utf-8")
            result = self._run([visudo, "-c", "-f", str(candidate)])
            combined = result.stdout + result.stderr
            if result.returncode != 0 and "parsed OK" not in combined:
                if "Permission" in combined or "may not" in combined:
                    self.skipTest(f"visudo unavailable here: {combined.strip()}")
                self.fail(f"sudoers template failed visudo -c -f: {combined}")

    def test_production_policy_is_conservative(self):
        policy = json.loads(self.POLICY.read_text(encoding="utf-8"))
        self.assertEqual(policy["schema"], bnd.BOUNDARY_POLICY_SCHEMA)
        self.assertEqual(policy["version"], 1)
        self.assertEqual(policy["allowed_uids"], [501])
        self.assertEqual(
            policy["allowed_roots"],
            ["/Users/davidlo/Documents/Betta Processing/batches"])
        operations = policy["operations"]
        self.assertTrue(operations["update_details"]["standing"])
        self.assertEqual(operations["update_details"]["fields"],
                         ["title", "arrival_date"])
        self.assertTrue(operations["set_inventory"]["standing"])
        self.assertEqual(operations["set_inventory"]["allowed_from"], [0])
        self.assertEqual(operations["set_inventory"]["target"], 1)
        self.assertEqual(operations["set_inventory"]["reasons"], ["received"])
        self.assertTrue(operations["media_append"]["standing"])
        self.assertEqual(operations["media_append"]["max_assets"], 2)
        self.assertEqual(
            operations["media_append"]["mime_types"],
            ["image/png", "image/jpeg"])
        self.assertFalse(operations["merch_update"]["standing"])
        self.assertEqual(policy["budgets"]["max_operations_per_request"], 6)
        self.assertEqual(policy["budgets"]["max_daily_writes"], 60)

    def test_production_policy_passes_pinned_daemon_validator(self):
        module_path = PROJECT / "scripts" / "betta_write_boundary.py"
        if not module_path.is_file():
            self.skipTest("R1 boundary core not on disk yet (concurrent build)")
        core = _load("betta_write_boundary_policy_t", "betta_write_boundary.py")
        policy = json.loads(self.POLICY.read_text(encoding="utf-8"))
        self.assertEqual(policy["schema"], core.POLICY_SCHEMA)
        self.assertIsNone(
            core.validate_policy(policy),
            "production policy must pass the pinned daemon validator")

    def test_deploy_files_never_embed_credentials(self):
        for path in sorted(DEPLOY.iterdir()):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8").lower()
            for marker in ("shpat_", "shpss_", "shpca_", "client_secret=",
                           "access_token=", "begin private key"):
                self.assertNotIn(
                    marker, text, f"credential-like marker in {path.name}")


if __name__ == "__main__":
    unittest.main()
