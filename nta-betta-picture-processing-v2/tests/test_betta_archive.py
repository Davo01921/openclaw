"""Offline tests for the verified Betta archive command.

Synthetic trees, temporary directories and no network. The real batch is never
touched.
"""

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "betta_archive.py"
spec = importlib.util.spec_from_file_location("betta_archive", SCRIPT)
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return sha(data)


def readback_pass(assertions=None):
    return {"status": ar.READBACK_PASS, "assertions": assertions or {}}


class ArchiveTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.active = self.root / "active"
        self.archive_root = self.root / "Archived Bettas"
        self.items = []
        self.reports = []

    def tearDown(self):
        self.tmp.cleanup()

    def add_item(self, tank, *, verify_status=ar.READBACK_PASS, failed=(), qa_exception=None):
        original = self.active / f"dji_{tank}.png"
        hero = self.active / f"{tank}.png"
        qa_path = self.active / f"betta-{tank}-independent-qa.json"
        write(original, f"orig-{tank}".encode())
        write(hero, f"hero-{tank}".encode())
        qa = {"accepted": bool(qa_exception), "accepted_by": "owner",
              "source_reference": "owner-instruction", "failed_assertions": list(qa_exception or [])}
        write(qa_path, json.dumps(qa).encode())
        self.items.append({
            "tank_id": tank,
            "original": {"path": str(original), "sha256": sha(f"orig-{tank}".encode())},
            "hero": {"path": str(hero), "sha256": sha(f"hero-{tank}".encode())},
            "image_qa": {"path": str(qa_path), "exception": qa if qa_exception else None},
        })
        self.reports.append({
            "tank_id": tank,
            "status": verify_status,
            "assertions": {name: {"status": "FAIL"} for name in failed},
        })

    def write_inputs(self, write_verify=True):
        manifest = {"schema": "nta-betta-shopify-batch-v1", "batch_id": "test-batch", "items": self.items}
        self.manifest_path = self.active / "manifest.json"
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.report_paths = []
        self.verify_path = self.active / "verify.json"
        if write_verify:
            self.verify_path.write_text(json.dumps({"items": self.reports}), encoding="utf-8")
            self.report_paths.append(self.verify_path)
        self.csv_path = self.active / "betta-inventory.csv"
        self.csv_path.write_text("Tank Number,Proposed Title,Cost,Retail Price\n", encoding="utf-8")
        return manifest

    def plan(self, **kwargs):
        return ar.build_plan(
            manifest_path=self.manifest_path,
            report_paths=self.report_paths,
            inventory_csv=self.csv_path,
            archive_root=self.archive_root,
            date="2026-10-10",
            **kwargs,
        )


class PlanTests(ArchiveTestCase):
    def test_configured_uploader_receipt_directory_is_archived(self):
        self.add_item("1BT11")
        self.write_inputs()
        state_root = self.active / "shopify-state"
        receipt = state_root / "receipts" / "1BT11-final.json"
        receipt.parent.mkdir(parents=True)
        receipt.write_text('{"status":"FINAL_SHOPIFY_READBACK_PASS"}\n', encoding="utf-8")
        plan = self.plan(state_root=state_root)
        matches = [
            entry for entry in plan["files"]
            if entry["role"] == "audit" and entry["source"] == str(receipt)
        ]
        self.assertEqual(len(matches), 1)

    def test_generic_audit_input_is_hash_locked_without_json_parsing(self):
        self.add_item("1BT11")
        self.write_inputs()
        telemetry = self.active / "betta-call-telemetry.csv"
        telemetry.write_text("stage,outcome\ncatalogue,OK\n", encoding="utf-8")
        plan = self.plan(audit_paths=[telemetry])
        self.assertFalse(plan["blocked"])
        self.assertEqual(plan["audit_inputs"], [{
            "path": str(telemetry), "sha256": ar.sha256_file(telemetry),
        }])
        audit = [
            entry for entry in plan["files"]
            if entry["role"] == "audit" and entry["source"] == str(telemetry)
        ]
        self.assertEqual(len(audit), 1)

    def test_plan_builds_destinations_and_date(self):
        self.add_item("1BT11")
        self.write_inputs()
        plan = self.plan()
        self.assertFalse(plan["blocked"])
        self.assertEqual(plan["archive_date"], "2026-10-10")
        originals = [f for f in plan["files"] if f["role"] == "original"]
        heroes = [f for f in plan["files"] if f["role"] == "hero"]
        self.assertEqual(originals[0]["destination"],
                         str(self.archive_root / "2026-10-10" / "Betta Processing" / "1BT11 Original 2026-10-10.png"))
        self.assertEqual(heroes[0]["destination"],
                         str(self.archive_root / "2026-10-10" / "Betta Processed" / "1BT11.png"))
        csvs = [f for f in plan["files"] if f["role"] == "inventory_csv"]
        self.assertEqual(csvs[0]["destination"],
                         str(self.archive_root / "2026-10-10" / "Betta Processing" / "betta-inventory.csv"))

    def test_plan_blocks_without_readback_pass(self):
        self.add_item("1BT11", verify_status="FINAL_SHOPIFY_READBACK_FAIL")
        self.write_inputs()
        plan = self.plan()
        self.assertTrue(plan["blocked"])
        self.assertEqual(plan["counts"]["needs_review"], 1)

    def test_plan_blocks_on_unresolved_failure(self):
        self.add_item("1BT11", failed=["media_identity"])
        self.write_inputs()
        plan = self.plan()
        self.assertTrue(plan["blocked"])
        self.assertEqual(plan["fish"][0]["unresolved_assertions"], ["media_identity"])

    def test_owner_exception_is_preserved_not_promoted(self):
        self.add_item("1BT11", failed=["same_identity"], qa_exception=["same_identity"])
        self.write_inputs()
        plan = self.plan()
        self.assertFalse(plan["blocked"])
        self.assertEqual(plan["fish"][0]["state"], ar.PASS_WITH_EXCEPTION)
        self.assertNotEqual(plan["fish"][0]["state"], ar.VERIFIED)

    def test_external_exception_file_resolves_failure(self):
        self.add_item("1BT11", failed=["media_identity"])
        self.write_inputs()
        exceptions = self.active / "exceptions.json"
        exceptions.write_text(json.dumps({"exceptions": [{
            "tank_id": "1BT11", "assertions": ["media_identity"],
            "accepted_by": "owner", "source_reference": "owner-note", "reason": "alt label only",
        }]}), encoding="utf-8")
        plan = self.plan(exceptions_path=exceptions)
        self.assertFalse(plan["blocked"])
        self.assertEqual(plan["fish"][0]["state"], ar.PASS_WITH_EXCEPTION)
        self.assertEqual(plan["fish"][0]["accepted_assertions"], ["media_identity"])

    def test_missing_source_blocks(self):
        self.add_item("1BT11")
        self.write_inputs()
        Path(self.items[0]["original"]["path"]).unlink()
        plan = self.plan()
        self.assertTrue(plan["blocked"])
        self.assertTrue(any("missing" in b["reason"] for b in plan["blockers"]))

    def test_conflicting_destination_isolates_batch(self):
        self.add_item("1BT11")
        self.write_inputs()
        destination = self.archive_root / "2026-10-10" / "Betta Processed" / "1BT11.png"
        write(destination, b"different-existing-hero")
        plan = self.plan()
        # A collision is isolated under the batch id rather than blocking or overwriting.
        self.assertFalse(plan["blocked"])
        self.assertTrue(plan["isolated"])
        hero = [f for f in plan["files"] if f["role"] == "hero"][0]
        self.assertIn("test-batch", hero["destination"])
        self.assertFalse(hero["conflict"])
        self.assertEqual(readback_existing(destination), b"different-existing-hero")


def readback_existing(path: Path) -> bytes:
    return path.read_bytes()


class ExecuteTests(ArchiveTestCase):
    def test_execute_sha_verifies_generic_audit_input(self):
        self.add_item("1BT11")
        self.write_inputs()
        authority = self.active / "authority.json"
        authority.write_text('{"authorised":true}\n', encoding="utf-8")
        plan = self.plan(audit_paths=[authority])
        result = ar.execute_plan(plan, apply=True)
        record = next(
            entry for entry in result["results"]
            if entry["source"] == str(authority)
        )
        self.assertEqual(record["source_sha256"], record["destination_sha256"])
        self.assertTrue(Path(record["destination"]).is_file())
        manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["audit_inputs"][0]["sha256"], ar.sha256_file(authority))

    def test_dry_run_does_not_move(self):
        self.add_item("1BT11")
        self.write_inputs()
        plan = self.plan()
        result = ar.execute_plan(plan, apply=False)
        self.assertTrue(all(r["status"] == "PLANNED" for r in result["results"]))
        self.assertTrue(Path(self.items[0]["original"]["path"]).is_file())
        self.assertFalse((self.archive_root / "2026-10-10" / "Betta Processing").exists())

    def test_execute_moves_and_writes_manifest(self):
        self.add_item("1BT11")
        self.write_inputs()
        plan = self.plan()
        result = ar.execute_plan(plan, apply=True)
        self.assertEqual(result["batch_status"], "COMPLETE")
        original = Path(self.items[0]["original"]["path"])
        hero = Path(self.items[0]["hero"]["path"])
        dest_original = self.archive_root / "2026-10-10" / "Betta Processing" / "1BT11 Original 2026-10-10.png"
        dest_hero = self.archive_root / "2026-10-10" / "Betta Processed" / "1BT11.png"
        self.assertFalse(original.exists())
        self.assertFalse(hero.exists())
        self.assertEqual(ar.sha256_file(dest_original), sha(b"orig-1BT11"))
        self.assertEqual(ar.sha256_file(dest_hero), sha(b"hero-1BT11"))
        manifest_path = self.archive_root / "2026-10-10" / "test-batch-archive-manifest.json"
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest["schema"], ar.MANIFEST_SCHEMA)
        self.assertTrue(all(f["destination_sha256"] for f in manifest["files"]))

    def test_execute_refuses_conflicting_destination(self):
        self.add_item("1BT11")
        self.write_inputs()
        plan = self.plan()
        destination = self.archive_root / "2026-10-10" / "Betta Processed" / "1BT11.png"
        write(destination, b"appeared-after-planning")
        with self.assertRaises(ar.ArchiveError):
            ar.execute_plan(plan, apply=True)
        self.assertEqual(destination.read_bytes(), b"appeared-after-planning")

    def test_resume_is_idempotent(self):
        self.add_item("1BT11")
        self.write_inputs()
        plan = self.plan()
        first = ar.execute_plan(plan, apply=True)
        second = ar.execute_plan(self.plan(), apply=True)
        self.assertEqual(first["batch_status"], "COMPLETE")
        self.assertEqual(second["batch_status"], "COMPLETE")
        statuses = {r["status"] for r in second["results"]}
        self.assertTrue(statuses <= {"ALREADY_DONE", "COPIED"})

    def test_never_deletes_unrelated_files(self):
        self.add_item("1BT11")
        self.write_inputs()
        unrelated = self.active / "keep-me.txt"
        unrelated.write_text("unrelated", encoding="utf-8")
        unrelated_state = self.active / ".betta-shopify-state" / "secrets" / "token.json"
        unrelated_state.parent.mkdir(parents=True, exist_ok=True)
        unrelated_state.write_text("secret", encoding="utf-8")
        plan = self.plan()
        ar.execute_plan(plan, apply=True)
        self.assertTrue(unrelated.is_file())
        self.assertTrue(unrelated_state.is_file())

    def test_manifest_is_immutable(self):
        path = self.archive_root / "2026-10-10" / "archive-manifest.json"
        ar.write_manifest_immutable(path, {"a": 1})
        ar.write_manifest_immutable(path, {"a": 1})  # identical is fine
        with self.assertRaises(ar.ArchiveError):
            ar.write_manifest_immutable(path, {"a": 2})

    def test_status_reports_state(self):
        self.add_item("1BT11")
        self.write_inputs()
        plan = self.plan()
        ar.execute_plan(plan, apply=True)
        status = ar.report_status(self.archive_root, "2026-10-10")
        self.assertEqual(status["count"], 1)
        self.assertEqual(status["batches"][0]["source"], "manifest")
        self.assertEqual(status["batches"][0]["batch_status"], "COMPLETE")

    def test_blocked_plan_refuses_execute(self):
        self.add_item("1BT11", failed=["media_identity"])
        self.write_inputs()
        plan = self.plan()
        with self.assertRaises(ar.ArchiveError):
            ar.execute_plan(plan, apply=True)


if __name__ == "__main__":
    unittest.main()

