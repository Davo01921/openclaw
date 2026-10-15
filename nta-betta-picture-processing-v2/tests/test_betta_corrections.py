"""Scoped tests for the A3 mutation firewall.

Covers two mechanisms:

- ``scripts/betta_corrections.py`` — immutable owner-correction records that
  bind source SHA, corrected/requested/accepted tank, product and operation
  scope, refused on tamper/reuse.
- ``scripts/betta_bridge_integrity.py`` — canonical-bridge path + hash pinning
  that flags workspace copies and drifted bytes.

NOTE (file ownership): the bridge-integrity tests live in this module because
the A3 file-ownership enumeration lists this module as the only owned *new*
test file; both mechanisms are A3 firewall deliverables.
"""

import contextlib
import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


corrections = _load("betta_corrections_tests", SCRIPTS / "betta_corrections.py")
bridge = _load("betta_bridge_integrity_tests", SCRIPTS / "betta_bridge_integrity.py")

SOURCE_SHA = "a" * 64
PRODUCT = "gid://shopify/Product/7255867588817"
VARIANT = "gid://shopify/ProductVariant/41571765453009"
BETTA_FIELDS = ["title", "arrival_date", "inventory", "media"]


def record_kwargs(**overrides):
    values = {
        "source_sha256": SOURCE_SHA,
        "original_model_tank": "5BT43",
        "corrected_tank": "2BT23",
        "product_id": PRODUCT,
        "variant_id": VARIANT,
        "operation": {"fields": list(BETTA_FIELDS), "mode": "owner-directed"},
        "reason": "owner confirmed the card reads 2BT23",
        "evidence_reference": "discord:message:1558414753716510721",
        "operator": "owner",
        "created_at": "2026-10-15T09:00:00+11:00",
    }
    values.update(overrides)
    return values


def validate(record_ref, **overrides):
    values = {
        "source_sha256": SOURCE_SHA,
        "requested_tank": "2BT23",
        "accepted_tank": "2BT23",
        "product_id": PRODUCT,
        "operation_fields": list(BETTA_FIELDS),
    }
    values.update(overrides)
    return corrections.validate_correction(record_ref, **values)


class CorrectionRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_happy_path_record_and_validate(self):
        path = corrections.record(**record_kwargs(), directory=self.root)
        self.assertTrue(path.is_file())
        self.assertTrue(path.name.startswith("correction-"))
        data = json.loads(path.read_text())
        self.assertEqual(corrections.SCHEMA, data["schema"])
        self.assertEqual(path.stem.split("correction-", 1)[1], data["correction_sha256"])
        self.assertEqual({"valid": True, "reason": "ok"}, validate(path))
        core = {key: value for key, value in data.items() if key != "correction_sha256"}
        self.assertEqual(data["correction_sha256"], corrections.json_sha256(core))

    def test_record_file_is_read_only(self):
        path = corrections.record(**record_kwargs(), directory=self.root)
        self.assertEqual(0o444, stat.S_IMODE(os.stat(path).st_mode))

    def test_validate_accepts_dict_input(self):
        path = corrections.record(**record_kwargs(), directory=self.root)
        data = json.loads(path.read_text())
        self.assertEqual({"valid": True, "reason": "ok"}, validate(data))

    def test_subset_of_recorded_scope_is_valid(self):
        path = corrections.record(**record_kwargs(), directory=self.root)
        verdict = validate(path, operation_fields=["title"])
        self.assertTrue(verdict["valid"])

    def test_operation_list_shorthand_is_normalised(self):
        path = corrections.record(
            **record_kwargs(operation=["media", "inventory", "media"]), directory=self.root)
        data = json.loads(path.read_text())
        self.assertEqual(["inventory", "media"], data["operation"]["fields"])
        self.assertEqual("owner-directed", data["operation"]["mode"])

    def test_tampered_record_dict_fails_self_hash(self):
        path = corrections.record(**record_kwargs(), directory=self.root)
        data = json.loads(path.read_text())
        data["corrected_tank"] = "9BT9"
        self.assertEqual(
            {"valid": False, "reason": "self_hash_mismatch"}, validate(data))

    def test_tampered_record_bytes_fail_self_hash(self):
        path = corrections.record(**record_kwargs(), directory=self.root)
        tampered = self.root / "tampered.json"
        tampered.write_bytes(
            path.read_bytes().replace(b"card reads 2BT23", b"card reads 9BT9"))
        self.assertEqual(
            {"valid": False, "reason": "self_hash_mismatch"}, validate(tampered))

    def test_reuse_for_another_source_fails(self):
        path = corrections.record(**record_kwargs(), directory=self.root)
        self.assertEqual(
            {"valid": False, "reason": "source_sha256_mismatch"},
            validate(path, source_sha256="b" * 64))

    def test_reuse_for_another_product_fails(self):
        path = corrections.record(**record_kwargs(), directory=self.root)
        self.assertEqual(
            {"valid": False, "reason": "product_id_mismatch"},
            validate(path, product_id="gid://shopify/Product/1"))

    def test_reuse_for_operation_outside_scope_fails(self):
        path = corrections.record(
            **record_kwargs(operation={"fields": ["retail", "cost", "vendor"]}),
            directory=self.root)
        self.assertEqual(
            {"valid": False, "reason": "operation_scope_mismatch"},
            validate(path, operation_fields=["retail", "cost", "vendor", "title"]))

    def test_corrected_tank_must_equal_accepted_tank(self):
        path = corrections.record(**record_kwargs(), directory=self.root)
        self.assertEqual(
            {"valid": False, "reason": "corrected_tank_mismatch"},
            validate(path, accepted_tank="5BT43"))

    def test_requested_tank_must_equal_recorded_target(self):
        path = corrections.record(**record_kwargs(), directory=self.root)
        self.assertEqual(
            {"valid": False, "reason": "requested_tank_mismatch"},
            validate(path, requested_tank="5BT43"))

    def test_duplicate_record_creation_refuses_overwrite(self):
        path = corrections.record(**record_kwargs(), directory=self.root)
        original = path.read_bytes()
        with self.assertRaisesRegex(corrections.CorrectionError, "already exists"):
            corrections.record(**record_kwargs(), directory=self.root)
        self.assertEqual(original, path.read_bytes())

    def test_record_refuses_malformed_inputs(self):
        cases = {
            "source_sha256": record_kwargs(source_sha256="xyz"),
            "original_model_tank": record_kwargs(original_model_tank="not a tank"),
            "corrected_tank": record_kwargs(corrected_tank="5bt43"),
            "product_id": record_kwargs(product_id="??"),
            "reason": record_kwargs(reason=" "),
            "evidence_reference": record_kwargs(evidence_reference=""),
            "operator": record_kwargs(operator=""),
            "created_at": record_kwargs(created_at="yesterday"),
            "operation": record_kwargs(operation={"fields": []}),
        }
        for label, values in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(corrections.CorrectionError):
                    corrections.record(**values, directory=self.root)

    def test_validate_schema_failures(self):
        path = corrections.record(**record_kwargs(), directory=self.root)
        data = json.loads(path.read_text())
        with self.subTest("missing self hash"):
            broken = {key: value for key, value in data.items()
                      if key != "correction_sha256"}
            self.assertEqual(
                {"valid": False, "reason": "schema_fields_mismatch"},
                validate(broken))
        with self.subTest("bad schema"):
            broken = dict(data, schema="nta-other-schema-v1")
            self.assertEqual(
                {"valid": False, "reason": "schema_mismatch"}, validate(broken))
        with self.subTest("extra field"):
            broken = dict(data, extra="nope")
            self.assertEqual(
                {"valid": False, "reason": "schema_fields_mismatch"}, validate(broken))
        with self.subTest("bad operation"):
            broken = json.loads(json.dumps(data))
            broken["operation"] = {"fields": ["UPPER"], "mode": "x"}
            broken_core = {key: value for key, value in broken.items()
                           if key != "correction_sha256"}
            broken["correction_sha256"] = corrections.json_sha256(broken_core)
            self.assertEqual(
                {"valid": False, "reason": "invalid_operation_scope"}, validate(broken))

    def test_validate_unavailable_and_malformed_files(self):
        missing = self.root / ("correction-" + "e" * 64 + ".json")
        self.assertEqual(
            {"valid": False, "reason": "record_unavailable"}, validate(missing))
        garbage = self.root / "garbage.json"
        garbage.write_text("{not json")
        self.assertEqual(
            {"valid": False, "reason": "record_invalid_json"}, validate(garbage))
        self.assertEqual(
            {"valid": False, "reason": "record_not_object"}, validate(12345))

    def test_validate_rejects_invalid_requested_operation_fields(self):
        path = corrections.record(**record_kwargs(), directory=self.root)
        self.assertEqual(
            {"valid": False, "reason": "invalid_requested_operation_fields"},
            validate(path, operation_fields="title"))

    def test_variant_match_accepted_and_mismatch_refused(self):
        path = corrections.record(**record_kwargs(), directory=self.root)
        self.assertEqual(
            {"valid": True, "reason": "ok"}, validate(path, variant_id=VARIANT))
        self.assertEqual(
            {"valid": False, "reason": "variant_id_mismatch"},
            validate(path, variant_id="gid://shopify/ProductVariant/1"))
        # A record without a variant cannot satisfy a caller that binds one.
        bare = corrections.record(
            **record_kwargs(variant_id=None), directory=self.root)
        self.assertEqual(
            {"valid": False, "reason": "variant_id_mismatch"},
            validate(bare, variant_id=VARIANT))
        # Omitting the caller-side variant keeps the previous behaviour.
        self.assertEqual(
            {"valid": True, "reason": "ok"},
            corrections.validate_correction(
                bare, source_sha256=SOURCE_SHA, requested_tank="2BT23",
                accepted_tank="2BT23", product_id=PRODUCT,
                operation_fields=list(BETTA_FIELDS)))

    def test_no_op_correction_refused_at_record_and_validate(self):
        with self.assertRaisesRegex(corrections.CorrectionError, "must differ"):
            corrections.record(
                **record_kwargs(original_model_tank="2BT23"),
                directory=self.root)
        path = corrections.record(**record_kwargs(), directory=self.root)
        data = json.loads(path.read_text())
        data["original_model_tank"] = data["corrected_tank"]
        core = {key: value for key, value in data.items()
                if key != "correction_sha256"}
        data["correction_sha256"] = corrections.json_sha256(core)
        self.assertEqual(
            {"valid": False, "reason": "no_op_correction"}, validate(data))

    def test_cli_record_refuses_no_op_correction(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = corrections.main([
                "record", "--source-sha256", SOURCE_SHA,
                "--original-model-tank", "2BT23", "--corrected-tank", "2BT23",
                "--product-id", PRODUCT, "--operation-fields", "media",
                "--reason", "r", "--evidence-reference", "e", "--operator", "owner",
                "--directory", str(self.root),
                "--created-at", "2026-10-15T09:00:00+11:00",
            ])
        self.assertEqual(2, code)
        self.assertFalse(json.loads(stdout.getvalue())["ok"])

    def test_cli_validate_variant_binding(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            corrections.main([
                "record", "--source-sha256", SOURCE_SHA,
                "--original-model-tank", "5BT43", "--corrected-tank", "2BT23",
                "--product-id", PRODUCT, "--variant-id", VARIANT,
                "--operation-fields", ",".join(BETTA_FIELDS),
                "--reason", "r", "--evidence-reference", "e", "--operator", "owner",
                "--directory", str(self.root),
                "--created-at", "2026-10-15T09:00:00+11:00",
            ])
        record_path = json.loads(stdout.getvalue())["path"]
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = corrections.main([
                "validate", "--record", record_path,
                "--source-sha256", SOURCE_SHA,
                "--requested-tank", "2BT23", "--accepted-tank", "2BT23",
                "--product-id", PRODUCT, "--variant-id", VARIANT,
                "--operation-fields", ",".join(BETTA_FIELDS),
            ])
        self.assertEqual(0, code)
        self.assertEqual({"valid": True, "reason": "ok"}, json.loads(stdout.getvalue()))
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = corrections.main([
                "validate", "--record", record_path,
                "--source-sha256", SOURCE_SHA,
                "--requested-tank", "2BT23", "--accepted-tank", "2BT23",
                "--product-id", PRODUCT,
                "--variant-id", "gid://shopify/ProductVariant/1",
                "--operation-fields", ",".join(BETTA_FIELDS),
            ])
        self.assertEqual(2, code)
        self.assertEqual(
            {"valid": False, "reason": "variant_id_mismatch"},
            json.loads(stdout.getvalue()))

    def test_cli_record_and_validate_round_trip(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = corrections.main([
                "record",
                "--source-sha256", SOURCE_SHA,
                "--original-model-tank", "5BT43",
                "--corrected-tank", "2BT23",
                "--product-id", PRODUCT,
                "--variant-id", VARIANT,
                "--operation-fields", ",".join(BETTA_FIELDS),
                "--reason", "owner confirmed",
                "--evidence-reference", "discord:message:1",
                "--operator", "owner",
                "--directory", str(self.root),
                "--created-at", "2026-10-15T09:00:00+11:00",
            ])
        self.assertEqual(0, code)
        created = json.loads(stdout.getvalue())
        self.assertTrue(created["ok"])
        record_path = Path(created["path"])
        self.assertTrue(record_path.is_file())

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = corrections.main([
                "validate",
                "--record", str(record_path),
                "--source-sha256", SOURCE_SHA,
                "--requested-tank", "2BT23",
                "--accepted-tank", "2BT23",
                "--product-id", PRODUCT,
                "--operation-fields", ",".join(BETTA_FIELDS),
            ])
        self.assertEqual(0, code)
        self.assertEqual({"valid": True, "reason": "ok"}, json.loads(stdout.getvalue()))

    def test_cli_validate_failure_and_duplicate_record_exit_nonzero(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            corrections.main([
                "record", "--source-sha256", SOURCE_SHA,
                "--original-model-tank", "5BT43", "--corrected-tank", "2BT23",
                "--product-id", PRODUCT, "--operation-fields", "media",
                "--reason", "r", "--evidence-reference", "e", "--operator", "owner",
                "--directory", str(self.root),
                "--created-at", "2026-10-15T09:00:00+11:00",
            ])
        created = json.loads(stdout.getvalue())
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = corrections.main([
                "validate", "--record", created["path"],
                "--source-sha256", "b" * 64,
                "--requested-tank", "2BT23", "--accepted-tank", "2BT23",
                "--product-id", PRODUCT, "--operation-fields", "media",
            ])
        self.assertEqual(2, code)
        self.assertFalse(json.loads(stdout.getvalue())["valid"])

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = corrections.main([
                "record", "--source-sha256", SOURCE_SHA,
                "--original-model-tank", "5BT43", "--corrected-tank", "2BT23",
                "--product-id", PRODUCT, "--operation-fields", "media",
                "--reason", "r", "--evidence-reference", "e", "--operator", "owner",
                "--directory", str(self.root),
                "--created-at", "2026-10-15T09:00:00+11:00",
            ])
        self.assertEqual(2, code)
        self.assertFalse(json.loads(stdout.getvalue())["ok"])


class BridgeIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make_bridge(self, name, payload):
        path = self.root / name
        path.write_bytes(payload)
        return path

    def write_index(self, canonical_path, digest, *, schema=bridge.SCHEMA):
        index = {
            "schema": schema,
            "entries": [{
                "name": "test-canonical",
                "role": "canonical",
                "path": str(canonical_path),
                "sha256": digest,
            }],
        }
        path = self.root / f"index-{len(list(self.root.glob('index*.json')))}.json"
        path.write_text(json.dumps(index))
        return path

    def test_verified_when_path_and_hash_match(self):
        canonical = self.make_bridge("canonical.mjs", b"bridge\n")
        index = self.write_index(canonical, bridge.sha256_file(canonical))
        result = bridge.check_bridge(canonical, index_path=index)
        self.assertEqual(True, result["ok"])
        self.assertEqual("verified", result["reason"])
        self.assertEqual(result["expected_sha256"], result["actual_sha256"])

    def test_identical_workspace_copy_is_still_not_canonical(self):
        canonical = self.make_bridge("canonical.mjs", b"bridge\n")
        copy = self.make_bridge("copy.mjs", canonical.read_bytes())
        index = self.write_index(canonical, bridge.sha256_file(canonical))
        result = bridge.check_bridge(copy, index_path=index)
        self.assertFalse(result["ok"])
        self.assertEqual("bridge_not_canonical", result["reason"])
        self.assertEqual(result["expected_sha256"], result["actual_sha256"])

    def test_drifted_bytes_flagged(self):
        canonical = self.make_bridge("canonical.mjs", b"bridge\n")
        index = self.write_index(canonical, bridge.sha256_file(canonical))
        canonical.write_bytes(b"bridge\nwidened allowlist\n")
        result = bridge.check_bridge(canonical, index_path=index)
        self.assertFalse(result["ok"])
        self.assertEqual("bridge_hash_mismatch", result["reason"])
        self.assertNotEqual(result["expected_sha256"], result["actual_sha256"])

    def test_missing_bridge_flagged(self):
        canonical = self.make_bridge("canonical.mjs", b"bridge\n")
        index = self.write_index(canonical, bridge.sha256_file(canonical))
        canonical.unlink()
        result = bridge.check_bridge(canonical, index_path=index)
        self.assertFalse(result["ok"])
        self.assertEqual("bridge_missing", result["reason"])
        self.assertIsNone(result["actual_sha256"])

    def test_index_problems_fail_closed(self):
        canonical = self.make_bridge("canonical.mjs", b"bridge\n")
        missing = self.root / "absent-index.json"
        result = bridge.check_bridge(canonical, index_path=missing)
        self.assertFalse(result["ok"])
        self.assertEqual("integrity_index_missing", result["reason"])
        invalid = self.root / "invalid.json"
        invalid.write_text("{\"schema\": \"wrong\"}")
        result = bridge.check_bridge(canonical, index_path=invalid)
        self.assertFalse(result["ok"])
        self.assertEqual("integrity_index_invalid", result["reason"])

    def test_cli_check_output_and_exit_codes(self):
        canonical = self.make_bridge("canonical.mjs", b"bridge\n")
        index = self.write_index(canonical, bridge.sha256_file(canonical))
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = bridge.main(
                ["check", "--bridge", str(canonical), "--index", str(index)])
        self.assertEqual(0, code)
        result = json.loads(stdout.getvalue())
        self.assertEqual(
            {"actual_sha256", "expected_sha256", "ok", "reason"}, set(result))

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = bridge.main(
                ["check", "--bridge", str(self.root / "copy.mjs"),
                 "--index", str(index)])
        self.assertEqual(2, code)
        self.assertFalse(json.loads(stdout.getvalue())["ok"])

    def test_shipped_index_is_well_formed(self):
        index = bridge.load_index(bridge.DEFAULT_INDEX)
        entry = bridge.canonical_entry(index)
        self.assertEqual(
            "/Users/davidlo/.openclaw/workspace/nta-fred-shopify-auth/"
            "nta-betta-picture-processor/scripts/shopify-session-bridge.mjs",
            entry["path"])
        self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$")

    def test_shipped_canonical_bridge_matches_its_pin(self):
        index = bridge.load_index(bridge.DEFAULT_INDEX)
        entry = bridge.canonical_entry(index)
        if not Path(entry["path"]).is_file():
            self.skipTest("canonical bridge not present on this machine")
        result = bridge.check_bridge(entry["path"])
        self.assertEqual(True, result["ok"], result)
        self.assertEqual("verified", result["reason"])


if __name__ == "__main__":
    unittest.main()
