"""Offline safety tests for automatic standing BAU authorisation."""

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


policy_mod = load_module("betta_policy_bau_test", ROOT / "scripts" / "betta_policy.py")
uploader_tests = load_module(
    "betta_policy_uploader_fixture", ROOT / "tests" / "test_betta_shopify_batch.py",
)


class AutomaticBAUPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.receipt_path = self.root / "authority" / "receipt.json"

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, *, count=1, authorised=True):
        return uploader_tests.Fixture(self.root / "batch", count=count, authorised=authorised)

    def policy(self, **changes):
        data = policy_mod.default_policy()
        data.update({"enabled": True, "automatic_batch_authorisation": True})
        data.update(changes)
        return policy_mod.StandingPolicy(data)

    @staticmethod
    def manifest_digest(fixture):
        return hashlib.sha256(fixture.manifest_path.read_bytes()).hexdigest()

    def test_defaults_fail_closed_and_require_explicit_automatic_flag(self):
        fixture = self.fixture()
        defaults = policy_mod.default_policy()
        self.assertFalse(defaults["enabled"])
        self.assertFalse(defaults["automatic_batch_authorisation"])
        with self.assertRaisesRegex(policy_mod.PolicyError, "disabled"):
            policy_mod.StandingPolicy(defaults).authorise_manifest(
                fixture.manifest_path, self.receipt_path,
            )
        defaults["enabled"] = True
        with self.assertRaisesRegex(policy_mod.PolicyError, "automatic batch"):
            policy_mod.StandingPolicy(defaults).authorise_manifest(
                fixture.manifest_path, self.receipt_path,
            )

    def test_valid_real_uploader_manifest_gets_exact_idempotent_receipt(self):
        fixture = self.fixture(count=2)
        digest = self.manifest_digest(fixture)
        policy = self.policy()
        first = policy.authorise_manifest(
            fixture.manifest_path, self.receipt_path, expected_sha256=digest,
        )
        original_receipt_bytes = self.receipt_path.read_bytes()
        second = policy.authorize_manifest(
            fixture.manifest_path, self.receipt_path, expected_sha256=digest,
        )
        self.assertEqual(first, second)
        self.assertEqual(original_receipt_bytes, self.receipt_path.read_bytes())
        self.assertEqual(digest, first["manifest_sha256"])
        self.assertEqual(2, first["item_count"])
        self.assertEqual("automatic-standing-bau", first["authorisation_mode"])
        self.assertFalse(first["scope"]["allow_product_create"])
        self.assertFalse(first["scope"]["qa_exceptions_allowed"])
        self.assertEqual(0o444, os.stat(self.receipt_path).st_mode & 0o777)

    def test_expected_digest_and_actual_persisted_bytes_must_match(self):
        fixture = self.fixture()
        with self.assertRaisesRegex(policy_mod.PolicyError, "expected manifest SHA-256"):
            self.policy().authorise_manifest(
                fixture.manifest_path, self.receipt_path, expected_sha256="0" * 64,
            )
        self.assertFalse(self.receipt_path.exists())

    def test_changed_manifest_cannot_reuse_receipt(self):
        fixture = self.fixture()
        policy = self.policy()
        policy.authorise_manifest(fixture.manifest_path, self.receipt_path)
        fixture.manifest_path.write_bytes(fixture.manifest_path.read_bytes() + b" \n")
        with self.assertRaisesRegex(policy_mod.PolicyError, "receipt differs"):
            policy.authorise_manifest(fixture.manifest_path, self.receipt_path)

    def test_changed_receipt_is_rejected(self):
        fixture = self.fixture()
        policy = self.policy()
        policy.authorise_manifest(fixture.manifest_path, self.receipt_path)
        os.chmod(self.receipt_path, 0o600)
        self.receipt_path.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(policy_mod.PolicyError, "receipt differs"):
            policy.authorise_manifest(fixture.manifest_path, self.receipt_path)

    def test_symlink_cannot_stand_in_for_immutable_receipt(self):
        fixture = self.fixture()
        policy = self.policy()
        real_receipt = self.root / "real-receipt.json"
        policy.authorise_manifest(fixture.manifest_path, real_receipt)
        self.receipt_path.parent.mkdir(parents=True)
        self.receipt_path.symlink_to(real_receipt)
        with self.assertRaisesRegex(policy_mod.PolicyError, "regular file"):
            policy.authorise_manifest(fixture.manifest_path, self.receipt_path)

    def test_real_uploader_authority_and_hash_evidence_are_required(self):
        fixture = self.fixture(authorised=False)
        with self.assertRaisesRegex(policy_mod.PolicyError, "write authority is false"):
            self.policy().authorise_manifest(fixture.manifest_path, self.receipt_path)

        fixture = uploader_tests.Fixture(
            self.root / "tampered", count=1, authorised=True,
        )
        Path(fixture.manifest_items[0]["hero"]["path"]).write_bytes(b"changed")
        with self.assertRaisesRegex(policy_mod.PolicyError, "hash mismatch"):
            self.policy().authorise_manifest(fixture.manifest_path, self.receipt_path)

    def test_uploader_accepted_qa_exception_is_forbidden_for_automatic_bau(self):
        fixture = self.fixture()
        tank = fixture.tanks[0]
        qa_path = fixture.qa_paths[tank]
        qa = json.loads(qa_path.read_text(encoding="utf-8"))
        qa["output"]["overall"] = "FAIL"
        qa["output"]["assertions"]["same_identity"] = "FAIL"
        qa["output"]["reasons"] = ["identity mismatch"]
        qa_hash = uploader_tests.write_json(qa_path, qa)
        fixture.manifest_items[0]["image_qa"]["sha256"] = qa_hash
        fixture.manifest_items[0]["image_qa"]["exception"] = {
            "accepted": True,
            "accepted_by": "owner",
            "source_reference": "owner-exception",
            "qa_receipt_sha256": qa_hash,
            "failed_assertions": ["same_identity"],
            "original_reasons": ["identity mismatch"],
        }
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(policy_mod.PolicyError, "QA PASS without exception"):
            self.policy().authorise_manifest(fixture.manifest_path, self.receipt_path)

    def test_inventory_must_be_exactly_tracked_deny_zero_to_one(self):
        fixture = self.fixture()
        fixture.approval_items[0]["existing_inventory"] = 1
        quantities = fixture.snapshot_records[0]["product"]["variants"]["nodes"][0][
            "inventoryItem"
        ]["inventoryLevels"]["nodes"][0]["quantities"]
        next(value for value in quantities if value["name"] == "available")["quantity"] = 1
        fixture._write_manifest()
        with self.assertRaisesRegex(policy_mod.PolicyError, "inventory 0-to-1 only"):
            self.policy().authorise_manifest(fixture.manifest_path, self.receipt_path)

    def test_batch_larger_than_twenty_is_rejected(self):
        fixture = self.fixture(count=21)
        with self.assertRaisesRegex(policy_mod.PolicyError, "fish-per-batch"):
            self.policy().authorise_manifest(fixture.manifest_path, self.receipt_path)

    def test_policy_config_cannot_relax_scope_or_hard_caps(self):
        unsafe = []
        data = policy_mod.default_policy()
        data["allow_product_create"] = True
        unsafe.append(data)
        data = policy_mod.default_policy()
        data["protected_fields"].remove("retail_price")
        unsafe.append(data)
        data = policy_mod.default_policy()
        data["inventory"]["allowed_from"] = [0, 1]
        unsafe.append(data)
        data = policy_mod.default_policy()
        data["inventory"]["target"] = True
        unsafe.append(data)
        data = policy_mod.default_policy()
        data["generation_budget"]["per_fish_usd"] = 0.15
        unsafe.append(data)
        data = policy_mod.default_policy()
        data["generation_budget"]["max_attempts_per_fish"] = 3
        unsafe.append(data)
        data = policy_mod.default_policy()
        data["generation_budget"]["fallback_cost_usd"] = float("nan")
        unsafe.append(data)
        for candidate in unsafe:
            with self.subTest(candidate=candidate):
                with self.assertRaises(policy_mod.PolicyError):
                    policy_mod.StandingPolicy(candidate)

    def test_mutated_policy_cannot_return_relaxed_budget(self):
        policy = self.policy()
        policy.data["generation_budget"]["per_batch_usd"] = 99.0
        with self.assertRaisesRegex(policy_mod.PolicyError, "hard cap"):
            policy.generation_budget()

    def test_legacy_manual_digest_grants_remain_supported(self):
        digest = "d" * 64
        data = policy_mod.default_policy()
        data["enabled"] = True
        data["authorisations"] = [{
            "manifest_sha256": digest,
            "receipt": "owner-grant",
            "at": "2026-10-11T00:00:00+11:00",
        }]
        policy = policy_mod.StandingPolicy(data)
        self.assertEqual("owner-grant", policy.authorise(digest)["receipt"])
        self.assertIsNone(policy.authorise("e" * 64))


if __name__ == "__main__":
    unittest.main()
