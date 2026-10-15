"""A6 adversarial security tests — P1 incident firewall (independent review).

Independent, adversarial attack suite written by the security reviewer (Agent
6) against the incident repair on branch ``codex/betta-identity-incident-20261015``.
Every test here encodes an attack the repaired system must survive, or — where
the attack legitimately cannot be stopped at this layer — documents the
boundary honestly in its name, docstring and assertions
(``trust_boundary_*`` / ``documentation_*`` tests).

Attack groups (mirroring the review mandate):

* ``UploaderIdentityGateAttacks`` — the central attack: cause an update of
  5BT43 while the owner requested 2BT23 (identity-lie variants, correction
  record reuse/tampering/scope, CLI commands, policy ``authorise_manifest``).
* ``DualReadFalseConfidence`` — confident hallucination vs confident read,
  below-gate values, and the gate-aware retry refinement.
* ``SourceBindingAttacks`` — drifted photos/evidence/crops must be refused.
* ``CrossProductContamination`` — two concurrent sandboxes sharing one
  registry must never cross-link receipts, manifests or identities.
* ``ProtectedFieldAndIdempotencyAttacks`` — baseline drift, duplicate
  mutations, price/cost/vendor protection under the new identity gate.
* ``MisreportingCrossCheck`` — audit claims vs the archived incident receipts.
* ``OwnerOverrideScoping`` — correction reuse, repeat recording, scope
  interchangeability.
* ``TrustBoundaryDocumentation`` — what the gate provably cannot know.

The suite is hermetic: no network, no Shopify, no real writes. Mocked vision
is keyed by input hash (A5's sandbox), so every mocked reading binds the bytes
it claims to. Genuine incident fixtures (README shas) are re-verified.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import io
import json
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
FIXTURES = TESTS_DIR / "fixtures" / "incident_2bt23"
INCIDENT_PHOTO = FIXTURES / "incident-photo.png"
INCIDENT_PHOTO_SECOND = FIXTURES / "incident-photo-second-upload.png"
NEAR_CONFUSION_PHOTO = FIXTURES / "near-confusion-5bt43-original.png"
EVIDENCE_DIR = FIXTURES / "evidence"
AUDIT_DOC = TESTS_DIR.parent / "docs" / "incident" / "SHOPIFY_AUDIT_2026-10-15.md"
INCIDENT_SHA = "6e4a4f573f8cfc829218f798eeb5b45cd08803689d31d7db6fce4920cdca9ca9"
NEAR_CONFUSION_SHA = "6c1d0e92004f5170c23797e7da5aabb11d72daade97f418308fc679fd6a15ecc"

for _path in (TESTS_DIR, SCRIPTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import betta_policy  # noqa: E402

incident_mod = importlib.import_module("test_betta_incident_2bt23")
shopify_mod = importlib.import_module("test_betta_shopify_batch")

bsb = shopify_mod.bsb
corrections = shopify_mod.corrections
ShopifyFixture = shopify_mod.Fixture
FakeGateway = shopify_mod.FakeGateway
StrictSandbox = incident_mod.StrictSandbox
catalogue_output = incident_mod.catalogue_output
label_output = incident_mod.label_output
preflight_output = incident_mod.preflight_output
prepqa_output = incident_mod.prepqa_output
sha256 = incident_mod.sha256


# --------------------------------------------------------------------------- #
# Shared fixtures
# --------------------------------------------------------------------------- #
class IncidentSite:
    """A two-item uploader manifest renamed to the incident tank IDs.

    Item ``2BT23`` is the owner-requested fish; item ``5BT43`` is the wrong
    product target Fred mutated. Photographs are bound to an item together
    with every hash-bound evidence sidecar (approval plan, labels, new-fish
    authority, QA input hashes, identity block), so attacks can be expressed
    with the genuine incident bytes.
    """

    EVIDENCE_SHAPES = {
        "approval_plan": ("items", "approval_items"),
        "protected_snapshot": ("records", "snapshot_records"),
        "shopify_details": ("items", "detail_items"),
        "labels": ("items", "label_items"),
        "new_fish_authority": ("items", "authority_items"),
    }

    def __init__(self, root, tanks=("2BT23", "5BT43"), authorised=False):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.fixture = ShopifyFixture(self.root, count=2, authorised=authorised)
        for old, new in zip(("1BT1", "1BT2"), tanks):
            self._rename(old, new)
        self.flush()

    # -- lookups ------------------------------------------------------------ #
    def item(self, tank):
        return next(value for value in self.fixture.manifest_items
                    if value["tank_id"] == tank)

    def _evidence(self, attr, tank):
        return next(value for value in getattr(self.fixture, attr)
                    if value["tank_id"] == tank)

    def approval(self, tank):
        return self._evidence("approval_items", tank)

    def label(self, tank):
        return self._evidence("label_items", tank)

    def authority(self, tank):
        return self._evidence("authority_items", tank)

    # -- mutations ---------------------------------------------------------- #
    def _rename(self, old, new):
        touched = 0
        for entry in self.fixture.manifest_items:
            if entry["tank_id"] == old:
                entry["tank_id"] = new
                entry["approved_title"] = entry["approved_title"].replace(old, new, 1)
                identity = entry.get("identity")
                if isinstance(identity, dict):
                    for field in ("detected_tank", "requested_tank", "accepted_tank"):
                        if identity.get(field) == old:
                            identity[field] = new
                touched += 1
        for entry in self.fixture.approval_items:
            if entry["tank_id"] == old:
                entry["tank_id"] = new
                entry["existing_title"] = entry["existing_title"].replace(old, new, 1)
                entry["proposed_title"] = entry["proposed_title"].replace(old, new, 1)
        for attr in ("snapshot_records", "detail_items", "label_items", "authority_items"):
            for entry in getattr(self.fixture, attr):
                if entry["tank_id"] == old:
                    entry["tank_id"] = new
        assert touched == 1, f"rename target {old} not found exactly once"

    def bind_photo(self, tank, photo, *, arrival_date="2026-10-14"):
        """Bind a real photo file to one item, updating every hash binding."""
        photo = Path(photo)
        destination = self.root / f"{tank}-original{photo.suffix}"
        shutil.copy2(photo, destination)
        digest = sha256(destination)
        item = self.item(tank)
        item["original"] = {
            "path": str(destination), "sha256": digest, "mime_type": "image/png",
        }
        item["arrival_date"] = arrival_date
        item["identity"]["source_sha256"] = digest
        approval = self.approval(tank)
        approval["original_path"] = str(destination)
        approval["original_sha256"] = digest
        approval["proposed_arrival_date"] = arrival_date
        label = self.label(tank)
        label["source_path"] = str(destination)
        label["source_sha256"] = digest
        label["photo_date"] = arrival_date
        self.authority(tank)["source_sha256"] = digest
        qa_path = Path(item["image_qa"]["path"])
        qa = json.loads(qa_path.read_text())
        qa["input_hashes"] = [digest, item["hero"]["sha256"], digest]
        item["image_qa"]["sha256"] = shopify_mod.write_json(qa_path, qa)
        return digest

    def set_identity(self, tank, **fields):
        self.item(tank)["identity"].update(fields)

    def record_correction(self, tank, **overrides):
        item = self.item(tank)
        values = {
            "source_sha256": item["original"]["sha256"],
            "original_model_tank": "5BT43",
            "corrected_tank": tank,
            "product_id": item["product_id"],
            "variant_id": item["variant_id"],
            "operation": {
                "fields": list(bsb.IDENTITY_OPERATION_FIELDS),
                "mode": "owner-directed",
            },
            "reason": "owner corrected the vision tank reading",
            "evidence_reference": "discord:message:test-evidence",
            "operator": "owner",
            "directory": self.root / "corrections",
            "created_at": "2026-10-15T00:00:00+00:00",
        }
        values.update(overrides)
        path = corrections.record(**values)
        return path, json.loads(path.read_text())

    def flush(self):
        manifest = json.loads(self.fixture.manifest_path.read_text())
        for name, (key, attr) in self.EVIDENCE_SHAPES.items():
            value = {key: getattr(self.fixture, attr)}
            path = self.root / f"{name}.json"
            manifest["evidence"][name]["sha256"] = shopify_mod.write_json(path, value)
        manifest["items"] = self.fixture.manifest_items
        shopify_mod.write_json(self.fixture.manifest_path, manifest)

    def load(self):
        return bsb.ManifestBundle(self.fixture.manifest_path)


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    # -- helpers ------------------------------------------------------------ #
    def fixtures_are_genuine(self):
        self.assertEqual(sha256(INCIDENT_PHOTO), INCIDENT_SHA)
        self.assertEqual(sha256(NEAR_CONFUSION_PHOTO), NEAR_CONFUSION_SHA)

    def cli(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = bsb.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()


# --------------------------------------------------------------------------- #
# 1. THE CENTRAL ATTACK — update 5BT43 while the owner requested 2BT23
# --------------------------------------------------------------------------- #
class UploaderIdentityGateAttacks(BaseCase):
    def test_central_attack_read_2bt23_target_5bt43_without_correction_refused(self):
        """Fred's exact shape: the incident photo (reads 2BT23) used to update 5BT43."""
        self.fixtures_are_genuine()
        site = IncidentSite(self.root)
        site.bind_photo("5BT43", INCIDENT_PHOTO)
        site.set_identity(
            "5BT43", detected_tank="2BT23", requested_tank="5BT43",
            accepted_tank="5BT43", correction_sha256=None)
        site.flush()
        with self.assertRaisesRegex(
                bsb.ManifestError, "without a correction record"):
            site.load()

    def test_central_attack_honest_request_2bt23_cannot_target_5bt43(self):
        """accepted_tank must equal the manifest tank: a 2BT23 request cannot
        silently become a 5BT43 mutation, with or without a record (the record
        contract itself requires requested == corrected == accepted)."""
        site = IncidentSite(self.root)
        site.bind_photo("5BT43", INCIDENT_PHOTO)
        site.set_identity(
            "5BT43", detected_tank="2BT23", requested_tank="2BT23",
            accepted_tank="5BT43", correction_sha256=None)
        site.flush()
        with self.assertRaisesRegex(
                bsb.ManifestError, "requested_tank must equal the manifest tank"):
            site.load()

    def test_central_attack_accepted_tank_must_equal_item_tank(self):
        site = IncidentSite(self.root)
        site.bind_photo("5BT43", INCIDENT_PHOTO)
        site.set_identity(
            "5BT43", detected_tank="5BT43", requested_tank="5BT43",
            accepted_tank="2BT23", correction_sha256=None)
        site.flush()
        with self.assertRaisesRegex(
                bsb.ManifestError, "accepted_tank must equal the manifest tank"):
            site.load()

    def test_central_attack_valid_correction_is_the_designed_override(self):
        """The honest mismatch (vision read 5BT43, owner corrected 2BT23) is
        refused without a record and allowed only with the exact record."""
        self.fixtures_are_genuine()
        site = IncidentSite(self.root)
        site.bind_photo("2BT23", INCIDENT_PHOTO)
        site.set_identity(
            "2BT23", detected_tank="5BT43", requested_tank="2BT23",
            accepted_tank="2BT23", correction_sha256=None)
        site.flush()
        with self.assertRaisesRegex(
                bsb.ManifestError, "differs from the requested tank"):
            site.load()
        path, record = site.record_correction(
            "2BT23", original_model_tank="5BT43")
        site.set_identity("2BT23", correction_sha256=record["correction_sha256"])
        site.flush()
        bundle = site.load()
        self.assertEqual(bundle.contexts["2BT23"].raw["identity"]["detected_tank"],
                         "5BT43")

    def test_correction_with_wrong_source_refused(self):
        """Correction recorded for the near-confusion 5BT43 photo presented for
        the incident photo (2BT23) — must fail on the source binding."""
        self.fixtures_are_genuine()
        site = IncidentSite(self.root)
        site.bind_photo("2BT23", INCIDENT_PHOTO)
        _, record = site.record_correction(
            "2BT23", source_sha256=NEAR_CONFUSION_SHA,
            original_model_tank="5BT43")
        site.set_identity(
            "2BT23", detected_tank="5BT43", requested_tank="2BT23",
            accepted_tank="2BT23", correction_sha256=record["correction_sha256"])
        site.flush()
        with self.assertRaisesRegex(bsb.ManifestError, "source_sha256_mismatch"):
            site.load()

    def test_correction_with_wrong_product_refused(self):
        site = IncidentSite(self.root)
        wrong_product = site.item("5BT43")["product_id"]
        _, record = site.record_correction(
            "2BT23", product_id=wrong_product, original_model_tank="5BT43")
        site.set_identity(
            "2BT23", detected_tank="5BT43", requested_tank="2BT23",
            accepted_tank="2BT23", correction_sha256=record["correction_sha256"])
        site.flush()
        with self.assertRaisesRegex(bsb.ManifestError, "product_id_mismatch"):
            site.load()

    def test_correction_copied_into_another_batch_refused(self):
        """Copy the valid record bytes (self-hash valid) into a second manifest
        and pair them with a different source photo: the record must not
        transfer to different bytes."""
        site_a = IncidentSite(self.root / "a")
        path_a, record_a = site_a.record_correction("2BT23")
        site_b = IncidentSite(self.root / "b")
        (site_b.root / "corrections").mkdir(parents=True, exist_ok=True)
        shutil.copy2(path_a, site_b.root / "corrections" / path_a.name)
        site_b.bind_photo("2BT23", NEAR_CONFUSION_PHOTO)
        site_b.set_identity(
            "2BT23", detected_tank="5BT43", requested_tank="2BT23",
            accepted_tank="2BT23",
            correction_sha256=record_a["correction_sha256"])
        site_b.flush()
        with self.assertRaisesRegex(bsb.ManifestError, "source_sha256_mismatch"):
            site_b.load()

    def test_correction_must_reside_at_the_bound_path(self):
        """A valid record moved away from the bound corrections directory is
        simply unavailable; copying the file elsewhere does not authorise."""
        site = IncidentSite(self.root)
        path, record = site.record_correction("2BT23")
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        shutil.move(str(path), str(elsewhere / path.name))
        site.set_identity(
            "2BT23", detected_tank="5BT43", requested_tank="2BT23",
            accepted_tank="2BT23", correction_sha256=record["correction_sha256"])
        site.flush()
        with self.assertRaisesRegex(bsb.ManifestError, "record_unavailable"):
            site.load()

    def test_correction_tampered_bytes_refused(self):
        site = IncidentSite(self.root)
        path, record = site.record_correction("2BT23")
        path.chmod(0o600)
        tampered = json.loads(path.read_text())
        tampered["corrected_tank"] = "5BT43"
        path.write_text(json.dumps(tampered))
        site.set_identity(
            "2BT23", detected_tank="5BT43", requested_tank="2BT23",
            accepted_tank="2BT23", correction_sha256=record["correction_sha256"])
        site.flush()
        with self.assertRaisesRegex(bsb.ManifestError, "self_hash_mismatch"):
            site.load()

    def test_correction_nonexistent_path_refused(self):
        site = IncidentSite(self.root)
        site.set_identity(
            "2BT23", detected_tank="5BT43", requested_tank="2BT23",
            accepted_tank="2BT23", correction_sha256="ab" * 32)
        site.flush()
        with self.assertRaisesRegex(bsb.ManifestError, "record_unavailable"):
            site.load()

    def test_correction_hash_must_be_lowercase(self):
        site = IncidentSite(self.root)
        site.set_identity(
            "2BT23", detected_tank="5BT43", requested_tank="2BT23",
            accepted_tank="2BT23", correction_sha256="AB" * 32)
        site.flush()
        with self.assertRaisesRegex(bsb.ManifestError, "lowercase SHA-256"):
            site.load()

    def test_identity_block_key_set_is_exact(self):
        site = IncidentSite(self.root)
        site.item("2BT23")["identity"]["extra"] = "smuggled"
        site.flush()
        with self.assertRaisesRegex(bsb.ManifestError, "identity block must contain exactly"):
            site.load()
        site = IncidentSite(self.root / "missing")
        del site.item("2BT23")["identity"]["requested_tank"]
        site.flush()
        with self.assertRaisesRegex(bsb.ManifestError, "identity block must contain exactly"):
            site.load()

    def test_identity_source_hash_must_bind_the_real_original_bytes(self):
        """Declare the incident-photo sha in the identity block while the
        original asset still hashes to different bytes — the uploader hashes
        the file, so this cannot be claimed."""
        self.fixtures_are_genuine()
        site = IncidentSite(self.root)
        site.set_identity("2BT23", source_sha256=INCIDENT_SHA)
        site.set_identity("5BT43", source_sha256=INCIDENT_SHA)
        site.flush()
        with self.assertRaisesRegex(
                bsb.ManifestError, "identity source hash differs"):
            site.load()

    def test_identity_tank_values_must_be_canonical(self):
        site = IncidentSite(self.root)
        site.set_identity("2BT23", detected_tank="2bt23")
        site.flush()
        with self.assertRaisesRegex(bsb.ManifestError, "canonical tank ID required"):
            site.load()

    def test_identity_source_sha_must_be_lowercase(self):
        site = IncidentSite(self.root)
        site.set_identity("2BT23", source_sha256=INCIDENT_SHA.upper())
        site.flush()
        with self.assertRaisesRegex(bsb.ManifestError, "lowercase SHA-256"):
            site.load()

    def test_identity_operation_fields_are_frozen(self):
        """Pin the field set a correction must cover; any loosening is a
        firewall change and must fail this test loudly."""
        self.assertEqual(tuple(bsb.IDENTITY_OPERATION_FIELDS),
                         ("title", "arrival_date", "inventory", "media"))

    def test_every_cli_command_refuses_broken_identity_before_any_state(self):
        site = IncidentSite(self.root, authorised=True)
        site.bind_photo("5BT43", INCIDENT_PHOTO)
        site.set_identity(
            "5BT43", detected_tank="2BT23", requested_tank="5BT43",
            accepted_tank="5BT43", correction_sha256=None)
        site.flush()
        for command in ("preflight", "dry-run", "execute", "resume", "status", "verify"):
            code, _out, err = self.cli(
                [command, "--manifest", str(site.fixture.manifest_path)])
            self.assertEqual(2, code, command)
            self.assertIn("without a correction record", err, command)
        self.assertFalse((self.root / "state").exists())
        self.assertFalse((self.root / "reports").exists())

    def test_policy_authorise_manifest_applies_the_identity_gate(self):
        """The standing-policy automatic authority loads the manifest through
        the uploader: a wrong identity must fail before any receipt exists."""
        site = IncidentSite(self.root, authorised=True)
        data = betta_policy.default_policy()
        data.update(enabled=True, automatic_batch_authorisation=True)
        policy = betta_policy.StandingPolicy(data)
        receipt_path = self.root / "authority-ok.json"
        receipt = policy.authorise_manifest(site.fixture.manifest_path, receipt_path)
        self.assertEqual(receipt["authorisation_mode"], "automatic-standing-bau")
        self.assertTrue(receipt_path.is_file())

        site.bind_photo("5BT43", INCIDENT_PHOTO)
        site.set_identity(
            "5BT43", detected_tank="2BT23", requested_tank="5BT43",
            accepted_tank="5BT43", correction_sha256=None)
        site.flush()
        attack_receipt = self.root / "authority-attack.json"
        with self.assertRaisesRegex(
                betta_policy.PolicyError, "uploader rejected manifest"):
            policy.authorise_manifest(site.fixture.manifest_path, attack_receipt)
        self.assertFalse(attack_receipt.exists())

    def test_legacy_digest_grant_cannot_bypass_the_identity_gate(self):
        """Even with an owner-recorded legacy digest grant, the live execute
        command re-loads the manifest through the identity gate and refuses."""
        site = IncidentSite(self.root, authorised=True)
        site.bind_photo("5BT43", INCIDENT_PHOTO)
        site.set_identity(
            "5BT43", detected_tank="2BT23", requested_tank="5BT43",
            accepted_tank="5BT43", correction_sha256=None)
        site.flush()
        digest = bsb.sha256_file(site.fixture.manifest_path)
        data = betta_policy.default_policy()
        data.update(enabled=True)
        data["authorisations"] = [{
            "manifest_sha256": digest, "receipt": "owner-grant-test",
            "at": "2026-10-15T00:00:00+11:00",
        }]
        policy = betta_policy.StandingPolicy(data)
        self.assertIsNotNone(policy.authorise(digest))
        code, _out, err = self.cli([
            "execute", "--manifest", str(site.fixture.manifest_path),
            "--live", "--confirm-manifest-sha256", digest,
        ])
        self.assertEqual(2, code)
        self.assertIn("without a correction record", err)
        self.assertFalse((self.root / "state").exists())

    def test_state_store_refuses_a_manifest_swap(self):
        """An existing state belongs to its exact manifest digest; a swapped
        manifest cannot re-use the state of a completed upload."""
        site = IncidentSite(self.root, authorised=True)
        bundle = site.load()
        bsb.StateStore(bundle)  # creates state bound to manifest digest A
        manifest = json.loads(site.fixture.manifest_path.read_text())
        manifest["note"] = "swapped-manifest-bytes"
        shopify_mod.write_json(site.fixture.manifest_path, manifest)
        swapped = site.load()
        self.assertNotEqual(bundle.sha256, swapped.sha256)
        with self.assertRaisesRegex(bsb.BatchError, "different manifest digest"):
            bsb.StateStore(swapped)


# --------------------------------------------------------------------------- #
# 2. Dual-read false confidence and the gate-aware retry refinement
# --------------------------------------------------------------------------- #
class DualReadFalseConfidence(BaseCase):
    def sandbox(self, name, catalogue, label):
        return StrictSandbox(self.root / name, [INCIDENT_PHOTO], {
            INCIDENT_SHA: {
                "catalogue": catalogue,
                "label": label,
                "preflight": preflight_output("2BT23", "2026-10-14"),
                "prepqa": prepqa_output(),
            }
        })

    def identify_and_retry(self, sandbox):
        record = sandbox.adapters["intake"](sandbox.batch_dir, {})["fish"][0]
        decision = sandbox.adapters["identify"](record, sandbox.batch_dir)
        entry = {"source_path": record["path"], "source_sha256": record["sha256"]}
        entry.update(decision)
        retry = sandbox.adapters["retry_identify"](entry, sandbox.batch_dir)
        return decision, retry

    def test_confident_crop_contradicting_confident_full_read_quarantines(self):
        """If the crop read is a confident hallucination (5BT43) while the full
        read is confident and correct (2BT23), the process must quarantine."""
        self.fixtures_are_genuine()
        sandbox = self.sandbox(
            "wrong-crop",
            catalogue_output("2BT23", "2026-10-14", 0.99, 0.96),
            label_output("5BT43", "9/10/2026", 0.99, 0.96))
        result = sandbox.run()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["published"], 0)
        self.assertEqual(result["quarantined"], 1)
        self.assertEqual(sandbox.calls["generate"], 0)
        self.assertEqual(sandbox.calls["execute"], 0)
        entry = sandbox.entry()
        self.assertEqual(entry["status"], "QUARANTINED")
        self.assertEqual(entry["label_reads"]["status"], "DISAGREE")
        self.assertIn("disagreement", entry["notes"][0])
        self.assertFalse((sandbox.batch_dir / "state" / "authority.json").exists())

    def test_below_gate_full_tank_cannot_veto_confident_crop(self):
        site = self.sandbox(
            "below-tank",
            catalogue_output("5BT43", "2026-10-14", 0.80, 0.96),
            label_output("2BT23", "14/10/2026", 0.99, 0.96))
        decision, retry = self.identify_and_retry(site)
        self.assertTrue(decision["uncertain"])
        self.assertEqual(retry["label_reads"]["status"], "RETRY_ACCEPTED")
        self.assertFalse(retry["uncertain"])
        self.assertEqual(retry["tank_id"], "2BT23")
        self.assertEqual(retry["photo_date"], "2026-10-14")
        receipt = json.loads(Path(retry["catalogue_evidence_path"]).read_text())
        self.assertIs(receipt["catalogue_reading"]["gate_passed"]["tank_id"], False)
        self.assertEqual(receipt["catalogue_reading"]["disposition"], "ACCEPTED")

    def test_recorded_real_run_shape_now_accepts_via_below_gate_refinement(self):
        """The recorded real run (tank 0.98/date 0.88 below gate; crop
        2BT23/2026-10-14) quarantined on the revision that produced the
        archived receipts.  The current gate-aware refinement discards the
        below-gate date and ACCEPTS the crop's (correct) date.  This test pins
        the current behaviour so the review can flag the docs/evidence drift
        explicitly; the safety invariant (never accept the misread date) still
        holds."""
        site = self.sandbox(
            "real-shape",
            catalogue_output("2BT23", "2026-04-10", 0.98, 0.88),
            label_output("2BT23", "14/10/2026", 0.99, 0.95))
        decision, retry = self.identify_and_retry(site)
        self.assertTrue(decision["uncertain"])
        self.assertEqual(retry["label_reads"]["status"], "RETRY_ACCEPTED")
        self.assertEqual(retry["tank_id"], "2BT23")
        self.assertEqual(retry["photo_date"], "2026-10-14")
        receipt = json.loads(Path(retry["catalogue_evidence_path"]).read_text())
        self.assertIs(receipt["catalogue_reading"]["gate_passed"]["photo_date"], False)
        self.assertEqual(receipt["catalogue_reading"]["disposition"], "ACCEPTED")
        identify_receipt = json.loads(
            Path(decision["catalogue_evidence_path"]).read_text())
        self.assertEqual(identify_receipt["uncertain"], True)
        self.assertEqual(identify_receipt["uncertain_reason"],
                         "catalogue confidence below 0.90")
        self.assertIsNone(identify_receipt["catalogue_confidences"]["photo_date"])
        archived = json.loads((TESTS_DIR.parent / "docs" / "incident" /
                               "incident_eval" /
                               "real-run-label-retry-receipt.json").read_text())
        self.assertEqual(archived["contradiction"],
                         "catalogue date 2026-04-10 vs label date 2026-10-14")
        # The archived receipt predates the gate-aware refinement: its
        # catalogue_reading has no gate_passed/disposition and the receipt has
        # no catalogue_confidence_gates field.  It is historical evidence, not
        # a reproducible outcome of the current code.
        self.assertNotIn("gate_passed", archived["catalogue_reading"])
        self.assertNotIn("disposition", archived["catalogue_reading"])
        self.assertNotIn("catalogue_confidence_gates", archived)

    def test_confidence_audit_fields_use_real_key_names(self):
        """Post-review regression pin (L1 fixed by A4): the catalogue receipt's
        ``catalogue_confidence_raw``/``..._gates`` audit fields now read through
        the same lookup the gates use, so the production model contract keys
        (``tank_confidence``/``date_confidence``) record the raw value and the
        true gate outcome — ``PASS`` for a passing field, ``BELOW_GATE`` with
        the raw value for a below-gate field — instead of MISSING/None."""
        real_keys = self.sandbox(
            "audit-real-keys",
            catalogue_output("2BT23", "2026-04-10", 0.98, 0.88),
            label_output("2BT23", "14/10/2026"))
        record = real_keys.adapters["intake"](real_keys.batch_dir, {})["fish"][0]
        decision = real_keys.adapters["identify"](record, real_keys.batch_dir)
        receipt = json.loads(Path(decision["catalogue_evidence_path"]).read_text())
        self.assertEqual(receipt["catalogue_confidence_gates"]["photo_date"],
                         "BELOW_GATE")
        self.assertEqual(receipt["catalogue_confidence_raw"]["photo_date"], 0.88)
        self.assertEqual(receipt["catalogue_confidence_gates"]["tank_id"], "PASS")
        self.assertEqual(receipt["catalogue_confidence_raw"]["tank_id"], 0.98)

        # The alternate mapping key form yields identical audit evidence.
        alt_keys = self.sandbox(
            "audit-alt-keys",
            catalogue_output("2BT23", "2026-04-10", 0.98, 0.88),
            label_output("2BT23", "14/10/2026"))
        output = alt_keys.vision[INCIDENT_SHA]["catalogue"]
        output["photo_date_confidence"] = output.pop("date_confidence")
        output["tank_id_confidence"] = output.pop("tank_confidence")
        record = alt_keys.adapters["intake"](alt_keys.batch_dir, {})["fish"][0]
        decision = alt_keys.adapters["identify"](record, alt_keys.batch_dir)
        receipt = json.loads(Path(decision["catalogue_evidence_path"]).read_text())
        self.assertEqual(receipt["catalogue_confidence_gates"]["photo_date"],
                         "BELOW_GATE")
        self.assertEqual(receipt["catalogue_confidence_raw"]["photo_date"], 0.88)
        self.assertEqual(receipt["catalogue_confidence_gates"]["tank_id"], "PASS")
        self.assertEqual(receipt["catalogue_confidence_raw"]["tank_id"], 0.98)

        # MISSING is reserved for values that are genuinely absent.
        absent = self.sandbox(
            "audit-absent",
            catalogue_output("2BT23", "2026-10-14", 0.98, None),
            label_output("2BT23", "14/10/2026"))
        absent.vision[INCIDENT_SHA]["catalogue"]["date_confidence"] = None
        record = absent.adapters["intake"](absent.batch_dir, {})["fish"][0]
        decision = absent.adapters["identify"](record, absent.batch_dir)
        receipt = json.loads(Path(decision["catalogue_evidence_path"]).read_text())
        self.assertEqual(receipt["catalogue_confidence_gates"]["photo_date"],
                         "MISSING")
        self.assertIsNone(receipt["catalogue_confidence_raw"]["photo_date"])
        self.assertEqual(receipt["catalogue_confidence_gates"]["tank_id"], "PASS")

    def test_below_gate_date_cannot_veto_confident_crop(self):
        site = self.sandbox(
            "below-date",
            catalogue_output("2BT23", "2026-04-10", 0.98, 0.80),
            label_output("2BT23", "14/10/2026", 0.99, 0.96))
        decision, retry = self.identify_and_retry(site)
        self.assertEqual(retry["label_reads"]["status"], "RETRY_ACCEPTED")
        self.assertEqual(retry["photo_date"], "2026-10-14")

    def test_both_below_gate_cannot_veto_confident_crop(self):
        site = self.sandbox(
            "below-both",
            catalogue_output("5BT43", "2026-04-10", 0.80, 0.80),
            label_output("2BT23", "14/10/2026", 0.99, 0.96))
        _decision, retry = self.identify_and_retry(site)
        self.assertEqual(retry["label_reads"]["status"], "RETRY_ACCEPTED")
        self.assertEqual(retry["tank_id"], "2BT23")

    def test_gated_tank_contradiction_still_refuses(self):
        site = self.sandbox(
            "gated-tank",
            catalogue_output("5BT43", "2026-10-14", 0.98, 0.96),
            label_output("2BT23", "14/10/2026", 0.99, 0.96))
        decision, retry = self.identify_and_retry(site)
        self.assertTrue(decision["quarantine"])
        self.assertEqual(retry["label_reads"]["status"], "RETRY_CONFLICT")
        self.assertTrue(retry["uncertain"])
        self.assertIsNone(retry["tank_id"])
        self.assertIsNone(retry["photo_date"])
        self.assertTrue(retry["reason"].startswith(
            "focused label read contradicts the catalogue read"))

    def test_gated_date_contradiction_still_refuses(self):
        site = self.sandbox(
            "gated-date",
            catalogue_output("2BT23", "2026-09-30", 0.98, 0.96),
            label_output("2BT23", "14/10/2026", 0.99, 0.96))
        _decision, retry = self.identify_and_retry(site)
        self.assertEqual(retry["label_reads"]["status"], "RETRY_CONFLICT")
        self.assertIsNone(retry["photo_date"])


# --------------------------------------------------------------------------- #
# 3. Source binding — drifted photos, crops and evidence
# --------------------------------------------------------------------------- #
class SourceBindingAttacks(BaseCase):
    def test_retry_refuses_drifted_source_bytes(self):
        sandbox = StrictSandbox(self.root / "sandbox", [INCIDENT_PHOTO], {
            INCIDENT_SHA: {
                "catalogue": catalogue_output("2BT23", "2026-04-10", 0.98, 0.80),
                "label": label_output("2BT23", "14/10/2026"),
                "preflight": preflight_output("2BT23", "2026-10-14"),
                "prepqa": prepqa_output(),
            }
        })
        record = sandbox.adapters["intake"](sandbox.batch_dir, {})["fish"][0]
        decision = sandbox.adapters["identify"](record, sandbox.batch_dir)
        entry = {"source_path": record["path"], "source_sha256": record["sha256"]}
        entry.update(decision)
        # Drift the batch copy of the photo after identification.
        shutil.copy2(NEAR_CONFUSION_PHOTO, record["path"])
        with self.assertRaisesRegex(
                incident_mod.betta_bau_adapters.StrictAdapterError,
                "label retry source changed"):
            sandbox.adapters["retry_identify"](entry, sandbox.batch_dir)

    def test_corroboration_receipt_refuses_changed_crop_bytes(self):
        sandbox = StrictSandbox(self.root / "sandbox", [INCIDENT_PHOTO], {
            INCIDENT_SHA: {
                "catalogue": catalogue_output("2BT23", "2026-10-14", 0.99, 0.96),
                "label": label_output("2BT23", "14/10/2026"),
                "preflight": preflight_output("2BT23", "2026-10-14"),
                "prepqa": prepqa_output(),
            }
        })
        record = sandbox.adapters["intake"](sandbox.batch_dir, {})["fish"][0]
        decision = sandbox.adapters["identify"](record, sandbox.batch_dir)
        self.assertEqual(decision["label_reads"]["status"], "AGREE")
        crop = Path(decision["label_reads"]["crop"]["crop_path"])
        crop.write_bytes(b"tampered-crop-bytes")
        with self.assertRaisesRegex(
                incident_mod.betta_bau_adapters.StrictAdapterError,
                "label crop changed since its corroboration receipt"):
            sandbox.adapters["identify"](record, sandbox.batch_dir)

    def test_corroboration_receipt_binds_source_crop_and_full_receipt(self):
        self.fixtures_are_genuine()
        sandbox = StrictSandbox(self.root / "sandbox", [INCIDENT_PHOTO], {
            INCIDENT_SHA: {
                "catalogue": catalogue_output("2BT23", "2026-10-14", 0.99, 0.96),
                "label": label_output("2BT23", "14/10/2026"),
                "preflight": preflight_output("2BT23", "2026-10-14"),
                "prepqa": prepqa_output(),
            }
        })
        record = sandbox.adapters["intake"](sandbox.batch_dir, {})["fish"][0]
        decision = sandbox.adapters["identify"](record, sandbox.batch_dir)
        reads = decision["label_reads"]
        self.assertEqual(reads["full"]["receipt_sha256"],
                         sha256(reads["full"]["receipt_path"]))
        self.assertEqual(reads["crop"]["receipt_sha256"],
                         sha256(reads["crop"]["receipt_path"]))
        self.assertEqual(reads["crop"]["crop_sha256"],
                         sha256(reads["crop"]["crop_path"]))
        receipt = json.loads(Path(reads["crop"]["receipt_path"]).read_text())
        self.assertEqual(receipt["source_identity"]["sha256"], INCIDENT_SHA)
        self.assertEqual(receipt["input_hashes"], [reads["crop"]["crop_sha256"]])
        self.assertEqual(receipt["full_read"]["receipt_sha256"],
                         reads["full"]["receipt_sha256"])
        # The recorded crop detection points at the live final crop path (the
        # A5-reported stale ``.part`` path is fixed at this revision).
        detection = receipt["crop_identity"]["detection"]
        self.assertEqual(detection["output_path"], receipt["crop_identity"]["path"])
        self.assertTrue(Path(detection["output_path"]).is_file())
        self.assertNotIn(".part", detection["output_path"])

    def test_uploader_resume_refuses_drifted_evidence_and_makes_no_write(self):
        site = IncidentSite(self.root, authorised=True)
        bundle = site.load()
        contexts = bundle.select()
        gateway = FakeGateway(contexts)
        state = bsb.StateStore(bundle)
        uploader = bsb.BatchUploader(
            bundle, gateway, state, sleep=lambda _: None,
            upload=lambda target, asset: None, poll_attempts=5, poll_interval=0)
        report = uploader.execute(contexts)
        self.assertEqual(2, report["verified_count"])
        writes_before = len(gateway.writes)
        state_path = Path(state.path)
        state_bytes = state_path.read_bytes()
        # Drift one evidence sidecar after a completed run.
        evidence = self.root / "approval_plan.json"
        evidence.write_bytes(evidence.read_bytes() + b"\n")
        code, _out, err = self.cli(
            ["resume", "--manifest", str(site.fixture.manifest_path)])
        self.assertEqual(2, code)
        self.assertIn("hash mismatch", err)
        self.assertEqual(state_path.read_bytes(), state_bytes)
        self.assertEqual(len(gateway.writes), writes_before)
        self.assertEqual(state.item("2BT23")["stage"], "VERIFIED")

    def test_uploader_refuses_drifted_asset_bytes(self):
        site = IncidentSite(self.root)
        hero = Path(site.item("5BT43")["hero"]["path"])
        hero.write_bytes(hero.read_bytes() + b"x")
        with self.assertRaisesRegex(bsb.ManifestError, "hash mismatch"):
            site.load()


# --------------------------------------------------------------------------- #
# 4. Cross-product contamination between concurrent sandboxes
# --------------------------------------------------------------------------- #
class CrossProductContamination(BaseCase):
    def make_sandbox(self, name, source, tank, date_iso, date_dmy, registry):
        return StrictSandbox(self.root / name, [source], {
            sha256(source): {
                "catalogue": catalogue_output(tank, date_iso),
                "label": label_output(tank, date_dmy),
                "preflight": preflight_output(tank, date_iso),
                "prepqa": prepqa_output(),
            }
        }, policy_mode="full", registry=registry, label=name)

    def test_concurrent_shared_registry_keeps_identities_uncrossed(self):
        self.fixtures_are_genuine()
        registry = self.root / "shared-registry.sqlite3"
        incident = self.make_sandbox(
            "batch-2bt23", INCIDENT_PHOTO, "2BT23", "2026-10-14", "14/10/2026",
            registry)
        confusion = self.make_sandbox(
            "batch-5bt43", NEAR_CONFUSION_PHOTO, "5BT43", "2026-10-09",
            "9/10/2026", registry)
        results = {}

        def run(name, sandbox):
            results[name] = sandbox.run()

        threads = [
            threading.Thread(target=run, args=("incident", incident)),
            threading.Thread(target=run, args=("confusion", confusion)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=180)
            self.assertFalse(thread.is_alive(), "sandbox run did not finish")
        self.assertEqual(results["incident"]["status"], "COMPLETE")
        self.assertEqual(results["confusion"]["status"], "COMPLETE")

        incident_entry, confusion_entry = incident.entry(), confusion.entry()
        self.assertEqual(incident_entry["source_sha256"], INCIDENT_SHA)
        self.assertEqual(confusion_entry["source_sha256"], NEAR_CONFUSION_SHA)
        self.assertEqual(incident_entry["tank_id"], "2BT23")
        self.assertEqual(confusion_entry["tank_id"], "5BT43")

        # No text artifact of one batch references the other identity.
        other_text = self._text_artifacts(incident.batch_dir)
        self.assertFalse(any(NEAR_CONFUSION_SHA in value for value in other_text))
        self.assertFalse(any("5BT43" in value for value in other_text))
        other_text = self._text_artifacts(confusion.batch_dir)
        self.assertFalse(any(INCIDENT_SHA in value for value in other_text))
        self.assertFalse(any("2BT23" in value for value in other_text))

        # Both identities remain distinct in the shared registry.
        con = sqlite3.connect(registry)
        try:
            rows = dict(con.execute(
                "SELECT source_sha256, batch_id FROM processed").fetchall())
        finally:
            con.close()
        self.assertEqual(rows, {
            INCIDENT_SHA: incident.batch_id,
            NEAR_CONFUSION_SHA: confusion.batch_id,
        })

    def _text_artifacts(self, batch_dir):
        values = []
        for path in sorted(Path(batch_dir).rglob("*")):
            if path.is_file() and path.suffix in {".json", ".md", ".txt", ".csv"}:
                try:
                    values.append(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError):
                    continue
        return values

    def test_registry_cannot_rebind_a_processed_identity(self):
        registry_path = self.root / "registry.sqlite3"
        registry = incident_mod.betta_watch.ProcessedRegistry(registry_path)
        registry.record(INCIDENT_SHA, "batch-first")
        registry.record(INCIDENT_SHA, "batch-second")
        self.assertEqual(registry.hashes(), {INCIDENT_SHA})
        con = sqlite3.connect(registry_path)
        try:
            rows = con.execute(
                "SELECT source_sha256, batch_id FROM processed").fetchall()
        finally:
            con.close()
        self.assertEqual(rows, [(INCIDENT_SHA, "batch-first")])

    def test_cross_linked_manifest_identity_refused(self):
        self.fixtures_are_genuine()
        site = IncidentSite(self.root)
        with self.assertRaisesRegex(
                bsb.ManifestError, "identity source hash differs"):
            site.set_identity("5BT43", source_sha256=NEAR_CONFUSION_SHA)
            site.flush()
            site.load()


# --------------------------------------------------------------------------- #
# 5. Protected fields, baseline drift, duplicate mutations
# --------------------------------------------------------------------------- #
class ProtectedFieldAndIdempotencyAttacks(BaseCase):
    def build(self, site):
        bundle = site.load()
        contexts = bundle.select()
        gateway = FakeGateway(contexts)
        state = bsb.StateStore(bundle)
        uploader = bsb.BatchUploader(
            bundle, gateway, state, sleep=lambda _: None,
            upload=lambda target, asset: None, poll_attempts=5, poll_interval=0)
        return bundle, contexts, gateway, state, uploader

    def test_protected_field_drift_blocks_before_any_write(self):
        site = IncidentSite(self.root, authorised=True)
        _bundle, contexts, gateway, state, uploader = self.build(site)
        for product in gateway.live.values():
            product["price"] = "26.00"
        report = uploader.execute(contexts)
        self.assertEqual(0, report["verified_count"])
        self.assertEqual(2, report["blocked_count"])
        self.assertIn("protected price changed", report["items"][0]["error"])
        self.assertEqual([], gateway.writes)
        self.assertEqual("BLOCKED", state.item("2BT23")["stage"])

    def test_mocked_write_path_never_touches_price_cost_vendor(self):
        site = IncidentSite(self.root, authorised=True)
        _bundle, contexts, gateway, state, uploader = self.build(site)
        report = uploader.execute(contexts)
        self.assertEqual(2, report["verified_count"])
        operations = [operation for operation, _ in gateway.writes]
        self.assertEqual(operations, [
            "betta_batch_stage_images",
            "betta_batch_add_images",
            "betta_batch_reorder_media",
            "betta_batch_delete_media",
            "betta_batch_update_details",
            "betta_batch_set_inventory",
            "betta_batch_stage_images",
            "betta_batch_add_images",
            "betta_batch_reorder_media",
            "betta_batch_delete_media",
            "betta_batch_update_details",
            "betta_batch_set_inventory",
        ])
        for operation, variables in gateway.writes:
            self.assertNotIn(operation, {
                "betta_merch_update_product", "betta_merch_update_variant"})
            for key in self._keys(variables):
                self.assertNotIn(key, {"price", "cost", "vendor"})
        details = [variables for operation, variables in gateway.writes
                   if operation == "betta_batch_update_details"]
        for variables in details:
            self.assertEqual(set(variables["product"]), {"id", "title", "metafields"})

        # Second pass: no duplicate mutation, in particular no second stock set.
        inventory_writes = sum(
            operation == "betta_batch_set_inventory"
            for operation, _ in gateway.writes)
        self.assertEqual(2, inventory_writes)
        resume_report = uploader.resume(contexts, live_enabled=True)
        self.assertEqual(0, resume_report["blocked_count"])
        self.assertEqual(
            2, sum(operation == "betta_batch_set_inventory"
                   for operation, _ in gateway.writes))
        self.assertEqual("VERIFIED", state.item("2BT23")["stage"])
        self.assertEqual("VERIFIED", state.item("5BT43")["stage"])

    @staticmethod
    def _keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from ProtectedFieldAndIdempotencyAttacks._keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from ProtectedFieldAndIdempotencyAttacks._keys(item)


# --------------------------------------------------------------------------- #
# 6. Misreporting cross-check — audit document vs archived receipts
# --------------------------------------------------------------------------- #
class MisreportingCrossCheck(BaseCase):
    def test_incident_receipts_match_the_audit_document(self):
        audit = AUDIT_DOC.read_text(encoding="utf-8")
        unauthorized = json.loads(
            (EVIDENCE_DIR / "5BT43-unauthorized-receipt.json").read_text())
        repair = json.loads(
            (EVIDENCE_DIR / "2BT23-repair-receipt.json").read_text())

        self.assertEqual(
            unauthorized["planSha256"],
            "b691ee3ba68106ca8c69827dd47628ac93db9168dde1952c42c0cd243806ece5")
        self.assertIn("b691ee3b", audit)
        self.assertIn("806ece5", audit)
        self.assertEqual(unauthorized["target"]["productId"],
                         "gid://shopify/Product/7239072481489")
        self.assertEqual(unauthorized["target"]["variantId"],
                         "gid://shopify/ProductVariant/41532067512529")
        self.assertEqual(unauthorized["before"],
                         {"vendor": "NTA Imports", "price": "25.00", "cost": "1.0"})
        self.assertEqual(unauthorized["after"],
                         {"vendor": "Renial", "price": "35.00", "cost": "15.0"})

        self.assertEqual(
            repair["planSha256"],
            "5ed84ede17ef8676890304c127ee6bcd5b3cbdf934adcf4eab72ae397f1ed64c")
        self.assertIn("5ed84ede", audit)
        self.assertIn("1ed64c", audit)
        self.assertEqual(repair["targets"]["update2BT23"]["productId"],
                         "gid://shopify/Product/7255867588817")
        self.assertEqual(repair["targets"]["update2BT23"]["variantId"],
                         "gid://shopify/ProductVariant/41571765453009")

        # The repair receipt is the exact inverse of the unauthorised change.
        self.assertEqual(repair["before"]["5BT43"], unauthorized["after"])
        self.assertEqual(repair["after"]["5BT43"], unauthorized["before"])
        self.assertEqual(repair["after"]["2BT23"],
                         {"vendor": "Renial", "price": "35.00", "cost": "15.0"})

        # The audit's live-state claims reference the same identifiers/values.
        for needle in (
                "NTA Imports", "Renial", "25.00", "35.00", "1.0", "15.0",
                "41532067512529", "41571765453009",
                "2026-10-09", "2026-06-30", "My Home Business"):
            self.assertIn(needle, audit)

    def test_two_incident_uploads_remain_byte_identical(self):
        self.assertEqual(sha256(INCIDENT_PHOTO), INCIDENT_SHA)
        self.assertEqual(sha256(INCIDENT_PHOTO_SECOND), INCIDENT_SHA)
        self.assertEqual(INCIDENT_PHOTO.read_bytes(),
                         INCIDENT_PHOTO_SECOND.read_bytes())


# --------------------------------------------------------------------------- #
# 7. Owner-override scoping — reuse, repeats, field-set interchangeability
# --------------------------------------------------------------------------- #
class OwnerOverrideScoping(BaseCase):
    def setUp(self):
        super().setUp()
        self.site = IncidentSite(self.root)
        self.path, self.record = self.site.record_correction("2BT23")

    def validate(self, *, source=None, requested=None, accepted=None,
                 product=None, fields=None):
        item = self.site.item("2BT23")
        return corrections.validate_correction(
            self.path,
            source_sha256=source or item["original"]["sha256"],
            requested_tank=requested or "2BT23",
            accepted_tank=accepted or "2BT23",
            product_id=product or item["product_id"],
            operation_fields=fields if fields is not None
            else list(bsb.IDENTITY_OPERATION_FIELDS),
        )

    def test_reuse_for_another_source_refused(self):
        self.assertFalse(self.validate(source=NEAR_CONFUSION_SHA)["valid"])

    def test_reuse_for_another_product_refused(self):
        verdict = self.validate(product="gid://shopify/Product/7239072481489")
        self.assertFalse(verdict["valid"])
        self.assertEqual(verdict["reason"], "product_id_mismatch")

    def test_reuse_for_another_tank_refused(self):
        self.assertFalse(self.validate(accepted="5BT43")["valid"])
        self.assertFalse(self.validate(requested="5BT43")["valid"])

    def test_merch_scope_cannot_authorise_betta_operation(self):
        path, _record = self.site.record_correction(
            "5BT43", original_model_tank="1BT99",
            operation={"fields": ["retail", "cost", "vendor"],
                       "mode": "owner-directed"})
        verdict = corrections.validate_correction(
            path,
            source_sha256=self.site.item("5BT43")["original"]["sha256"],
            requested_tank="5BT43", accepted_tank="5BT43",
            product_id=self.site.item("5BT43")["product_id"],
            operation_fields=list(bsb.IDENTITY_OPERATION_FIELDS),
        )
        self.assertFalse(verdict["valid"])
        self.assertEqual(verdict["reason"], "operation_scope_mismatch")

    def test_betta_scope_cannot_authorise_merch_fields(self):
        verdict = self.validate(fields=["retail", "cost", "vendor"])
        self.assertFalse(verdict["valid"])
        self.assertEqual(verdict["reason"], "operation_scope_mismatch")

    def test_partial_scope_refused(self):
        """A record missing one of the four Betta operation fields cannot
        authorise the full uploader operation set."""
        missing = [field for field in bsb.IDENTITY_OPERATION_FIELDS
                   if field != "media"]
        path, _record = self.site.record_correction(
            "5BT43", original_model_tank="1BT99",
            operation={"fields": missing, "mode": "owner-directed"})
        verdict = corrections.validate_correction(
            path,
            source_sha256=self.site.item("5BT43")["original"]["sha256"],
            requested_tank="5BT43", accepted_tank="5BT43",
            product_id=self.site.item("5BT43")["product_id"],
            operation_fields=list(bsb.IDENTITY_OPERATION_FIELDS),
        )
        self.assertFalse(verdict["valid"])
        self.assertEqual(verdict["reason"], "operation_scope_mismatch")

    def test_repeat_recording_refused_and_original_bytes_stable(self):
        original = self.path.read_bytes()
        with self.assertRaisesRegex(corrections.CorrectionError, "already exists"):
            self.site.record_correction("2BT23")
        self.assertEqual(self.path.read_bytes(), original)
        self.assertTrue(self.validate()["valid"])

    def test_no_op_correction_refused_at_recording_and_validation(self):
        """Post-review regression pin (A3 hardening): a correction whose
        ``original_model_tank`` equals its ``corrected_tank`` is refused at
        creation and is invalid even when a caller hand-builds one with a valid
        self-hash (``no_op_correction``)."""
        with self.assertRaisesRegex(corrections.CorrectionError, "no-op"):
            self.site.record_correction("2BT23", original_model_tank="2BT23")
        item = self.site.item("2BT23")
        core = {
            "schema": corrections.SCHEMA,
            "source_sha256": item["original"]["sha256"],
            "original_model_tank": "2BT23",
            "corrected_tank": "2BT23",
            "product_id": item["product_id"],
            "variant_id": item["variant_id"],
            "operation": {"fields": list(bsb.IDENTITY_OPERATION_FIELDS),
                          "mode": "owner-directed"},
            "reason": "hand-built no-op",
            "evidence_reference": "review:test",
            "operator": "owner",
            "created_at": "2026-10-15T00:00:00+00:00",
        }
        hand_built = {**core, "correction_sha256": corrections.json_sha256(core)}
        verdict = corrections.validate_correction(
            hand_built,
            source_sha256=core["source_sha256"],
            requested_tank="2BT23", accepted_tank="2BT23",
            product_id=core["product_id"],
            operation_fields=list(bsb.IDENTITY_OPERATION_FIELDS),
        )
        self.assertFalse(verdict["valid"])
        self.assertEqual(verdict["reason"], "no_op_correction")

    def test_correction_variant_must_match_when_bound(self):
        """Post-review regression pin (A3 hardening): when a caller binds a
        variant, a record for a different variant is refused — including at the
        uploader, which now passes ``item.variant_id``."""
        item = self.site.item("2BT23")
        verdict = corrections.validate_correction(
            self.path,
            source_sha256=item["original"]["sha256"],
            requested_tank="2BT23", accepted_tank="2BT23",
            product_id=item["product_id"],
            variant_id="gid://shopify/ProductVariant/999",
            operation_fields=list(bsb.IDENTITY_OPERATION_FIELDS),
        )
        self.assertFalse(verdict["valid"])
        self.assertEqual(verdict["reason"], "variant_id_mismatch")

        path, record = self.site.record_correction(
            "5BT43", original_model_tank="1BT99",
            variant_id="gid://shopify/ProductVariant/999")
        self.site.set_identity(
            "5BT43", detected_tank="1BT99", requested_tank="5BT43",
            accepted_tank="5BT43", correction_sha256=record["correction_sha256"])
        self.site.flush()
        with self.assertRaisesRegex(bsb.ManifestError, "variant_id_mismatch"):
            self.site.load()

    def test_documentation_detected_tank_claim_is_not_authenticated(self):
        """The gate binds source/product/target/scope but does not compare the
        manifest's ``detected_tank`` claim with the record's
        ``original_model_tank``.  Neither value authorises anything, so this is
        an audit-trail consistency gap, not an authorisation bypass."""
        item = self.site.item("2BT23")
        item["identity"]["detected_tank"] = "1BT99"
        item["identity"]["correction_sha256"] = self.record["correction_sha256"]
        self.site.flush()
        bundle = self.site.load()
        self.assertEqual(bundle.contexts["2BT23"].raw["identity"]["detected_tank"],
                         "1BT99")
        self.assertEqual(self.record["original_model_tank"], "5BT43")


# --------------------------------------------------------------------------- #
# 8. Trust-boundary documentation — what the gate provably cannot know
# --------------------------------------------------------------------------- #
class TrustBoundaryDocumentation(BaseCase):
    def test_boundary_upstream_producer_lie_passes_the_gate(self):
        """Variant (e): the manifest asserts the incident photo *detected*
        5BT43 (requested==accepted==5BT43).  The gate cannot re-run vision, so
        a fully self-consistent lie loads.  What stops this upstream: the dual
        reads build the manifest and the recorded real reads of this exact
        photo are 2BT23 on both sides; the manifest producer would have to
        fabricate every hash-bound sidecar.  Residual trust: manifest
        authorship and the vision read it reports."""
        self.fixtures_are_genuine()
        site = IncidentSite(self.root)
        digest = site.bind_photo("5BT43", INCIDENT_PHOTO)
        site.set_identity(
            "5BT43", source_sha256=digest, detected_tank="5BT43",
            requested_tank="5BT43", accepted_tank="5BT43",
            correction_sha256=None)
        site.flush()
        bundle = site.load()
        self.assertEqual(bundle.contexts["5BT43"].raw["identity"], {
            "source_sha256": INCIDENT_SHA, "detected_tank": "5BT43",
            "requested_tank": "5BT43", "accepted_tank": "5BT43",
            "correction_sha256": None,
        })

    def test_boundary_self_minted_correction_passes_the_gate(self):
        """Variant (c2): an actor with write access to the corrections
        directory (or to a manifest-declared ``corrections_dir``) can mint a
        self-hashed record and pair it with an honest ``detected_tank`` claim.
        This is the same trust boundary as writing the manifest itself: the
        gate authenticates documents, not people.  Deployment requirement:
        the corrections directory must be owner-writable only."""
        self.fixtures_are_genuine()
        site = IncidentSite(self.root)
        digest = site.bind_photo("2BT23", INCIDENT_PHOTO)
        path, record = site.record_correction("2BT23")
        self.assertEqual(record["operator"], "owner")
        site.set_identity(
            "2BT23", source_sha256=digest, detected_tank="5BT43",
            requested_tank="2BT23", accepted_tank="2BT23",
            correction_sha256=record["correction_sha256"])
        site.flush()
        bundle = site.load()
        self.assertEqual(bundle.corrections_dir, (site.root / "corrections").resolve())
        self.assertTrue(Path(path).is_file())

    def test_manifest_guard_refuses_disagree_and_retry_conflict(self):
        """Post-review regression pin (L2 fixed by A4): ``build_manifest``
        refuses BOTH the identify-path ``DISAGREE`` and the retry-path
        ``RETRY_CONFLICT`` statuses before any manifest can be written, while a
        normal (agreeing) entry still builds — the defence-in-depth guard is no
        longer narrower than the process quarantine rules."""
        sandbox = StrictSandbox(self.root / "guard", [INCIDENT_PHOTO], {
            INCIDENT_SHA: {
                "catalogue": catalogue_output("2BT23", "2026-10-14"),
                "label": label_output("2BT23", "14/10/2026"),
                "preflight": preflight_output("2BT23", "2026-10-14"),
                "prepqa": prepqa_output(),
            }
        }, policy_mode="full")
        result = sandbox.run()
        self.assertEqual(result["status"], "COMPLETE")
        state = sandbox.state()
        entry = next(iter(state["fish"].values()))
        self.assertEqual(entry["status"], "VERIFIED")  # FISH_PASS
        original_reads = entry["label_reads"]
        for status in ("DISAGREE", "RETRY_CONFLICT"):
            entry["label_reads"] = {"status": status, "reasons": ["injected"]}
            with self.assertRaisesRegex(
                    incident_mod.betta_bau_adapters.StrictAdapterError,
                    "must never reach a manifest"):
                sandbox.adapters["build_manifest"](state, sandbox.batch_dir)
        entry["label_reads"] = original_reads
        built = sandbox.adapters["build_manifest"](state, sandbox.batch_dir)
        self.assertIn("manifest_sha256", built)


if __name__ == "__main__":
    unittest.main()
