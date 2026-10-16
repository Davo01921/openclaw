"""Hermetic tests for the trusted Shopify write boundary (H1 mitigation).

Covers the core validation pipeline, authorisation records, corrections reuse,
evidence/manifest binding, replay/idempotency, budgets, receipts, the fake
Shopify happy paths for every operation, reconciliation semantics and the
daemon/client round-trip (including a spawned daemon subprocess and a fake
Shopify HTTP endpoint).

None of these tests requires root: all state lives in TEMP directories and the
Shopify HTTP layer is faked. The daemon subprocess is spawned with Apple's
``/usr/bin/python3`` when present to prove Python 3.9 compatibility end to end.
"""

import hashlib
import http.server
import importlib.util
import io
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
PYTHON39 = "/usr/bin/python3"

SOURCE = "a" * 64
TANK = "2BT23"
DETECTED_WRONG = "5BT43"
PRODUCT = "gid://shopify/Product/7255867588817"
VARIANT = "gid://shopify/ProductVariant/41571765453009"
INVENTORY_ITEM = "gid://shopify/InventoryItem/45246295916657"
LOCATION = "gid://shopify/Location/65024483441"
IDENTITY_FIELDS = ["title", "arrival_date", "inventory", "media"]

FAKE_TOKEN = "fake-access-token"
FAKE_SECRET = "super-secret-value-do-not-log-12345"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


boundary = _load("betta_write_boundary_tests", "betta_write_boundary.py")
corrections = _load("betta_corrections_wb_tests", "betta_corrections.py")
daemon_mod = _load("betta_write_daemon_tests", "betta_write_daemon.py")
client_mod = _load("betta_write_client_tests", "betta_write_client.py")
admin_mod = _load("betta_write_admin_tests", "betta_write_admin.py")


# ---------------------------------------------------------------------------
# Fakes and fixtures
# ---------------------------------------------------------------------------


def _sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def png_bytes(payload=b"\x00\x00\x00\x00"):
    import struct
    import zlib

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) +
            chunk(b"IDAT", zlib.compress(payload)) + chunk(b"IEND", b""))


def jpeg_bytes():
    return b"\xff\xd8\xff\xe0" + b"\x00" * 32 + b"\xff\xd9"


class FakeShopify:
    """In-process Shopify service fake with failure injection and a call log."""

    def __init__(self):
        self.product = {
            "product_id": PRODUCT,
            "variant_id": VARIANT,
            "inventory_item_id": INVENTORY_ITEM,
            "location_id": LOCATION,
            "title": f"{TANK} - old title",
            "arrival_date": "2026-10-01",
            "available": 0,
            "inventory_quantity": 0,
            "status": "ACTIVE",
            "vendor": "NTA",
            "price": "35.00",
            "cost": "10.00",
            "description_sha256": "d" * 64,
            "inventory_policy": "DENY",
            "tracked": True,
            "media": [],
        }
        self.calls = []
        self.fail_uncertain = set()
        self.fail_uncertain_after_apply = set()
        self.fail_rejected = set()
        self.mutate_protected_on = set()

    # -- reads -------------------------------------------------------------

    def read_product(self, product_id, location_id=None):
        self.calls.append(("read", product_id))
        return dict(self.product)

    # -- writes ------------------------------------------------------------

    def _prepare(self, operation):
        if operation in self.fail_rejected:
            raise boundary.ShopifyRejectedError(f"{operation} rejected by fake")
        if operation in self.fail_uncertain:
            raise boundary.ShopifyUncertainError(f"{operation} uncertain by fake")

    def apply_update_details(self, product_id, fields):
        self.calls.append(("update_details", dict(fields)))
        self._prepare("update_details")
        self.product.update(fields)
        if "update_details" in self.mutate_protected_on:
            self.product["price"] = "99.99"
        if "update_details" in self.fail_uncertain_after_apply:
            raise boundary.ShopifyUncertainError("update_details uncertain after apply")
        return {"updated": sorted(fields)}

    def apply_set_inventory(self, *, inventory_item_id, location_id, quantity,
                            reason, change_from, reference_document_uri,
                            idempotency_key):
        self.calls.append(("set_inventory", quantity, change_from, reason,
                           idempotency_key))
        self._prepare("set_inventory")
        self.product["available"] = quantity
        self.product["inventory_quantity"] = quantity
        if "set_inventory" in self.fail_uncertain_after_apply:
            raise boundary.ShopifyUncertainError("set_inventory uncertain after apply")
        return {"quantity": quantity}

    def apply_media_append(self, *, product_id, assets, batch_id, tank,
                           poll_attempts, poll_interval):
        self.calls.append(("media_append", [asset["role"] for asset in assets]))
        self._prepare("media_append")
        new_media = [
            {"id": f"gid://shopify/MediaImage/{900 + index}",
             "alt": asset["alt"], "status": "READY"}
            for index, asset in enumerate(assets)
        ]
        self.product["media"] = new_media + self.product["media"]
        if "media_append" in self.fail_uncertain_after_apply:
            raise boundary.ShopifyUncertainError("media_append uncertain after apply")
        return {"media_ids": [value["id"] for value in new_media]}

    def apply_merch_update(self, *, product_id, variant_id, inventory_item_id,
                           fields):
        self.calls.append(("merch_update", dict(fields)))
        self._prepare("merch_update")
        self.product.update(fields)
        if "merch_update" in self.fail_uncertain_after_apply:
            raise boundary.ShopifyUncertainError("merch_update uncertain after apply")
        return {"updated": sorted(fields)}

    def write_calls(self):
        return [call for call in self.calls if call[0] != "read"]


class Fixture:
    """One hermetic boundary environment in a temporary directory."""

    def __init__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.state.mkdir()
        self.batch_root = self.root / "batches"
        self.batch_root.mkdir()
        self.paths = boundary.BoundaryPaths(self.state)
        self.paths.ensure_dirs()
        self.policy = boundary.default_policy()
        self.policy["allowed_roots"] = [str(self.batch_root)]
        self.write_policy()
        self.identity = {
            "source_sha256": SOURCE,
            "detected_tank": TANK,
            "requested_tank": TANK,
            "accepted_tank": TANK,
            "correction_sha256": None,
        }
        self.manifest = {
            "schema": boundary.MANIFEST_SCHEMA,
            "batch_id": "batch-wb-test-01",
            "items": [{
                "tank_id": TANK,
                "product_id": PRODUCT,
                "variant_id": VARIANT,
                "inventory_item_id": INVENTORY_ITEM,
                "location_id": LOCATION,
                "original": {"sha256": SOURCE},
                "identity": self.identity,
            }],
        }
        self.manifest_path = self.batch_root / "manifest.json"
        self.write_manifest()
        self.shopify = FakeShopify()
        self.engine = boundary.BoundaryEngine(
            self.paths, corrections_path=SCRIPTS / "betta_corrections.py")

    # -- policy / manifest -------------------------------------------------

    def write_policy(self):
        boundary.atomic_write_json(self.paths.policy_path, self.policy)

    def write_manifest(self, manifest=None):
        payload = self.manifest if manifest is None else manifest
        self.manifest_path.write_text(json.dumps(payload))
        self.manifest_sha = _sha256_bytes(self.manifest_path.read_bytes())
        return self.manifest_path

    def evidence(self, **overrides):
        evidence = {
            "manifest_path": str(self.manifest_path),
            "manifest_sha256": self.manifest_sha,
            "source_sha256": SOURCE,
            "identity": dict(self.identity),
            "correction_sha256": self.identity.get("correction_sha256"),
            "qa_receipt_sha256": None,
            "idempotency_key": f"key-{uuid.uuid4().hex[:12]}",
        }
        evidence.update(overrides)
        return evidence

    def request(self, operation, operations, *, evidence=None, authorisation=None,
                mode="apply", target=None, request_id=None):
        if target is None:
            target = ({} if operation == "status" else
                      {"product_id": PRODUCT, "variant_id": VARIANT})
        payload = {
            "schema": boundary.REQUEST_SCHEMA,
            "request_id": request_id or str(uuid.uuid4()),
            "operation": operation,
            "mode": mode,
            "target": target,
            "operations": list(operations),
        }
        if authorisation is not None:
            payload["authorisation"] = authorisation
        if evidence is not None:
            payload["evidence"] = evidence
        return payload

    # -- convenience operations -------------------------------------------

    def standing(self):
        return {"kind": "standing"}

    def update_details_request(self, *, title=None, arrival=None, expected=None,
                               request_id=None, evidence=None, mode="apply",
                               authorisation=None):
        operations = {"type": "update_details"}
        if title is not None:
            operations["title"] = title
        if arrival is not None:
            operations["arrival_date"] = arrival
        if expected is not None:
            operations["expected"] = expected
        return self.request(
            "update_details", [operations],
            evidence=evidence or self.evidence(),
            authorisation=authorisation or self.standing(),
            request_id=request_id, mode=mode)

    def handle(self, request, *, shopify=None, peer_uid=501):
        return self.engine.handle(
            request, peer_uid=peer_uid,
            shopify=self.shopify if shopify is None else shopify)

    # -- authorisations / corrections -------------------------------------

    def authorise(self, *, fields, tank=TANK, product=PRODUCT, variant=VARIANT,
                  source_sha256=SOURCE, expires_in_hours=24.0, created_at=None):
        return boundary.write_authorisation_record(
            self.paths, source_sha256=source_sha256, tank=tank,
            product_id=product, variant_id=variant, fields=fields,
            reason="owner approved", operator="owner",
            expires_in_hours=expires_in_hours, created_at=created_at)

    def owner_auth(self, path):
        record = json.loads(Path(path).read_text())
        return {"kind": "owner",
                "authorisation_sha256": record["authorisation_sha256"]}

    def craft_correction(self, *, detected=DETECTED_WRONG, corrected=TANK,
                         source_sha256=SOURCE, product_id=PRODUCT,
                         variant_id=VARIANT, fields=None):
        fields = fields if fields is not None else list(IDENTITY_FIELDS)
        core = {
            "schema": corrections.SCHEMA,
            "source_sha256": source_sha256,
            "original_model_tank": detected,
            "corrected_tank": corrected,
            "product_id": product_id,
            "variant_id": variant_id,
            "operation": {"fields": sorted(fields), "mode": "owner-directed"},
            "reason": "owner confirmed the card",
            "evidence_reference": "discord:message:1",
            "operator": "owner",
            "created_at": "2026-10-15T09:00:00+11:00",
        }
        digest = corrections.json_sha256(core)
        payload = {**core, "correction_sha256": digest}
        path = self.paths.corrections_dir / f"correction-{digest}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return digest

    def corrected_identity(self, digest):
        return {
            "source_sha256": SOURCE,
            "detected_tank": DETECTED_WRONG,
            "requested_tank": TANK,
            "accepted_tank": TANK,
            "correction_sha256": digest,
        }

    def use_corrected_identity(self, digest):
        self.identity = self.corrected_identity(digest)
        self.manifest["items"][0]["identity"] = dict(self.identity)
        self.write_manifest()

    def close(self):
        self.temp.cleanup()


# ---------------------------------------------------------------------------
# Policy + environment hostile tests
# ---------------------------------------------------------------------------


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture()
        self.addCleanup(self.fixture.close)

    def test_default_policy_validates(self):
        self.assertIsNone(boundary.validate_policy(boundary.default_policy()))

    def test_policy_merch_standing_is_rejected(self):
        policy = boundary.default_policy()
        policy["operations"]["merch_update"]["standing"] = True
        self.assertEqual("policy_merch_standing_forbidden",
                         boundary.validate_policy(policy))

    def test_policy_relative_allowed_root_is_rejected(self):
        policy = boundary.default_policy()
        policy["allowed_roots"] = ["relative/path"]
        self.assertEqual("policy_allowed_roots_invalid",
                         boundary.validate_policy(policy))

    def test_policy_missing_fails_closed_but_status_reports(self):
        os.unlink(self.fixture.paths.policy_path)
        response = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"}))
        self.assertEqual(boundary.OUTCOME_REFUSED, response["outcome"])
        self.assertEqual(boundary.ERR_OPERATION_NOT_ALLOWED, response["error_code"])
        status = self.fixture.handle(self.fixture.request("status", []))
        self.assertTrue(status["ok"])
        self.assertFalse(status["readback"]["policy_loaded"])
        self.assertEqual("policy_missing", status["readback"]["policy_error"])

    def test_hostile_environment_variables_have_no_effect(self):
        permissive = self.fixture.root / "permissive.json"
        policy = boundary.default_policy()
        policy["operations"]["merch_update"]["standing"] = True
        policy["allowed_uids"] = [0, 501, 999]
        permissive.write_text(json.dumps(policy))
        hostile = {
            "NTA_BETTA_WRITE_POLICY": str(permissive),
            "BOUNDARY_POLICY": str(permissive),
            "NTA_BETTA_WRITE_STATE_DIR": str(self.fixture.root / "elsewhere"),
            "NTA_BETTA_WRITE_ALLOWED_UIDS": "0,501,999",
            "BETTA_WRITE_ENABLED": "true",
            "NTA_BETTA_BATCH_WRITE_ENABLED": "true",
            "SHOPIFY_ACCESS_TOKEN": "stolen-token",
        }
        previous = {key: os.environ.get(key) for key in hostile}
        try:
            os.environ.update(hostile)
            status = self.fixture.handle(self.fixture.request("status", []))
            self.assertEqual([501], status["readback"]["allowed_uids"])
            self.assertFalse(
                status["readback"]["operations"]["merch_update"]["standing"])
            response = self.fixture.handle(self.fixture.request(
                "merch_update",
                [{"type": "merch_update", "vendor": "EVIL",
                  "expected": {"vendor": "NTA"}}],
                evidence=self.fixture.evidence(),
                authorisation={"kind": "standing"},
                target={"product_id": PRODUCT, "variant_id": VARIANT,
                        "inventory_item_id": INVENTORY_ITEM}))
            self.assertEqual(boundary.ERR_AUTHORISATION_INVALID,
                             response["error_code"])
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


# ---------------------------------------------------------------------------
# Authorisation records
# ---------------------------------------------------------------------------


class AuthorisationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture()
        self.addCleanup(self.fixture.close)

    def test_record_roundtrip_and_derived_operation_class(self):
        path = self.fixture.authorise(fields=["title", "title", "arrival_date"])
        record = json.loads(Path(path).read_text())
        self.assertEqual(boundary.AUTHORISATION_SCHEMA, record["schema"])
        self.assertEqual(["arrival_date", "title"], record["fields"])
        self.assertEqual("update_details", record["operation_class"])
        self.assertEqual(0o444, stat.S_IMODE(os.stat(path).st_mode))
        self.assertEqual(
            record["authorisation_sha256"],
            boundary.json_sha256({key: value for key, value in record.items()
                                  if key != "authorisation_sha256"}))

    def test_expired_record_rejected(self):
        path = self.fixture.authorise(fields=["title"])
        record = json.loads(Path(path).read_text())
        record["expires_at"] = "2026-01-01T00:00:00+00:00"
        record["created_at"] = "2025-12-01T00:00:00+00:00"
        core = {key: value for key, value in record.items()
                if key != "authorisation_sha256"}
        record["authorisation_sha256"] = boundary.json_sha256(core)
        ok, reason = boundary.validate_authorisation(
            record, operation="update_details", required_fields=["title"],
            target={"product_id": PRODUCT, "variant_id": VARIANT},
            source_sha256=SOURCE)
        self.assertFalse(ok)
        self.assertEqual("expired", reason)

    def test_self_hash_tamper_rejected_by_engine(self):
        path = self.fixture.authorise(fields=["title"])
        record = json.loads(Path(path).read_text())
        record["fields"] = ["title", "arrival_date"]
        tampered = self.fixture.paths.authorisations_dir / (
            f"authorisation-{record['authorisation_sha256']}.json")
        tampered.chmod(0o644)
        tampered.write_text(json.dumps(record))
        response = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"},
            authorisation=self.fixture.owner_auth(path)))
        self.assertEqual(boundary.ERR_AUTHORISATION_INVALID, response["error_code"])
        self.assertIn("self_hash_mismatch", response["detail"])

    def test_field_scope_mismatch_rejected(self):
        path = self.fixture.authorise(fields=["title"])
        response = self.fixture.handle(self.fixture.update_details_request(
            arrival="2026-10-20", expected={"arrival_date": "2026-10-01"},
            authorisation=self.fixture.owner_auth(path)))
        self.assertEqual(boundary.ERR_AUTHORISATION_INVALID, response["error_code"])
        self.assertIn("field_scope_mismatch", response["detail"])

    def test_variant_and_source_bindings_are_exact(self):
        path = self.fixture.authorise(
            fields=["title"], variant="gid://shopify/ProductVariant/999")
        response = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"},
            authorisation=self.fixture.owner_auth(path)))
        self.assertEqual(boundary.ERR_AUTHORISATION_INVALID, response["error_code"])
        self.assertIn("variant_id_mismatch", response["detail"])

        other = self.fixture.authorise(fields=["vendor"],
                                       source_sha256="b" * 64)
        response = self.fixture.handle(self.fixture.request(
            "merch_update",
            [{"type": "merch_update", "vendor": "X", "expected": {"vendor": "NTA"}}],
            evidence=self.fixture.evidence(),
            authorisation=self.fixture.owner_auth(other),
            target={"product_id": PRODUCT, "variant_id": VARIANT,
                    "inventory_item_id": INVENTORY_ITEM}))
        self.assertEqual(boundary.ERR_AUTHORISATION_INVALID, response["error_code"])
        self.assertIn("source_sha256_mismatch", response["detail"])

    def test_owner_authorisation_is_single_use(self):
        path = self.fixture.authorise(fields=["title", "arrival_date"])
        auth = self.fixture.owner_auth(path)
        first = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"},
            authorisation=auth))
        self.assertEqual(boundary.OUTCOME_APPLIED, first["outcome"])
        second = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - newer", expected={"title": f"{TANK} - new"},
            authorisation=auth))
        self.assertEqual(boundary.ERR_AUTHORISATION_INVALID, second["error_code"])
        self.assertIn("consumed", second["detail"])

    def test_merch_standing_is_impossible(self):
        response = self.fixture.handle(self.fixture.request(
            "merch_update",
            [{"type": "merch_update", "vendor": "EVIL",
              "expected": {"vendor": "NTA"}}],
            evidence=self.fixture.evidence(), authorisation={"kind": "standing"},
            target={"product_id": PRODUCT, "variant_id": VARIANT,
                    "inventory_item_id": INVENTORY_ITEM}))
        self.assertEqual(boundary.ERR_AUTHORISATION_INVALID, response["error_code"])
        self.assertEqual([], self.fixture.shopify.write_calls())

    def test_owner_merch_update_applies_with_full_field_scope(self):
        path = self.fixture.authorise(fields=["vendor", "price", "cost"])
        response = self.fixture.handle(self.fixture.request(
            "merch_update",
            [{"type": "merch_update", "vendor": "NewVendor", "price": "42.50",
              "cost": "11.25",
              "expected": {"vendor": "NTA", "price": "35.00", "cost": "10.00"}}],
            evidence=self.fixture.evidence(),
            authorisation=self.fixture.owner_auth(path),
            target={"product_id": PRODUCT, "variant_id": VARIANT,
                    "inventory_item_id": INVENTORY_ITEM}))
        self.assertEqual(boundary.OUTCOME_APPLIED, response["outcome"],
                         response["detail"])
        self.assertEqual("NewVendor", self.fixture.shopify.product["vendor"])
        self.assertEqual("42.50", self.fixture.shopify.product["price"])
        self.assertEqual("11.25", self.fixture.shopify.product["cost"])
        self.assertEqual(f"{TANK} - old title",
                         self.fixture.shopify.product["title"])

    def test_admin_authorise_refuses_non_root(self):
        if os.geteuid() == 0:
            self.skipTest("test must run as a normal user")
        result = subprocess.run(
            [PYTHON39 if os.path.exists(PYTHON39) else sys.executable,
             str(SCRIPTS / "betta_write_admin.py"), "--state-dir",
             str(self.fixture.state), "authorise",
             "--source-sha", SOURCE, "--tank", TANK, "--product", PRODUCT,
             "--variant", VARIANT, "--fields", "title",
             "--reason", "test", "--operator", "attacker"],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(2, result.returncode)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("root", payload["error"])
        self.assertEqual([], list(
            self.fixture.paths.authorisations_dir.glob("authorisation-*.json")))


# ---------------------------------------------------------------------------
# Evidence + corrections
# ---------------------------------------------------------------------------


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture()
        self.addCleanup(self.fixture.close)

    def test_manifest_hash_mismatch_refused(self):
        evidence = self.fixture.evidence(manifest_sha256="b" * 64)
        response = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"},
            evidence=evidence))
        self.assertEqual(boundary.ERR_EVIDENCE_INVALID, response["error_code"])
        self.assertIn("manifest bytes", response["detail"])

    def test_manifest_outside_allowed_roots_refused(self):
        outside = self.fixture.root / "outside.json"
        outside.write_bytes(self.fixture.manifest_path.read_bytes())
        evidence = self.fixture.evidence(
            manifest_path=str(outside),
            manifest_sha256=_sha256_bytes(outside.read_bytes()))
        response = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"},
            evidence=evidence))
        self.assertEqual(boundary.ERR_EVIDENCE_INVALID, response["error_code"])
        self.assertIn("allowed roots", response["detail"])

    def test_manifest_target_product_mismatch_refused(self):
        manifest = json.loads(json.dumps(self.fixture.manifest))
        manifest["items"][0]["product_id"] = "gid://shopify/Product/123"
        self.fixture.write_manifest(manifest)
        response = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"}))
        self.assertEqual(boundary.ERR_EVIDENCE_INVALID, response["error_code"])
        self.assertIn("product differs", response["detail"])

    def test_detected_tank_mismatch_without_correction_refused(self):
        self.fixture.identity = {
            "source_sha256": SOURCE,
            "detected_tank": DETECTED_WRONG,
            "requested_tank": TANK,
            "accepted_tank": TANK,
            "correction_sha256": None,
        }
        self.fixture.manifest["items"][0]["identity"] = dict(self.fixture.identity)
        self.fixture.write_manifest()
        response = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"}))
        self.assertEqual(boundary.ERR_EVIDENCE_INVALID, response["error_code"])
        self.assertIn("without a correction", response["detail"])

    def test_valid_correction_enables_the_write(self):
        digest = self.fixture.craft_correction()
        self.fixture.use_corrected_identity(digest)
        response = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"}))
        self.assertEqual(boundary.OUTCOME_APPLIED, response["outcome"],
                         response["detail"])

    def test_tampered_correction_refused(self):
        digest = self.fixture.craft_correction()
        path = self.fixture.paths.corrections_dir / f"correction-{digest}.json"
        record = json.loads(path.read_text())
        record["corrected_tank"] = "9BT9"
        path.write_text(json.dumps(record))
        self.fixture.use_corrected_identity(digest)
        response = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"}))
        self.assertEqual(boundary.ERR_CORRECTION_INVALID, response["error_code"])
        self.assertIn("self_hash", response["detail"])

    def test_correction_for_a_different_source_refused(self):
        digest = self.fixture.craft_correction(source_sha256="b" * 64)
        self.fixture.use_corrected_identity(digest)
        response = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"}))
        self.assertEqual(boundary.ERR_CORRECTION_INVALID, response["error_code"])
        self.assertIn("source_sha256_mismatch", response["detail"])

    def test_no_op_correction_refused(self):
        digest = self.fixture.craft_correction(detected=TANK)
        self.fixture.use_corrected_identity(digest)
        response = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"}))
        self.assertEqual(boundary.ERR_CORRECTION_INVALID, response["error_code"])
        self.assertIn("no_op_correction", response["detail"])

    def test_correction_scope_must_cover_the_identity_operation_fields(self):
        digest = self.fixture.craft_correction(fields=["title"])
        self.fixture.use_corrected_identity(digest)
        response = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"}))
        self.assertEqual(boundary.ERR_CORRECTION_INVALID, response["error_code"])
        self.assertIn("operation_scope_mismatch", response["detail"])

    def test_malformed_qa_receipt_hash_refused(self):
        evidence = self.fixture.evidence(qa_receipt_sha256="not-a-sha")
        response = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"},
            evidence=evidence))
        self.assertEqual(boundary.ERR_EVIDENCE_INVALID, response["error_code"])


# ---------------------------------------------------------------------------
# Pipeline order refusals (distinct codes)
# ---------------------------------------------------------------------------


class PipelineRefusalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture()
        self.addCleanup(self.fixture.close)

    def test_peer_not_allowed(self):
        response = self.fixture.handle(
            self.fixture.update_details_request(
                title=f"{TANK} - new", expected={"title": f"{TANK} - old title"}),
            peer_uid=999)
        self.assertEqual(boundary.ERR_PEER_NOT_ALLOWED, response["error_code"])
        self.assertEqual([], self.fixture.shopify.calls)

    def test_bad_request_schema_and_uuid(self):
        payload = self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"})
        payload["schema"] = "wrong"
        response = self.fixture.handle(payload)
        self.assertEqual(boundary.ERR_BAD_REQUEST, response["error_code"])

        payload = self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"})
        payload["request_id"] = "not-a-uuid"
        response = self.fixture.handle(payload)
        self.assertEqual(boundary.ERR_BAD_REQUEST, response["error_code"])

        payload = self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"})
        payload["mode"] = "sideways"
        response = self.fixture.handle(payload)
        self.assertEqual(boundary.ERR_BAD_REQUEST, response["error_code"])

    def test_disabled_flag_fails_closed_for_every_operation(self):
        self.fixture.paths.disabled_path.write_text("disabled")
        status = self.fixture.handle(self.fixture.request("status", []))
        self.assertEqual(boundary.ERR_BOUNDARY_DISABLED, status["error_code"])
        response = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"}))
        self.assertEqual(boundary.ERR_BOUNDARY_DISABLED, response["error_code"])
        self.assertEqual([], self.fixture.shopify.calls)

    def test_unknown_or_disabled_operation_refused(self):
        payload = self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"})
        payload["operation"] = "reorder_media"
        response = self.fixture.handle(payload)
        self.assertEqual(boundary.ERR_OPERATION_NOT_ALLOWED, response["error_code"])

        policy = dict(self.fixture.policy)
        policy["operations"] = dict(policy["operations"])
        policy["operations"].pop("update_details")
        boundary.atomic_write_json(self.fixture.paths.policy_path, policy)
        response = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"}))
        self.assertEqual(boundary.ERR_OPERATION_NOT_ALLOWED, response["error_code"])

    def test_replay_with_same_id_different_body_rejected(self):
        request = self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"})
        first = self.fixture.handle(request)
        self.assertEqual(boundary.OUTCOME_APPLIED, first["outcome"])
        mutated = dict(request)
        mutated["operations"] = [{"type": "update_details",
                                  "title": f"{TANK} - EVIL",
                                  "expected": {"title": f"{TANK} - new"}}]
        second = self.fixture.handle(mutated)
        self.assertEqual(boundary.ERR_REPLAY_REJECTED, second["error_code"])
        self.assertEqual(1, len(self.fixture.shopify.write_calls()))

    def test_duplicate_idempotency_key_rejected(self):
        key = "duplicate-key-1"
        first = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"},
            evidence=self.fixture.evidence(idempotency_key=key)))
        self.assertEqual(boundary.OUTCOME_APPLIED, first["outcome"])
        second = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - newer", expected={"title": f"{TANK} - new"},
            evidence=self.fixture.evidence(idempotency_key=key)))
        self.assertEqual(boundary.ERR_DUPLICATE_OPERATION, second["error_code"])
        self.assertEqual(1, len(self.fixture.shopify.write_calls()))

    def test_policy_refused_field_allowlist(self):
        policy = dict(self.fixture.policy)
        policy["operations"] = dict(policy["operations"])
        policy["operations"]["update_details"] = {
            "standing": True, "fields": ["title"]}
        boundary.atomic_write_json(self.fixture.paths.policy_path, policy)
        response = self.fixture.handle(self.fixture.update_details_request(
            arrival="2026-10-20", expected={"arrival_date": "2026-10-01"}))
        self.assertEqual(boundary.ERR_POLICY_REFUSED, response["error_code"])
        self.assertEqual([], self.fixture.shopify.write_calls())

    def test_policy_refused_daily_budget_exhausted(self):
        policy = dict(self.fixture.policy)
        policy["budgets"] = dict(policy["budgets"])
        policy["budgets"]["max_daily_writes"] = 0
        boundary.atomic_write_json(self.fixture.paths.policy_path, policy)
        response = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"}))
        self.assertEqual(boundary.ERR_POLICY_REFUSED, response["error_code"])
        self.assertIn("budget", response["detail"])
        self.assertEqual([], self.fixture.shopify.write_calls())

    def test_baseline_drift_refused_without_mutation(self):
        response = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": "SOMETHING ELSE"}))
        self.assertEqual(boundary.ERR_BASELINE_DRIFT, response["error_code"])
        self.assertEqual([], self.fixture.shopify.write_calls())

    def test_fresh_readback_target_mismatch_refused(self):
        self.fixture.shopify.product["product_id"] = "gid://shopify/Product/999"
        response = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"}))
        self.assertEqual(boundary.ERR_BASELINE_DRIFT, response["error_code"])

    def test_missing_shopify_service_refused(self):
        response = self.fixture.engine.handle(
            self.fixture.update_details_request(
                title=f"{TANK} - new", expected={"title": f"{TANK} - old title"}),
            peer_uid=501, shopify=None)
        self.assertEqual(boundary.ERR_SHOPIFY_UNAVAILABLE, response["error_code"])

    def test_bad_request_missing_target_binding(self):
        response = self.fixture.handle(self.fixture.request(
            "set_inventory",
            [{"type": "set_inventory", "quantity": 1, "reason": "received",
              "expected": {"available": 0}}],
            evidence=self.fixture.evidence(),
            authorisation={"kind": "standing"},
            target={"product_id": PRODUCT, "variant_id": VARIANT,
                    "location_id": LOCATION}))
        self.assertEqual(boundary.ERR_BAD_REQUEST, response["error_code"])

    def test_status_round_trip_without_secrets(self):
        response = self.fixture.handle(self.fixture.request("status", []))
        self.assertTrue(response["ok"])
        self.assertEqual(boundary.OUTCOME_STATUS, response["outcome"])
        serialised = json.dumps(response)
        self.assertNotIn("client_secret", serialised)
        self.assertNotIn("access_token", serialised)


# ---------------------------------------------------------------------------
# Happy paths (in-process FakeShopify)
# ---------------------------------------------------------------------------


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture()
        self.addCleanup(self.fixture.close)

    def test_update_details_applies_and_signs_receipt(self):
        response = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new title",
            arrival="2026-10-20",
            expected={"title": f"{TANK} - old title",
                      "arrival_date": "2026-10-01"}))
        self.assertEqual(boundary.OUTCOME_APPLIED, response["outcome"],
                         response["detail"])
        receipt = response["receipt"]
        self.assertEqual(boundary.RECEIPT_SCHEMA, receipt["schema"])
        self.assertEqual(f"{TANK} - new title", receipt["after"]["title"])
        self.assertEqual("2026-10-01", receipt["before"]["arrival_date"])
        self.assertEqual("UNCHANGED", receipt["checks"]["protected"])
        key = boundary.load_signing_key(self.fixture.paths.signing_key_path)
        self.assertEqual((True, "ok"),
                         boundary.verify_receipt_object(receipt, key))
        self.assertTrue(response["receipt_signature"].startswith("hmac-sha256:"))

    def test_dry_run_validates_but_never_writes_or_spends_budget(self):
        response = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"},
            mode="dry_run"))
        self.assertEqual(boundary.OUTCOME_DRY_RUN, response["outcome"],
                         response["detail"])
        self.assertTrue(response["ok"])  # validated preflight, nothing written
        self.assertEqual("dry_run", response["receipt"]["mode"])
        self.assertEqual([], self.fixture.shopify.write_calls())
        ledger = boundary.Ledger(self.fixture.paths.ledger_path)
        self.assertEqual(0, ledger.writes_today())

    def test_set_inventory_applies_with_reference_and_key(self):
        response = self.fixture.handle(self.fixture.request(
            "set_inventory",
            [{"type": "set_inventory", "quantity": 1, "reason": "received",
              "expected": {"available": 0}}],
            evidence=self.fixture.evidence(idempotency_key="inv-key-1"),
            authorisation={"kind": "standing"},
            target={"product_id": PRODUCT, "variant_id": VARIANT,
                    "inventory_item_id": INVENTORY_ITEM, "location_id": LOCATION}))
        self.assertEqual(boundary.OUTCOME_APPLIED, response["outcome"],
                         response["detail"])
        call = [value for value in self.fixture.shopify.calls
                if value[0] == "set_inventory"][0]
        self.assertEqual(1, call[1])
        self.assertEqual(0, call[2])
        self.assertEqual("received", call[3])
        self.assertEqual("inv-key-1", call[4])
        self.assertEqual(1, self.fixture.shopify.product["available"])

    def test_set_inventory_baseline_outside_policy_refused(self):
        response = self.fixture.handle(self.fixture.request(
            "set_inventory",
            [{"type": "set_inventory", "quantity": 1, "reason": "received",
              "expected": {"available": 7}}],
            evidence=self.fixture.evidence(idempotency_key="inv-key-2"),
            authorisation={"kind": "standing"},
            target={"product_id": PRODUCT, "variant_id": VARIANT,
                    "inventory_item_id": INVENTORY_ITEM, "location_id": LOCATION}))
        self.assertEqual(boundary.ERR_POLICY_REFUSED, response["error_code"])
        self.assertEqual([], self.fixture.shopify.write_calls())

    def test_set_inventory_quantity_not_target_refused(self):
        response = self.fixture.handle(self.fixture.request(
            "set_inventory",
            [{"type": "set_inventory", "quantity": 5, "reason": "received",
              "expected": {"available": 0}}],
            evidence=self.fixture.evidence(idempotency_key="inv-key-3"),
            authorisation={"kind": "standing"},
            target={"product_id": PRODUCT, "variant_id": VARIANT,
                    "inventory_item_id": INVENTORY_ITEM, "location_id": LOCATION}))
        self.assertEqual(boundary.ERR_POLICY_REFUSED, response["error_code"])

    def _media_request(self, roles=("original", "hero"), **evidence_overrides):
        assets = {"hero": png_bytes(b"hero"), "original": png_bytes(b"original")}
        entries = []
        for role in roles:
            path = self.fixture.batch_root / f"{role}.png"
            path.write_bytes(assets[role])
            entries.append({
                "path": str(path),
                "sha256": _sha256_bytes(path.read_bytes()),
                "role": role,
            })
        return self.fixture.request(
            "media_append", [{"type": "media_append", "assets": entries}],
            evidence=self.fixture.evidence(**evidence_overrides),
            authorisation={"kind": "standing"})

    def test_media_append_applies_hero_first_then_original(self):
        self.fixture.shopify.product["media"] = [
            {"id": "gid://shopify/MediaImage/1", "alt": "old", "status": "READY"}]
        response = self.fixture.handle(self._media_request())
        self.assertEqual(boundary.OUTCOME_APPLIED, response["outcome"],
                         response["detail"])
        media_calls = [value for value in self.fixture.shopify.calls
                       if value[0] == "media_append"]
        self.assertEqual([("media_append", ["hero", "original"])], media_calls)
        media = self.fixture.shopify.product["media"]
        self.assertEqual(3, len(media))
        self.assertIn("|HERO|sha256=", media[0]["alt"])
        self.assertIn("|ORIGINAL|sha256=", media[1]["alt"])
        self.assertEqual("old", media[2]["alt"])
        receipt = response["receipt"]
        self.assertEqual([media[0]["id"], media[1]["id"]],
                         [value["id"] for value in receipt["after"]["media"][:2]])

    def test_media_append_duplicate_alt_refused(self):
        first = self.fixture.handle(self._media_request())
        self.assertEqual(boundary.OUTCOME_APPLIED, first["outcome"],
                         first["detail"])
        duplicate = self.fixture.handle(self._media_request())
        self.assertEqual(boundary.ERR_POLICY_REFUSED, duplicate["error_code"])
        self.assertIn("already exists", duplicate["detail"])
        media_calls = [value for value in self.fixture.shopify.calls
                       if value[0] == "media_append"]
        self.assertEqual(1, len(media_calls))

    def test_media_append_asset_sha_mismatch_refused(self):
        request = self._media_request()
        request["operations"][0]["assets"][0]["sha256"] = "c" * 64
        response = self.fixture.handle(request)
        self.assertEqual(boundary.ERR_EVIDENCE_INVALID, response["error_code"])
        self.assertEqual([], self.fixture.shopify.write_calls())

    def test_media_append_non_image_refused(self):
        request = self._media_request()
        text_path = self.fixture.batch_root / "not-an-image.txt"
        text_path.write_bytes(b"plain text, not an image")
        request["operations"][0]["assets"][0]["path"] = str(text_path)
        request["operations"][0]["assets"][0]["sha256"] = _sha256_bytes(
            text_path.read_bytes())
        response = self.fixture.handle(request)
        self.assertEqual(boundary.ERR_EVIDENCE_INVALID, response["error_code"])

    def test_media_append_policy_mime_subset_refused(self):
        jpeg_path = self.fixture.batch_root / "photo.jpg"
        jpeg_path.write_bytes(jpeg_bytes())
        policy = dict(self.fixture.policy)
        policy["operations"] = dict(policy["operations"])
        policy["operations"]["media_append"] = dict(
            policy["operations"]["media_append"])
        policy["operations"]["media_append"]["mime_types"] = ["image/png"]
        boundary.atomic_write_json(self.fixture.paths.policy_path, policy)
        request = self._media_request()
        request["operations"][0]["assets"][0]["path"] = str(jpeg_path)
        request["operations"][0]["assets"][0]["sha256"] = _sha256_bytes(
            jpeg_path.read_bytes())
        response = self.fixture.handle(request)
        self.assertEqual(boundary.ERR_POLICY_REFUSED, response["error_code"])
        self.assertIn("MIME", response["detail"])

    def test_media_append_size_cap_refused(self):
        policy = dict(self.fixture.policy)
        policy["operations"] = dict(policy["operations"])
        policy["operations"]["media_append"] = dict(
            policy["operations"]["media_append"])
        policy["operations"]["media_append"]["max_bytes"] = 10
        boundary.atomic_write_json(self.fixture.paths.policy_path, policy)
        response = self.fixture.handle(self._media_request())
        self.assertEqual(boundary.ERR_POLICY_REFUSED, response["error_code"])
        self.assertIn("size cap", response["detail"])

    def test_replay_identical_returns_stored_receipt_without_second_write(self):
        request = self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"})
        first = self.fixture.handle(request)
        second = self.fixture.handle(request)
        self.assertEqual(first["receipt_sha256"], second["receipt_sha256"])
        self.assertEqual(1, len(self.fixture.shopify.write_calls()))
        self.assertEqual(first["outcome"], second["outcome"])

    def test_protected_field_drift_marks_reconciliation(self):
        self.fixture.shopify.mutate_protected_on = {"update_details"}
        response = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"}))
        self.assertEqual(boundary.OUTCOME_RECONCILIATION_REQUIRED,
                         response["outcome"])
        self.assertEqual(boundary.ERR_RECONCILIATION_REQUIRED,
                         response["error_code"])


# ---------------------------------------------------------------------------
# Reconciliation semantics
# ---------------------------------------------------------------------------


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture()
        self.addCleanup(self.fixture.close)

    def _inventory_request(self, *, request_id=None, key="recon-key"):
        return self.fixture.request(
            "set_inventory",
            [{"type": "set_inventory", "quantity": 1, "reason": "received",
              "expected": {"available": 0}}],
            evidence=self.fixture.evidence(idempotency_key=key),
            authorisation={"kind": "standing"},
            target={"product_id": PRODUCT, "variant_id": VARIANT,
                    "inventory_item_id": INVENTORY_ITEM, "location_id": LOCATION},
            request_id=request_id)

    def test_uncertain_outcome_is_reconciliation_required_and_never_replayed(self):
        self.fixture.shopify.fail_uncertain = {"set_inventory"}
        request = self._inventory_request()
        first = self.fixture.handle(request)
        self.assertEqual(boundary.OUTCOME_RECONCILIATION_REQUIRED,
                         first["outcome"])
        self.assertEqual(boundary.ERR_RECONCILIATION_REQUIRED,
                         first["error_code"])
        second = self.fixture.handle(dict(request))
        self.assertEqual(boundary.OUTCOME_RECONCILIATION_REQUIRED,
                         second["outcome"])
        self.assertEqual(first["readback"], second["readback"])
        self.assertEqual(1, len([value for value in self.fixture.shopify.calls
                                 if value[0] == "set_inventory"]))

    def test_verify_settles_not_applied_and_a_new_request_may_apply(self):
        self.fixture.shopify.fail_uncertain = {"set_inventory"}
        first = self.fixture.handle(self._inventory_request(key="recon-key-a"))
        self.assertEqual(boundary.OUTCOME_RECONCILIATION_REQUIRED,
                         first["outcome"])
        verify = self.fixture.handle(self.fixture.request(
            "verify", [], target={"product_id": PRODUCT}))
        self.assertEqual(boundary.OUTCOME_VERIFIED, verify["outcome"])
        states = [row["state"] for row in verify["readback"]["reconciliations"]]
        self.assertEqual([boundary.STATE_RECONCILED_NOT_APPLIED], states)
        self.fixture.shopify.fail_uncertain = set()
        second = self.fixture.handle(self._inventory_request(key="recon-key-b"))
        self.assertEqual(boundary.OUTCOME_APPLIED, second["outcome"],
                         second["detail"])
        self.assertEqual(1, self.fixture.shopify.product["available"])

    def test_verify_settles_applied_after_uncertain_write(self):
        self.fixture.shopify.fail_uncertain_after_apply = {"set_inventory"}
        first = self.fixture.handle(self._inventory_request(key="recon-key-c"))
        self.assertEqual(boundary.OUTCOME_RECONCILIATION_REQUIRED,
                         first["outcome"])
        verify = self.fixture.handle(self.fixture.request(
            "verify", [], target={"product_id": PRODUCT}))
        states = [row["state"] for row in verify["readback"]["reconciliations"]]
        self.assertEqual([boundary.STATE_RECONCILED_APPLIED], states)

    def test_uncertain_media_append_settles_partial_as_unsettled(self):
        self.fixture.shopify.fail_uncertain_after_apply = {"media_append"}
        request = self.fixture.request(
            "media_append", [{"type": "media_append", "assets": [
                {"path": str(self.fixture.batch_root / "hero.png"),
                 "sha256": "", "role": "hero"},
                {"path": str(self.fixture.batch_root / "original.png"),
                 "sha256": "", "role": "original"}]}],
            evidence=self.fixture.evidence(),
            authorisation={"kind": "standing"})
        for role, payload in (("hero", png_bytes(b"h")), ("original", png_bytes(b"o"))):
            path = self.fixture.batch_root / f"{role}.png"
            path.write_bytes(payload)
        for asset in request["operations"][0]["assets"]:
            path = Path(asset["path"])
            asset["sha256"] = _sha256_bytes(path.read_bytes())
        first = self.fixture.handle(request)
        self.assertEqual(boundary.OUTCOME_RECONCILIATION_REQUIRED,
                         first["outcome"])
        # Remove the original media to simulate a partial attachment (hero stays).
        media = self.fixture.shopify.product["media"]
        self.fixture.shopify.product["media"] = media[:1] + media[2:]
        verify = self.fixture.handle(self.fixture.request(
            "verify", [], target={"product_id": PRODUCT}))
        rows = verify["readback"]["reconciliations"]
        self.assertEqual("PARTIAL", rows[0]["state"])

    def test_verify_replay_returns_stored_response(self):
        request = self.fixture.request(
            "verify", [], target={"product_id": PRODUCT})
        first = self.fixture.handle(request)
        second = self.fixture.handle(request)
        self.assertEqual(first["receipt_sha256"], second["receipt_sha256"])
        self.assertEqual(first["outcome"], second["outcome"])

    def test_read_only_operations_reject_authority_objects(self):
        verify_payload = self.fixture.request(
            "verify", [], target={"product_id": PRODUCT})
        verify_payload["authorisation"] = {"kind": "standing"}
        response = self.fixture.handle(verify_payload)
        self.assertEqual(boundary.ERR_BAD_REQUEST, response["error_code"])
        status_payload = self.fixture.request("status", [])
        status_payload["target"] = {"product_id": PRODUCT}
        response = self.fixture.handle(status_payload)
        self.assertEqual(boundary.ERR_BAD_REQUEST, response["error_code"])


# ---------------------------------------------------------------------------
# Receipt signing / admin verify
# ---------------------------------------------------------------------------


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture()
        self.addCleanup(self.fixture.close)

    def _applied_receipt(self):
        response = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"}))
        self.assertEqual(boundary.OUTCOME_APPLIED, response["outcome"],
                         response["detail"])
        return response

    def test_receipt_signature_verifies_and_tampers_fail(self):
        response = self._applied_receipt()
        key = boundary.load_signing_key(self.fixture.paths.signing_key_path)
        receipt = response["receipt"]
        self.assertEqual((True, "ok"), boundary.verify_receipt_object(receipt, key))
        tampered = json.loads(json.dumps(receipt))
        tampered["after"]["title"] = f"{TANK} - EVIL"
        ok, reason = boundary.verify_receipt_object(tampered, key)
        self.assertFalse(ok)
        self.assertEqual("receipt_sha_mismatch", reason)
        signature_tampered = json.loads(json.dumps(receipt))
        signature_tampered["receipt_signature"] = "hmac-sha256:" + "0" * 64
        ok, reason = boundary.verify_receipt_object(signature_tampered, key)
        self.assertFalse(ok)
        self.assertEqual("signature_mismatch", reason)
        wrong_key = boundary.load_signing_key(
            self.fixture.root / "other.key")
        ok, _reason = boundary.verify_receipt_object(receipt, wrong_key)
        self.assertFalse(ok)

    def test_receipt_written_root_owned_mode_and_exclusive(self):
        response = self._applied_receipt()
        path = boundary.receipt_path_for(
            self.fixture.paths, response["receipt"]["request_id"])
        self.assertTrue(path.is_file())
        self.assertEqual(0o600, stat.S_IMODE(os.stat(path).st_mode))
        self.assertEqual(response["receipt"], json.loads(path.read_text()))

    def test_admin_verify_receipt_cli(self):
        response = self._applied_receipt()
        path = boundary.receipt_path_for(
            self.fixture.paths, response["receipt"]["request_id"])
        python = PYTHON39 if os.path.exists(PYTHON39) else sys.executable
        good = subprocess.run(
            [python, str(SCRIPTS / "betta_write_admin.py"),
             "--state-dir", str(self.fixture.state),
             "verify-receipt", "--file", str(path)],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(0, good.returncode, good.stdout + good.stderr)
        payload = json.loads(good.stdout)
        self.assertTrue(payload["ok"])

        tampered = json.loads(path.read_text())
        tampered["after"]["title"] = "EVIL"
        tampered_path = self.fixture.root / "tampered-receipt.json"
        tampered_path.write_text(json.dumps(tampered))
        bad = subprocess.run(
            [python, str(SCRIPTS / "betta_write_admin.py"),
             "--state-dir", str(self.fixture.state),
             "verify-receipt", "--file", str(tampered_path)],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(2, bad.returncode)
        self.assertFalse(json.loads(bad.stdout)["ok"])

    def test_admin_disable_enable_and_status(self):
        python = PYTHON39 if os.path.exists(PYTHON39) else sys.executable
        disable = subprocess.run(
            [python, str(SCRIPTS / "betta_write_admin.py"),
             "--state-dir", str(self.fixture.state), "disable"],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(0, disable.returncode, disable.stderr)
        self.assertTrue(self.fixture.paths.disabled_path.exists())
        refused = self.fixture.handle(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"}))
        self.assertEqual(boundary.ERR_BOUNDARY_DISABLED, refused["error_code"])
        enable = subprocess.run(
            [python, str(SCRIPTS / "betta_write_admin.py"),
             "--state-dir", str(self.fixture.state), "enable"],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(0, enable.returncode, enable.stderr)
        self.assertFalse(self.fixture.paths.disabled_path.exists())
        status = subprocess.run(
            [python, str(SCRIPTS / "betta_write_admin.py"),
             "--state-dir", str(self.fixture.state), "status"],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(0, status.returncode, status.stderr)
        payload = json.loads(status.stdout)
        self.assertTrue(payload["policy_loaded"])
        self.assertFalse(payload["disabled"])


# ---------------------------------------------------------------------------
# Daemon behaviour (in-process + subprocess with fake HTTP Shopify)
# ---------------------------------------------------------------------------


class FakeGraphQLState:
    """Backing state for the fake Shopify HTTP endpoint."""

    def __init__(self):
        self.title = f"{TANK} - old title"
        self.arrival_date = "2026-10-01"
        self.available = 0
        self.requests = []

    def product_payload(self):
        return {
            "data": {"product": {
                "id": PRODUCT,
                "title": self.title,
                "status": "ACTIVE",
                "descriptionHtml": "<p>betta</p>",
                "handle": "betta",
                "vendor": "NTA",
                "productType": "Betta",
                "metafield": {"value": self.arrival_date, "type": "date"},
                "media": {"pageInfo": {"hasNextPage": False}, "nodes": []},
                "variants": {
                    "pageInfo": {"hasNextPage": False},
                    "nodes": [{
                        "id": VARIANT,
                        "price": "35.00",
                        "inventoryQuantity": self.available,
                        "inventoryPolicy": "DENY",
                        "inventoryItem": {
                            "id": INVENTORY_ITEM,
                            "tracked": True,
                            "unitCost": {"amount": "10.00",
                                         "currencyCode": "AUD"},
                            "inventoryLevels": {
                                "pageInfo": {"hasNextPage": False},
                                "nodes": [{
                                    "location": {"id": LOCATION, "name": "NTA"},
                                    "quantities": [
                                        {"name": "available",
                                         "quantity": self.available},
                                        {"name": "on_hand",
                                         "quantity": self.available},
                                        {"name": "committed", "quantity": 0},
                                    ],
                                }],
                            },
                        },
                    }],
                },
            }},
        }


class FakeShopifyHTTP:
    """Tiny HTTP server speaking the pinned GraphQL/auth surface."""

    def __init__(self, state):
        self.state = state
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # keep test output clean
                pass

            def _respond(self, payload, status=200):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                outer.state.requests.append((self.path, raw.decode("utf-8", "replace")))
                if self.path.endswith("/admin/oauth/access_token"):
                    self._respond({"access_token": FAKE_TOKEN,
                                   "expires_in": 3600})
                    return
                if "/graphql" not in self.path:
                    self._respond({"errors": ["not found"]}, status=404)
                    return
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except ValueError:
                    self._respond({"errors": ["bad json"]}, status=400)
                    return
                query = payload.get("query", "")
                variables = payload.get("variables") or {}
                if "query BettaBoundaryProduct" in query:
                    self._respond(outer.state.product_payload())
                    return
                if "mutation BettaBoundaryUpdateDetails" in query:
                    product = variables.get("product") or {}
                    if "title" in product:
                        outer.state.title = product["title"]
                    self._respond({"data": {"productUpdate": {
                        "product": {"id": PRODUCT}, "userErrors": []}}})
                    return
                if "mutation BettaBoundarySetArrivalDate" in query:
                    metafields = variables.get("metafields") or [{}]
                    outer.state.arrival_date = metafields[0].get("value")
                    self._respond({"data": {"metafieldsSet": {
                        "metafields": [{"id": "gid://shopify/Metafield/1"}],
                        "userErrors": []}}})
                    return
                if "mutation BettaBoundarySetInventory" in query:
                    quantities = ((variables.get("input") or {})
                                  .get("quantities") or [{}])
                    outer.state.available = quantities[0].get("quantity")
                    self._respond({"data": {"inventorySetQuantities": {
                        "inventoryAdjustmentGroup": {"createdAt": "now",
                                                     "reason": "received"},
                        "userErrors": []}}})
                    return
                self._respond({"errors": ["unsupported query"]}, status=500)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self):
        return self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def spawn_daemon(socket_path, state_dir, env_extra=None, wait=20.0):
    python = PYTHON39 if os.path.exists(PYTHON39) else sys.executable
    environment = dict(os.environ)
    environment.update(env_extra or {})
    process = subprocess.Popen(
        [python, str(SCRIPTS / "betta_write_daemon.py"),
         "--socket", str(socket_path), "--state-dir", str(state_dir),
         "--code-root", str(SCRIPTS)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env=environment)
    deadline = time.time() + wait
    while time.time() < deadline:
        if process.poll() is not None:
            _out, err = process.communicate()
            raise AssertionError(f"daemon exited early: {err}")
        if socket_path.exists():
            try:
                probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    probe.settimeout(0.5)
                    probe.connect(str(socket_path))
                    return process
                finally:
                    probe.close()
            except OSError:
                pass
        time.sleep(0.05)
    process.terminate()
    raise AssertionError("daemon did not start in time")


class DaemonTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture()
        self.addCleanup(self.fixture.close)
        self.processes = []
        self.addCleanup(self._terminate_processes)

    def _terminate_processes(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()

    # -- in-process daemon plumbing ---------------------------------------

    def test_default_peer_uid_matches_current_euid(self):
        server, client = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        self.addCleanup(client.close)
        self.assertEqual(os.geteuid(), daemon_mod.default_peer_uid(server))

    def test_daemon_rejects_injected_disallowed_uid(self):
        daemon = daemon_mod.WriteDaemon(
            boundary=boundary, socket_path=self.fixture.root / "x.sock",
            state_dir=self.fixture.state, code_root=SCRIPTS,
            uid_provider=lambda conn: 999, log_stream=io.StringIO())
        response = daemon.handle_line(json.dumps(
            self.fixture.update_details_request(
                title=f"{TANK} - new", expected={"title": f"{TANK} - old title"})),
            999)
        self.assertEqual(boundary.ERR_PEER_NOT_ALLOWED, response["error_code"])
        self.assertEqual([], self.fixture.shopify.calls)

    def test_daemon_garbage_line_is_bad_request(self):
        daemon = daemon_mod.WriteDaemon(
            boundary=boundary, socket_path=self.fixture.root / "x.sock",
            state_dir=self.fixture.state, code_root=SCRIPTS,
            log_stream=io.StringIO())
        response = daemon.handle_line(b"definitely not json", 501)
        self.assertEqual(boundary.ERR_BAD_REQUEST, response["error_code"])
        self.assertEqual(boundary.RESPONSE_SCHEMA, response["schema"])

    # -- subprocess + fake HTTP Shopify -----------------------------------

    def test_subprocess_daemon_and_client_roundtrip(self):
        state = FakeGraphQLState()
        fake_http = FakeShopifyHTTP(state)
        self.addCleanup(fake_http.close)
        (self.fixture.paths.shopify_env_path).write_text(
            f"SHOPIFY_STORE_URL=http://127.0.0.1:{fake_http.port}\n"
            f"SHOPIFY_CLIENT_ID=test-client\n"
            f"SHOPIFY_CLIENT_SECRET={FAKE_SECRET}\n"
            "SHOPIFY_API_VERSION=2026-07\n")
        socket_path = self.fixture.root / "boundary.sock"
        process = spawn_daemon(socket_path, self.fixture.state)
        self.processes.append(process)
        client = client_mod.WriteBoundaryClient(str(socket_path), timeout=30.0)

        status = client.status()
        self.assertTrue(status["ok"], status)
        self.assertEqual(boundary.OUTCOME_STATUS, status["outcome"])
        self.assertTrue(status["readback"]["policy_loaded"])
        serialised = json.dumps(status)
        self.assertNotIn(FAKE_SECRET, serialised)
        self.assertNotIn(FAKE_TOKEN, serialised)

        request = self.fixture.update_details_request(
            title=f"{TANK} - client title",
            expected={"title": f"{TANK} - old title"})
        applied = client.request(request)
        self.assertEqual(boundary.OUTCOME_APPLIED, applied["outcome"],
                         applied["detail"])
        self.assertEqual(f"{TANK} - client title", state.title)

        replay = client.request(request)
        self.assertEqual(applied["receipt_sha256"], replay["receipt_sha256"])

        verify = client.verify({"product_id": PRODUCT}, {})
        self.assertEqual(boundary.OUTCOME_VERIFIED, verify["outcome"])
        self.assertEqual(f"{TANK} - client title",
                         verify["readback"]["product"]["title"])

        receipt_path = boundary.receipt_path_for(
            self.fixture.paths, applied["receipt"]["request_id"])
        self.assertTrue(receipt_path.is_file())
        good = subprocess.run(
            [PYTHON39 if os.path.exists(PYTHON39) else sys.executable,
             str(SCRIPTS / "betta_write_admin.py"),
             "--state-dir", str(self.fixture.state),
             "verify-receipt", "--file", str(receipt_path)],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(0, good.returncode, good.stdout + good.stderr)

        process.terminate()
        _out, err = process.communicate(timeout=15)
        self.assertNotIn(FAKE_SECRET, err)
        self.assertNotIn(FAKE_TOKEN, err)

    def test_subprocess_daemon_ignores_hostile_environment(self):
        permissive = self.fixture.root / "hostile-policy.json"
        hostile_policy = boundary.default_policy()
        hostile_policy["operations"]["merch_update"]["standing"] = True
        hostile_policy["allowed_uids"] = [0, 501, 999]
        permissive.write_text(json.dumps(hostile_policy))
        env_extra = {
            "NTA_BETTA_WRITE_POLICY": str(permissive),
            "BOUNDARY_POLICY": str(permissive),
            "BOUNDARY_STATE_DIR": str(self.fixture.root / "elsewhere"),
            "NTA_BETTA_WRITE_ALLOWED_UIDS": "0,501,999",
            "BETTA_WRITE_ENABLED": "true",
            "NTA_BETTA_BATCH_WRITE_ENABLED": "true",
            "SHOPIFY_ACCESS_TOKEN": "hostile-token",
        }
        socket_path = self.fixture.root / "hostile.sock"
        process = spawn_daemon(socket_path, self.fixture.state,
                               env_extra=env_extra)
        self.processes.append(process)
        client = client_mod.WriteBoundaryClient(str(socket_path), timeout=30.0)
        status = client.status()
        self.assertEqual([501], status["readback"]["allowed_uids"])
        self.assertFalse(
            status["readback"]["operations"]["merch_update"]["standing"])
        response = client.request(self.fixture.request(
            "merch_update",
            [{"type": "merch_update", "vendor": "EVIL",
              "expected": {"vendor": "NTA"}}],
            evidence=self.fixture.evidence(),
            authorisation={"kind": "standing"},
            target={"product_id": PRODUCT, "variant_id": VARIANT,
                    "inventory_item_id": INVENTORY_ITEM}))
        self.assertEqual(boundary.ERR_AUTHORISATION_INVALID,
                         response["error_code"])

    def test_subprocess_daemon_disabled_flag_fails_closed(self):
        socket_path = self.fixture.root / "disabled.sock"
        self.fixture.paths.disabled_path.write_text("disabled")
        process = spawn_daemon(socket_path, self.fixture.state)
        self.processes.append(process)
        client = client_mod.WriteBoundaryClient(str(socket_path), timeout=30.0)
        response = client.request(self.fixture.update_details_request(
            title=f"{TANK} - new", expected={"title": f"{TANK} - old title"}))
        self.assertEqual(boundary.ERR_BOUNDARY_DISABLED, response["error_code"])
        status = client.status()
        self.assertEqual(boundary.ERR_BOUNDARY_DISABLED, status["error_code"])


# ---------------------------------------------------------------------------
# Client API + structural checks
# ---------------------------------------------------------------------------


class ClientAndStructureTests(unittest.TestCase):
    def test_build_request_shape_and_uuid(self):
        client = client_mod.WriteBoundaryClient("/nonexistent.sock")
        payload = client.build_request(
            operation="update_details", mode="apply",
            target={"product_id": PRODUCT}, evidence={"a": 1},
            operations=[{"type": "update_details"}],
            authorisation={"kind": "standing"})
        self.assertEqual(boundary.REQUEST_SCHEMA, payload["schema"])
        self.assertEqual(4, uuid.UUID(payload["request_id"]).version)
        explicit = client.build_request(
            operation="status", mode="apply", target={}, evidence=None,
            operations=[], authorisation=None, request_id=str(uuid.uuid4()))
        self.assertNotIn("authorisation", explicit)
        self.assertNotIn("evidence", explicit)

    def test_client_transport_failure_raises(self):
        client = client_mod.WriteBoundaryClient("/nonexistent/nowhere.sock")
        with self.assertRaises(client_mod.WriteBoundaryClientError):
            client.request({"schema": boundary.REQUEST_SCHEMA})

    def test_py39_compilation_of_boundary_files(self):
        if not os.path.exists(PYTHON39):
            self.skipTest("/usr/bin/python3 is unavailable")
        files = [
            "betta_write_boundary.py", "betta_write_daemon.py",
            "betta_write_client.py", "betta_write_admin.py",
        ]
        result = subprocess.run(
            [PYTHON39, "-m", "py_compile"] + [str(SCRIPTS / name) for name in files],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_boundary_modules_are_stdlib_only(self):
        allowed_prefixes = (
            "__future__", "argparse", "ctypes", "datetime", "decimal", "grp",
            "hashlib", "hmac", "http", "importlib", "json", "os", "pathlib",
            "re", "signal", "socket", "stat", "struct", "sys", "tempfile",
            "time", "types", "typing", "urllib", "uuid", "unittest",
            "betta_write", "betta_corrections",
        )
        for name in ("betta_write_boundary.py", "betta_write_daemon.py",
                     "betta_write_client.py", "betta_write_admin.py"):
            for line_number, line in enumerate(
                    (SCRIPTS / name).read_text().splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("import "):
                    module = stripped.split()[1].split(".")[0]
                elif stripped.startswith("from "):
                    module = stripped.split()[1].split(".")[0]
                else:
                    continue
                self.assertTrue(
                    module.startswith(allowed_prefixes),
                    f"{name}:{line_number} imports non-stdlib module {module}")


if __name__ == "__main__":
    unittest.main()
