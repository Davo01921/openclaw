import copy
import contextlib
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "betta_shopify_batch.py"
SPEC = importlib.util.spec_from_file_location("betta_shopify_batch", SCRIPT)
bsb = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bsb
SPEC.loader.exec_module(bsb)

CORRECTIONS_SCRIPT = Path(__file__).parents[1] / "scripts" / "betta_corrections.py"
CORRECTIONS_SPEC = importlib.util.spec_from_file_location(
    "betta_corrections_for_uploader_tests", CORRECTIONS_SCRIPT)
corrections = importlib.util.module_from_spec(CORRECTIONS_SPEC)
sys.modules[CORRECTIONS_SPEC.name] = corrections
CORRECTIONS_SPEC.loader.exec_module(corrections)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return bsb.sha256_file(path)


class Fixture:
    def __init__(self, root: Path, count: int = 1, authorised: bool = False):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.count = count
        self.authorised = authorised
        self.tanks = [f"1BT{index + 1}" for index in range(count)]
        self.qa_paths = {}
        self.approval_items = []
        self.snapshot_records = []
        self.detail_items = []
        self.label_items = []
        self.authority_items = []
        self.manifest_items = []
        self._build_items()
        self.manifest_path = self._write_manifest()

    def _build_items(self):
        for index, tank in enumerate(self.tanks, 1):
            source = self.root / f"{tank}-source.png"
            hero = self.root / f"{tank}-hero.png"
            source.write_bytes(f"source-{tank}".encode())
            hero.write_bytes(f"hero-{tank}".encode())
            source_hash = bsb.sha256_file(source)
            hero_hash = bsb.sha256_file(hero)
            product_id = f"gid://shopify/Product/{100 + index}"
            variant_id = f"gid://shopify/ProductVariant/{200 + index}"
            inventory_id = f"gid://shopify/InventoryItem/{300 + index}"
            location_id = "gid://shopify/Location/401"
            old_media_id = f"gid://shopify/MediaImage/{500 + index}"
            existing_title = f"{tank} - Old Betta Male"
            approved_title = f"{tank} - Blue Red Halfmoon Male"
            source_reference = f"owner-confirmation:{tank}:{source_hash}"
            qa = {
                "call_id": f"qa-{index}",
                "provider": "mock",
                "model": "mock-vision",
                "timestamp": "2026-10-09T00:00:00+00:00",
                "input_hashes": [source_hash, hero_hash, source_hash],
                "output": {
                    "assertions": {
                        "same_identity": "PASS",
                        "body_anatomy": "PASS",
                        "scale_markings": "PASS",
                        "regional_colour": "PASS",
                        "tail_fins_pose": "PASS",
                        "complete_framing": "PASS",
                        "realistic_texture": "PASS",
                        "hero_composition": "PASS",
                        "label": "PASS",
                        "reference_integrity": "PASS",
                    },
                    "overall": "PASS",
                    "reasons": [],
                },
            }
            qa_path = self.root / f"{tank}-qa.json"
            qa_hash = write_json(qa_path, qa)
            self.qa_paths[tank] = qa_path
            self.approval_items.append({
                "tank_id": tank,
                "product_id": product_id,
                "variant_id": variant_id,
                "inventory_item_id": inventory_id,
                "existing_title": existing_title,
                "proposed_title": approved_title,
                "existing_arrival_date": "2026-08-01",
                "proposed_arrival_date": "2026-10-09",
                "existing_inventory": 0,
                "proposed_inventory": 1,
                "source_reference": source_reference,
                "hero_path": str(hero),
                "hero_sha256": hero_hash,
                "original_path": str(source),
                "original_sha256": source_hash,
                "retail_price_preserved": "35.00",
                "cost_preserved": "7.15",
            })
            description = f"<p>Protected {tank}</p>"
            self.snapshot_records.append({
                "tank_id": tank,
                "status": "PREFLIGHT_PASS",
                "inventory_location": {
                    "id": location_id,
                    "name": "Test Location",
                },
                "product": {
                    "id": product_id,
                    "title": existing_title,
                    "status": "ACTIVE",
                    "descriptionHtml": description,
                    "media": {
                        "pageInfo": {"hasNextPage": False},
                        "nodes": [{
                            "id": old_media_id,
                            "mediaContentType": "IMAGE",
                            "image": {"url": f"https://example.test/{tank}-old.png"},
                        }],
                    },
                    "variants": {
                        "pageInfo": {"hasNextPage": False},
                        "nodes": [{
                            "id": variant_id,
                            "price": "35.00",
                            "inventoryQuantity": 0,
                            "inventoryPolicy": "DENY",
                            "inventoryItem": {
                                "id": inventory_id,
                                "tracked": True,
                                "unitCost": {
                                    "amount": "7.15",
                                    "currencyCode": "AUD",
                                },
                                "inventoryLevels": {
                                    "pageInfo": {"hasNextPage": False},
                                    "nodes": [{
                                        "location": {
                                            "id": location_id,
                                            "name": "Test Location",
                                        },
                                        "quantities": [
                                            {"name": "available", "quantity": 0},
                                            {"name": "on_hand", "quantity": 0},
                                            {"name": "committed", "quantity": 0},
                                        ],
                                    }],
                                },
                            },
                        }],
                    },
                },
            })
            self.detail_items.append({
                "tank_id": tank,
                "product_id": product_id,
                "variant_id": variant_id,
                "inventory_item_id": inventory_id,
                "existing_title": existing_title,
                "product_status": "ACTIVE",
                "handle": tank.lower(),
                "vendor": "NTA Imports",
                "product_type": "Domesticated Betta",
                "retail_price": "35.00",
                "cost": "7.15",
                "existing_arrival_date": "2026-08-01",
                "inventory_quantity": 0,
            })
            self.label_items.append({
                "tank_id": tank,
                "source_path": str(source),
                "source_sha256": source_hash,
                "photo_date": "2026-10-09",
                "status": "RECONCILED",
            })
            self.authority_items.append({
                "tank_id": tank,
                "source_sha256": source_hash,
                "new_fish_authorised": True,
                "source_reference": source_reference,
                "intake_confirmed": True,
                "shopify_write_authorised": False,
            })
            self.manifest_items.append({
                "tank_id": tank,
                "product_id": product_id,
                "variant_id": variant_id,
                "inventory_item_id": inventory_id,
                "location_id": location_id,
                "approved_title": approved_title,
                "arrival_date": "2026-10-09",
                "quantity": 1,
                "inventory_reason": "received",
                "source_reference": source_reference,
                "hero": {
                    "path": str(hero),
                    "sha256": hero_hash,
                    "mime_type": "image/png",
                },
                "original": {
                    "path": str(source),
                    "sha256": source_hash,
                    "mime_type": "image/png",
                },
                "image_qa": {
                    "path": str(qa_path),
                    "sha256": qa_hash,
                    "exception": None,
                },
                "identity": {
                    "source_sha256": source_hash,
                    "detected_tank": tank,
                    "requested_tank": tank,
                    "accepted_tank": tank,
                    "correction_sha256": None,
                },
                "write_authorised": self.authorised,
            })

    def _write_manifest(self) -> Path:
        evidence_values = {
            "approval_plan": {"items": self.approval_items},
            "protected_snapshot": {"records": self.snapshot_records},
            "shopify_details": {"items": self.detail_items},
            "labels": {"items": self.label_items},
            "new_fish_authority": {"items": self.authority_items},
        }
        evidence = {}
        for name, value in evidence_values.items():
            path = self.root / f"{name}.json"
            evidence[name] = {
                "path": str(path),
                "sha256": write_json(path, value),
            }
        manifest = {
            "schema": bsb.MANIFEST_SCHEMA,
            "batch_id": "test-betta-batch",
            "shopify_write_authorised": self.authorised,
            "state_dir": str(self.root / "state"),
            "report_dir": str(self.root / "reports"),
            "corrections_dir": str(self.root / "corrections"),
            "evidence": evidence,
            "items": self.manifest_items,
        }
        path = self.root / "manifest.json"
        write_json(path, manifest)
        return path

    def rewrite_manifest(self):
        manifest = json.loads(self.manifest_path.read_text())
        manifest["items"] = self.manifest_items
        write_json(self.manifest_path, manifest)

    def install_correction(self, tank: str, **overrides):
        """Write one immutably-recorded owner correction and bind it in the manifest."""
        item = next(value for value in self.manifest_items if value["tank_id"] == tank)
        values = {
            "source_sha256": item["original"]["sha256"],
            "original_model_tank": "9BT9",
            "corrected_tank": tank,
            "product_id": item["product_id"],
            "variant_id": item["variant_id"],
            "operation": {
                "fields": list(bsb.IDENTITY_OPERATION_FIELDS),
                "mode": "owner-directed",
            },
            "reason": "owner corrected the vision tank reading",
            "evidence_reference": "test-evidence-reference",
            "operator": "owner",
            "directory": self.root / "corrections",
            "created_at": "2026-10-15T00:00:00+00:00",
        }
        values.update(overrides)
        path = corrections.record(**values)
        record = json.loads(path.read_text())
        item["identity"].update({
            "detected_tank": values["original_model_tank"],
            "correction_sha256": record["correction_sha256"],
        })
        self.rewrite_manifest()
        return path, record

    def add_completion(self, tank: str):
        item = next(value for value in self.manifest_items if value["tank_id"] == tank)
        media_ids = [
            "gid://shopify/MediaImage/9001",
            "gid://shopify/MediaImage/9002",
        ]
        media_alts = [
            f"{tank} - Approved xAI hero",
            f"{tank} - Untouched original photograph",
        ]
        receipts = {
            "attachment": {
                "status": "ATTACHMENT_REQUEST_ACCEPTED",
                "staged_hashes": [
                    {"role": "HERO", "sha256": item["hero"]["sha256"]},
                    {"role": "ORIGINAL", "sha256": item["original"]["sha256"]},
                ],
            },
            "reorder": {
                "status": "REORDER_REQUEST_ACCEPTED",
                "expected_after": media_ids,
            },
            "media": {
                "status": "FINAL_MEDIA_PASS",
                "remaining_media_ids": media_ids,
            },
            "details": {
                "status": "DETAILS_READBACK_PASS",
                "readback_title": item["approved_title"],
                "readback_arrival_date": item["arrival_date"],
            },
            "stock": {
                "status": "FINAL_SHOPIFY_READBACK_PASS",
                "product_id": item["product_id"],
                "inventory_item_id": item["inventory_item_id"],
                "location_id": item["location_id"],
                "final_available_quantity": 1,
            },
        }
        receipt_entries = []
        for role, value in receipts.items():
            path = self.root / f"{tank}-{role}.json"
            receipt_entries.append({
                "role": role,
                "path": str(path),
                "sha256": write_json(path, value),
            })
        item["completion_evidence"] = {
            "status": "FINAL_SHOPIFY_READBACK_PASS",
            "media_ids": media_ids,
            "media_alts": media_alts,
            "receipts": receipt_entries,
        }
        self.rewrite_manifest()
        return media_ids, media_alts


def live_for(ctx):
    return {
        "read_at": bsb.utc_now(),
        "source": "FRESH_SHOPIFY_READ",
        "product_id": ctx.product_id,
        "title": ctx.baseline["title"],
        "status": ctx.protected["status"],
        "description_html": ctx.protected["description_html"],
        "description_sha256": digest(ctx.protected["description_html"].encode()),
        "handle": ctx.protected["handle"],
        "vendor": ctx.protected["vendor"],
        "product_type": ctx.protected["product_type"],
        "arrival_date": ctx.baseline["arrival_date"],
        "arrival_date_type": "date",
        "media": [{
            "id": ctx.baseline["old_media_ids"][0],
            "alt": "old image",
            "status": "READY",
            "media_content_type": "IMAGE",
            "url": "https://example.test/old.png",
        }],
        "variant_id": ctx.variant_id,
        "price": ctx.protected["price"],
        "inventory_quantity": ctx.baseline["available"],
        "inventory_policy": "DENY",
        "inventory_item_id": ctx.inventory_item_id,
        "tracked": True,
        "cost": ctx.protected["cost"],
        "cost_currency": ctx.protected["cost_currency"],
        "location_id": ctx.location_id,
        "location_name": "Test Location",
        "available": ctx.baseline["available"],
        "on_hand": ctx.baseline["available"],
        "committed": 0,
    }


class FakeGateway:
    def __init__(self, contexts):
        self.live = {
            ctx.product_id: live_for(ctx)
            for ctx in contexts
        }
        self.writes = []
        self.reads = 0
        self.media_processing_reads = 0
        self.media_delay_reads = 0
        self.uncertain_operation = None
        self.uncertain_applies = False

    def read_product(self, product_id, location_id):
        self.reads += 1
        value = self.live[product_id]
        if self.media_processing_reads:
            self.media_processing_reads -= 1
            for media in value["media"]:
                if media["alt"] and media["alt"].startswith("NTA|"):
                    media["status"] = "PROCESSING"
        else:
            for media in value["media"]:
                if media["alt"] and media["alt"].startswith("NTA|"):
                    media["status"] = "READY"
        return copy.deepcopy(value)

    def write(self, operation, variables, approval):
        self.writes.append((operation, copy.deepcopy(variables)))
        if operation == self.uncertain_operation:
            if self.uncertain_applies:
                self._apply(operation, variables)
            raise bsb.UncertainWriteError("mock uncertain transport")
        return self._apply(operation, variables)

    def _apply(self, operation, variables):
        if operation == "betta_batch_stage_images":
            return {
                "stagedUploadsCreate": {
                    "stagedTargets": [
                        {
                            "url": "https://upload.test/hero",
                            "resourceUrl": "https://resource.test/hero",
                            "parameters": [{"name": "key", "value": "hero-secret"}],
                        },
                        {
                            "url": "https://upload.test/original",
                            "resourceUrl": "https://resource.test/original",
                            "parameters": [{"name": "key", "value": "original-secret"}],
                        },
                    ],
                    "userErrors": [],
                },
            }
        product_id = (
            variables.get("product", {}).get("id") or
            variables.get("id") or
            variables.get("productId")
        )
        if operation == "betta_batch_set_inventory":
            inventory_id = variables["input"]["quantities"][0]["inventoryItemId"]
            live = next(
                value for value in self.live.values()
                if value["inventory_item_id"] == inventory_id
            )
        else:
            live = self.live.get(product_id)
        if operation == "betta_batch_add_images":
            start = 7000 + len(live["media"])
            for offset, media in enumerate(variables["media"]):
                live["media"].append({
                    "id": f"gid://shopify/MediaImage/{start + offset}",
                    "alt": media["alt"],
                    "status": "PROCESSING" if self.media_delay_reads else "READY",
                    "media_content_type": "IMAGE",
                    "url": f"https://cdn.test/{start + offset}.png",
                })
            self.media_processing_reads = self.media_delay_reads
            return {"productUpdate": {"product": {"id": product_id}, "userErrors": []}}
        if operation == "betta_batch_reorder_media":
            order = [move["id"] for move in variables["moves"]]
            by_id = {value["id"]: value for value in live["media"]}
            remainder = [
                value for value in live["media"]
                if value["id"] not in order
            ]
            live["media"] = [by_id[value] for value in order] + remainder
            return {"productReorderMedia": {"job": {"id": "gid://shopify/Job/1"}, "mediaUserErrors": []}}
        if operation == "betta_batch_delete_media":
            deleting = set(variables["mediaIds"])
            live["media"] = [
                value for value in live["media"]
                if value["id"] not in deleting
            ]
            return {"productDeleteMedia": {"deletedMediaIds": list(deleting), "mediaUserErrors": []}}
        if operation == "betta_batch_update_details":
            live["title"] = variables["product"]["title"]
            live["arrival_date"] = variables["product"]["metafields"][0]["value"]
            return {"productUpdate": {"product": {"id": product_id}, "userErrors": []}}
        if operation == "betta_batch_set_inventory":
            quantity = variables["input"]["quantities"][0]
            if live["available"] != quantity["changeFromQuantity"]:
                return {"inventorySetQuantities": {"inventoryAdjustmentGroup": None, "userErrors": [{"message": "CAS mismatch"}]}}
            live["available"] = quantity["quantity"]
            live["on_hand"] = quantity["quantity"]
            live["inventory_quantity"] = quantity["quantity"]
            return {"inventorySetQuantities": {"inventoryAdjustmentGroup": {"changes": [{"name": "available", "delta": 1}]}, "userErrors": []}}
        raise AssertionError(f"unexpected operation {operation}")


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_manifest_validation(self):
        fixture = Fixture(self.root)
        bundle = bsb.ManifestBundle(fixture.manifest_path)
        self.assertEqual(["1BT1"], list(bundle.contexts))

    def test_duplicate_tank_and_product_detection(self):
        fixture = Fixture(self.root, count=2)
        fixture.manifest_items[1]["product_id"] = fixture.manifest_items[0]["product_id"]
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(bsb.ManifestError, "duplicate product_id"):
            bsb.ManifestBundle(fixture.manifest_path)

        fixture = Fixture(self.root / "tank", count=2)
        fixture.manifest_items[1]["tank_id"] = fixture.manifest_items[0]["tank_id"]
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(bsb.ManifestError, "duplicate tank_id"):
            bsb.ManifestBundle(fixture.manifest_path)

    def test_hash_mismatch(self):
        fixture = Fixture(self.root)
        Path(fixture.manifest_items[0]["original"]["path"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(bsb.ManifestError, "hash mismatch"):
            bsb.ManifestBundle(fixture.manifest_path)

    def test_failed_qa_requires_hash_bound_owner_exception(self):
        fixture = Fixture(self.root)
        tank = fixture.tanks[0]
        qa_path = fixture.qa_paths[tank]
        qa = json.loads(qa_path.read_text())
        qa["output"]["overall"] = "FAIL"
        qa["output"]["assertions"]["same_identity"] = "FAIL"
        qa["output"]["reasons"] = ["identity mismatch"]
        qa_hash = write_json(qa_path, qa)
        fixture.manifest_items[0]["image_qa"]["sha256"] = qa_hash
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(bsb.ManifestError, "owner exception"):
            bsb.ManifestBundle(fixture.manifest_path)
        fixture.manifest_items[0]["image_qa"]["exception"] = {
            "accepted": True,
            "accepted_by": "owner",
            "source_reference": "owner-instruction-2026-10-09",
            "qa_receipt_sha256": qa_hash,
            "failed_assertions": ["same_identity"],
            "original_reasons": ["identity mismatch"],
        }
        fixture.rewrite_manifest()
        self.assertEqual(
            "FAIL",
            bsb.ManifestBundle(fixture.manifest_path)
            .contexts[tank].qa["output"]["overall"],
        )

    def test_identity_block_is_required_for_every_item(self):
        fixture = Fixture(self.root)
        del fixture.manifest_items[0]["identity"]
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(bsb.ManifestError, "identity block required"):
            bsb.ManifestBundle(fixture.manifest_path)

    def test_identity_block_rejects_unknown_keys(self):
        fixture = Fixture(self.root)
        fixture.manifest_items[0]["identity"]["extra"] = "not-allowed"
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(bsb.ManifestError, "identity block must contain exactly"):
            bsb.ManifestBundle(fixture.manifest_path)

    def test_identity_source_hash_must_bind_the_camera_original(self):
        fixture = Fixture(self.root)
        fixture.manifest_items[0]["identity"]["source_sha256"] = "b" * 64
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(bsb.ManifestError, "identity source hash differs"):
            bsb.ManifestBundle(fixture.manifest_path)

    def test_identity_accepted_tank_must_equal_the_manifest_tank(self):
        fixture = Fixture(self.root)
        fixture.manifest_items[0]["identity"]["accepted_tank"] = "9BT9"
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(bsb.ManifestError, "accepted_tank must equal"):
            bsb.ManifestBundle(fixture.manifest_path)

    def test_identity_requested_tank_must_equal_item_tank_without_correction(self):
        fixture = Fixture(self.root)
        fixture.manifest_items[0]["identity"]["requested_tank"] = "9BT9"
        fixture.manifest_items[0]["identity"]["detected_tank"] = "9BT9"
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(bsb.ManifestError, "requested_tank must equal"):
            bsb.ManifestBundle(fixture.manifest_path)

    def test_detected_requested_mismatch_refused_without_correction(self):
        fixture = Fixture(self.root)
        fixture.manifest_items[0]["identity"]["detected_tank"] = "9BT9"
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(bsb.ManifestError, "without a correction record"):
            bsb.ManifestBundle(fixture.manifest_path)

    def test_valid_correction_allows_detected_requested_mismatch(self):
        fixture = Fixture(self.root)
        _, record = fixture.install_correction("1BT1")
        bundle = bsb.ManifestBundle(fixture.manifest_path)
        identity = bundle.contexts["1BT1"].raw["identity"]
        self.assertEqual("9BT9", identity["detected_tank"])
        self.assertEqual(record["correction_sha256"], identity["correction_sha256"])

    def test_correction_for_wrong_product_refused(self):
        fixture = Fixture(self.root)
        fixture.install_correction(
            "1BT1", product_id="gid://shopify/Product/999")
        with self.assertRaisesRegex(bsb.ManifestError, "product_id_mismatch"):
            bsb.ManifestBundle(fixture.manifest_path)

    def test_correction_for_wrong_source_refused(self):
        fixture = Fixture(self.root)
        fixture.install_correction("1BT1", source_sha256="c" * 64)
        with self.assertRaisesRegex(bsb.ManifestError, "source_sha256_mismatch"):
            bsb.ManifestBundle(fixture.manifest_path)

    def test_correction_for_wrong_variant_refused(self):
        fixture = Fixture(self.root)
        fixture.install_correction(
            "1BT1", variant_id="gid://shopify/ProductVariant/999")
        with self.assertRaisesRegex(bsb.ManifestError, "variant_id_mismatch"):
            bsb.ManifestBundle(fixture.manifest_path)

    def test_correction_scope_must_cover_betta_operations(self):
        fixture = Fixture(self.root)
        fixture.install_correction(
            "1BT1", operation={"fields": ["retail", "cost", "vendor"],
                               "mode": "owner-directed"})
        with self.assertRaisesRegex(bsb.ManifestError, "operation_scope_mismatch"):
            bsb.ManifestBundle(fixture.manifest_path)

    def test_missing_correction_record_refused(self):
        fixture = Fixture(self.root)
        fixture.manifest_items[0]["identity"]["detected_tank"] = "9BT9"
        fixture.manifest_items[0]["identity"]["correction_sha256"] = "d" * 64
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(bsb.ManifestError, "record_unavailable"):
            bsb.ManifestBundle(fixture.manifest_path)

    def test_tampered_correction_record_refused(self):
        fixture = Fixture(self.root)
        path, _ = fixture.install_correction("1BT1")
        path.chmod(0o600)
        record = json.loads(path.read_text())
        record["corrected_tank"] = "9BT9"
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(bsb.ManifestError, "self_hash_mismatch"):
            bsb.ManifestBundle(fixture.manifest_path)

    def test_invalid_correction_hash_format_refused(self):
        fixture = Fixture(self.root)
        fixture.manifest_items[0]["identity"]["detected_tank"] = "9BT9"
        fixture.manifest_items[0]["identity"]["correction_sha256"] = "NOT-HEX"
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(bsb.ManifestError, "lowercase SHA-256"):
            bsb.ManifestBundle(fixture.manifest_path)


class UploaderTests(unittest.TestCase):
    def test_root_help_lists_all_commands(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                bsb.main(["--help"])
        self.assertEqual(0, raised.exception.code)
        commands = (
            "preflight", "dry-run", "execute", "status", "resume", "verify",
        )
        for command in commands:
            self.assertIn(command, output.getvalue())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def build(self, count=1, authorised=False):
        fixture = Fixture(self.root, count=count, authorised=authorised)
        bundle = bsb.ManifestBundle(fixture.manifest_path)
        contexts = bundle.select()
        gateway = FakeGateway(contexts)
        state = bsb.StateStore(bundle)
        uploader = bsb.BatchUploader(
            bundle, gateway, state,
            sleep=lambda _: None,
            upload=lambda target, asset: None,
            poll_attempts=5,
            poll_interval=0,
        )
        return fixture, bundle, contexts, gateway, state, uploader

    def test_shopify_identity_mismatch_blocks(self):
        _, _, contexts, gateway, state, uploader = self.build()
        gateway.live[contexts[0].product_id]["variant_id"] = "gid://shopify/ProductVariant/999"
        report = uploader.dry_run(contexts)
        self.assertEqual(1, report["blocked_count"])
        self.assertEqual("BLOCKED", state.item("1BT1")["stage"])

    def test_stock_change_during_processing_stops_cas(self):
        _, _, contexts, gateway, state, uploader = self.build(authorised=True)
        ctx = contexts[0]
        uploader.preflight_one(ctx)
        state.transition(ctx.tank_id, "DETAILS_UPDATED")
        gateway.live[ctx.product_id]["available"] = 1
        gateway.live[ctx.product_id]["inventory_quantity"] = 1
        with self.assertRaisesRegex(bsb.BatchError, "stock changed before uploader CAS"):
            uploader._set_inventory(ctx)
        self.assertNotIn(
            "betta_batch_set_inventory",
            [operation for operation, _ in gateway.writes],
        )
        gateway.live[ctx.product_id]["available"] = 0
        gateway.live[ctx.product_id]["inventory_quantity"] = 2
        with self.assertRaisesRegex(bsb.BatchError, "aggregate stock changed"):
            uploader._set_inventory(ctx)
        self.assertNotIn(
            "betta_batch_set_inventory",
            [operation for operation, _ in gateway.writes],
        )

    def test_changed_baseline_after_preflight_blocks_before_write(self):
        _, _, contexts, gateway, state, uploader = self.build(authorised=True)
        ctx = contexts[0]
        uploader.preflight_one(ctx)
        gateway.live[ctx.product_id]["title"] = "Externally changed title"
        report = uploader.execute([ctx])
        self.assertEqual(1, report["blocked_count"])
        self.assertEqual([], gateway.writes)
        self.assertEqual("BLOCKED", state.item(ctx.tank_id)["stage"])

    def test_attachment_recovery_avoids_duplicate_media(self):
        _, _, contexts, gateway, state, uploader = self.build(authorised=True)
        ctx = contexts[0]
        uploader.preflight_one(ctx)
        state.transition(ctx.tank_id, "STAGED")
        gateway.live[ctx.product_id]["media"].extend([
            {
                "id": "gid://shopify/MediaImage/8301",
                "alt": ctx.expected_alt("hero"),
                "status": "READY",
                "media_content_type": "IMAGE",
                "url": "https://cdn.test/hero.png",
            },
            {
                "id": "gid://shopify/MediaImage/8302",
                "alt": ctx.expected_alt("original"),
                "status": "READY",
                "media_content_type": "IMAGE",
                "url": "https://cdn.test/original.png",
            },
        ])
        uploader._attach_media(ctx)
        self.assertEqual([], gateway.writes)
        self.assertEqual(
            "MEDIA_ATTACH_REQUESTED", state.item(ctx.tank_id)["stage"],
        )

    def test_accepted_inventory_crash_reconciles_without_rewrite(self):
        _, _, contexts, gateway, state, uploader = self.build(authorised=True)
        ctx = contexts[0]
        uploader.preflight_one(ctx)
        state.transition(ctx.tank_id, "DETAILS_UPDATED")
        key = str(__import__("uuid").uuid4())
        state.set_fields(
            ctx.tank_id, "test_inventory_key",
            inventory_idempotency_key=key,
        )
        variables = {
            "input": {
                "name": "available",
                "reason": "received",
                "referenceDocumentUri": "gid://nta-betta/Batch/test/1BT1/x",
                "quantities": [{
                    "inventoryItemId": ctx.inventory_item_id,
                    "locationId": ctx.location_id,
                    "quantity": 1,
                    "changeFromQuantity": 0,
                }],
            },
            "idempotencyKey": key,
        }
        state.record_intent(
            ctx.tank_id, "betta_batch_set_inventory", variables,
            {"idempotency_key": key, "change_from_quantity": 0},
        )
        state.complete_intent(ctx.tank_id, "ACCEPTED")
        gateway.live[ctx.product_id]["available"] = 1
        gateway.live[ctx.product_id]["inventory_quantity"] = 1
        uploader._set_inventory(ctx)
        self.assertEqual([], gateway.writes)
        self.assertEqual(
            "INVENTORY_UPDATED", state.item(ctx.tank_id)["stage"],
        )

    def test_media_processing_delay_is_polled(self):
        _, _, contexts, gateway, state, uploader = self.build()
        ctx = contexts[0]
        uploader.preflight_one(ctx)
        gateway.live[ctx.product_id]["media"].extend([
            {
                "id": "gid://shopify/MediaImage/8001",
                "alt": ctx.expected_alt("hero"),
                "status": "PROCESSING",
                "media_content_type": "IMAGE",
                "url": "https://cdn.test/hero.png",
            },
            {
                "id": "gid://shopify/MediaImage/8002",
                "alt": ctx.expected_alt("original"),
                "status": "PROCESSING",
                "media_content_type": "IMAGE",
                "url": "https://cdn.test/original.png",
            },
        ])
        gateway.media_processing_reads = 2
        uploader._poll_media_ready(ctx)
        self.assertEqual("MEDIA_READY", state.item(ctx.tank_id)["stage"])
        self.assertGreaterEqual(
            state.item(ctx.tank_id)["telemetry"]["media_poll_reads"], 3
        )

    def test_duplicate_media_is_rejected(self):
        _, _, contexts, gateway, _, uploader = self.build()
        ctx = contexts[0]
        live = gateway.live[ctx.product_id]
        duplicate = {
            "id": "gid://shopify/MediaImage/8100",
            "alt": ctx.expected_alt("hero"),
            "status": "READY",
            "media_content_type": "IMAGE",
            "url": "https://cdn.test/duplicate.png",
        }
        live["media"].extend([
            duplicate,
            {**duplicate, "id": "gid://shopify/MediaImage/8101"},
            {
                **duplicate,
                "id": "gid://shopify/MediaImage/8102",
                "alt": ctx.expected_alt("original"),
            },
        ])
        with self.assertRaisesRegex(bsb.BatchError, "duplicate uploaded hero"):
            uploader._tagged_media(ctx, live)

    def test_interrupted_upload_resumes_only_missing_transfer(self):
        _, _, contexts, gateway, state, uploader = self.build(authorised=True)
        ctx = contexts[0]
        uploader.preflight_one(ctx)
        calls = []

        def interrupted(target, asset):
            role = "hero" if "hero" in Path(asset["path"]).name else "original"
            calls.append(role)
            if role == "original":
                raise bsb.DeferredError("mock interrupted transfer")

        uploader.upload = interrupted
        with self.assertRaises(bsb.DeferredError):
            uploader._allocate_and_transfer(ctx)
        self.assertEqual(["hero"], state.item(ctx.tank_id)["staged_transfers"])
        self.assertEqual("original", state.item(ctx.tank_id)["pending_transfer"]["role"])
        result = uploader.reconcile_pending(ctx, resolve_not_applied=True)
        self.assertEqual("OPERATOR_CONFIRMED_TRANSFER_NOT_APPLIED", result["status"])

        resumed = []
        uploader.upload = lambda target, asset: resumed.append(
            "hero" if "hero" in Path(asset["path"]).name else "original"
        )
        uploader._allocate_and_transfer(ctx)
        self.assertEqual(["original"], resumed)
        self.assertEqual("STAGED", state.item(ctx.tank_id)["stage"])

    def test_uncertain_mutation_reconciles_without_replay(self):
        _, _, contexts, gateway, state, uploader = self.build(authorised=True)
        ctx = contexts[0]
        uploader.preflight_one(ctx)
        variables = {
            "input": {
                "name": "available",
                "reason": "received",
                "referenceDocumentUri": "gid://nta-betta/Batch/test/1BT1/x",
                "quantities": [{
                    "inventoryItemId": ctx.inventory_item_id,
                    "locationId": ctx.location_id,
                    "quantity": 1,
                    "changeFromQuantity": 0,
                }],
            },
            "idempotencyKey": str(__import__("uuid").uuid4()),
        }
        state.record_intent(ctx.tank_id, "betta_batch_set_inventory", variables)
        state.mark_uncertain(ctx.tank_id, "mock transport")
        gateway.live[ctx.product_id]["available"] = 1
        gateway.live[ctx.product_id]["inventory_quantity"] = 1
        writes_before = len(gateway.writes)
        result = uploader.reconcile_pending(ctx)
        self.assertEqual("RECONCILED_APPLIED", result["status"])
        self.assertEqual(writes_before, len(gateway.writes))
        self.assertEqual("INVENTORY_UPDATED", state.item(ctx.tank_id)["stage"])

    def test_incorrect_image_order_fails_verification(self):
        _, _, contexts, gateway, state, uploader = self.build()
        ctx = contexts[0]
        uploader.preflight_one(ctx)
        uploaded = {
            "hero": {
                "id": "gid://shopify/MediaImage/8201",
                "alt": ctx.expected_alt("hero"),
                "status": "READY",
            },
            "original": {
                "id": "gid://shopify/MediaImage/8202",
                "alt": ctx.expected_alt("original"),
                "status": "READY",
            },
        }
        state.set_fields(ctx.tank_id, "test_uploaded", uploaded_media=uploaded)
        live = gateway.live[ctx.product_id]
        live["title"] = ctx.title
        live["arrival_date"] = ctx.arrival_date
        live["available"] = live["inventory_quantity"] = 1
        live["media"] = [
            {
                **uploaded["original"],
                "media_content_type": "IMAGE",
                "url": "https://cdn.test/original.png",
            },
            {
                **uploaded["hero"],
                "media_content_type": "IMAGE",
                "url": "https://cdn.test/hero.png",
            },
        ]
        assertions = bsb.final_assertions(ctx, live, state.item(ctx.tank_id))
        self.assertEqual("FAIL", assertions["media_order"]["status"])

    def test_protected_field_change_blocks(self):
        _, _, contexts, gateway, _, uploader = self.build()
        ctx = contexts[0]
        gateway.live[ctx.product_id]["price"] = "99.00"
        report = uploader.dry_run(contexts)
        self.assertEqual(1, report["blocked_count"])
        self.assertIn("protected price changed", report["items"][0]["error"])

    def test_partial_batch_failure_does_not_stop_other_product(self):
        _, _, contexts, gateway, state, uploader = self.build(count=2)
        gateway.live[contexts[1].product_id]["location_id"] = "gid://shopify/Location/999"
        report = uploader.dry_run(contexts)
        self.assertEqual(1, report["blocked_count"])
        self.assertEqual("PREFLIGHTED", state.item(contexts[0].tank_id)["stage"])
        self.assertEqual("BLOCKED", state.item(contexts[1].tank_id)["stage"])

    def test_completed_product_is_verified_and_skipped(self):
        fixture = Fixture(self.root)
        media_ids, media_alts = fixture.add_completion("1BT1")
        bundle = bsb.ManifestBundle(fixture.manifest_path)
        ctx = bundle.contexts["1BT1"]
        gateway = FakeGateway([ctx])
        live = gateway.live[ctx.product_id]
        live.update({
            "title": ctx.title,
            "arrival_date": ctx.arrival_date,
            "available": 1,
            "on_hand": 1,
            "inventory_quantity": 1,
            "media": [
                {
                    "id": media_ids[0],
                    "alt": media_alts[0],
                    "status": "READY",
                    "media_content_type": "IMAGE",
                    "url": "https://cdn.test/hero.png",
                },
                {
                    "id": media_ids[1],
                    "alt": media_alts[1],
                    "status": "READY",
                    "media_content_type": "IMAGE",
                    "url": "https://cdn.test/original.png",
                },
            ],
        })
        state = bsb.StateStore(bundle)
        uploader = bsb.BatchUploader(bundle, gateway, state, sleep=lambda _: None)
        report = uploader.dry_run([ctx])
        self.assertEqual(1, report["completed_verified_count"])
        self.assertEqual([], gateway.writes)
        self.assertEqual("COMPLETED_VERIFIED", state.item("1BT1")["stage"])

    def test_inventory_uses_persisted_idempotency_and_cas(self):
        _, _, contexts, gateway, state, uploader = self.build(authorised=True)
        ctx = contexts[0]
        uploader.preflight_one(ctx)
        state.transition(ctx.tank_id, "DETAILS_UPDATED")
        uploader._set_inventory(ctx)
        operation, variables = gateway.writes[-1]
        self.assertEqual("betta_batch_set_inventory", operation)
        self.assertEqual(
            0,
            variables["input"]["quantities"][0]["changeFromQuantity"],
        )
        self.assertEqual(
            state.item(ctx.tank_id)["inventory_idempotency_key"],
            variables["idempotencyKey"],
        )
        self.assertEqual("INVENTORY_UPDATED", state.item(ctx.tank_id)["stage"])

    def test_full_mocked_write_path(self):
        _, _, contexts, gateway, state, uploader = self.build(authorised=True)
        report = uploader.execute(contexts)
        self.assertEqual(1, report["verified_count"])
        self.assertEqual(0, report["blocked_count"])
        self.assertEqual("VERIFIED", state.item("1BT1")["stage"])
        self.assertEqual([
            "betta_batch_stage_images",
            "betta_batch_add_images",
            "betta_batch_reorder_media",
            "betta_batch_delete_media",
            "betta_batch_update_details",
            "betta_batch_set_inventory",
        ], [operation for operation, _ in gateway.writes])
        receipt = Path(state.item("1BT1")["final_receipt"])
        self.assertTrue(receipt.is_file())
        self.assertEqual(
            "FINAL_SHOPIFY_READBACK_PASS",
            json.loads(receipt.read_text())["status"],
        )

    def test_corrected_item_completes_full_mocked_write_path(self):
        fixture = Fixture(self.root, authorised=True)
        fixture.install_correction("1BT1")
        bundle = bsb.ManifestBundle(fixture.manifest_path)
        contexts = bundle.select()
        gateway = FakeGateway(contexts)
        state = bsb.StateStore(bundle)
        uploader = bsb.BatchUploader(
            bundle, gateway, state,
            sleep=lambda _: None,
            upload=lambda target, asset: None,
            poll_attempts=5,
            poll_interval=0,
        )
        report = uploader.execute(contexts)
        self.assertEqual(1, report["verified_count"])
        self.assertEqual(0, report["blocked_count"])
        self.assertEqual("VERIFIED", state.item("1BT1")["stage"])

    def test_execute_and_resume_refuse_unbound_identity_before_any_state(self):
        fixture = Fixture(self.root, authorised=True)
        del fixture.manifest_items[0]["identity"]["detected_tank"]
        fixture.rewrite_manifest()
        for command in ("execute", "resume"):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = bsb.main([
                    command,
                    "--manifest", str(fixture.manifest_path),
                    "--bridge", str(self.root / "bridge.mjs"),
                ])
            self.assertEqual(2, code)
            self.assertIn("identity block", stderr.getvalue())
        self.assertFalse((fixture.root / "state").exists())
        self.assertFalse((fixture.root / "reports").exists())


if __name__ == "__main__":
    unittest.main()
