import copy
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "betta_batch.py"
spec = importlib.util.spec_from_file_location("betta_batch", SCRIPT)
bb = importlib.util.module_from_spec(spec); spec.loader.exec_module(bb)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        assets = {}
        for role in ("source", "hero"):
            path = root / f"{role}.png"; path.write_bytes(role.encode())
            assets[role] = {"path": str(path), "sha256": hashlib.sha256(role.encode()).hexdigest()}
        assets["original"] = dict(assets["source"])
        protected = {k: f"before-{k}" for k in bb.PROTECTED}
        title = "4BT41 - Turquoise White Red Marble Halfmoon Male"
        self.item = {
            "id": "4BT41", "state": "MUTATION_PENDING",
            "history": [{"from": None, "to": "DISCOVERED", "at": bb.now()}],
            "source": assets["source"],
            "catalogue": {
                "tank_id": "4BT41",
                "photo_date": "2026-09-04",
                "fish_name": "Turquoise White Red Marble",
                "tail_type": "Halfmoon",
                "sex": "Male",
                "sex_confidence": 0.0,
                "title": title,
                "evidence": {"provider": "google", "model": "gemini", "call_id": "cat-1", "timestamp": bb.now(), "input_hashes": [assets["source"]["sha256"]], "output": {"tank_id": "4BT41"}},
            },
            "product": {"id": "gid://shopify/Product/1", "before": protected},
            "images": {"hero": assets["hero"]},
            "image_qa": {
                "deterministic": {k: "PASS" for k in bb.QA_DETERMINISTIC},
                "visual": {"provider": "google", "model": "gemini", "call_id": "qa-1", "timestamp": bb.now(),
                    "input_hashes": [assets["source"]["sha256"], assets["hero"]["sha256"], assets["source"]["sha256"]],
                    "output": {"verdict": "PASS"}, "assertions": {k: "PASS" for k in bb.QA_VISUAL}, "overall": "PASS"},
                "outcome": "PASS",
            },
            "mutation": {"title": title, "arrival_date": "2026-09-04", "inventory": 1,
                         "media": [assets["hero"]["sha256"], assets["source"]["sha256"]]},
        }
        self.ledger = {"schema_version": 2, "batch_id": "test", "batch_state": "PROCESSING", "items": [self.item]}

    def tearDown(self): self.tmp.cleanup()

    def retank(self, item, tank):
        item["id"] = tank
        item["catalogue"]["tank_id"] = tank
        item["catalogue"]["title"] = bb.expected_catalogue_title(item["catalogue"])
        item["mutation"]["title"] = item["catalogue"]["title"]

    def visual_item(self):
        item = copy.deepcopy(self.item)
        item["state"] = "VISUAL_ACCEPTED"
        return item

    def test_valid_mutation_pending(self): bb.validate_ledger(self.ledger)

    def test_title_contract_exact(self):
        self.assertEqual(
            bb.expected_catalogue_title(self.item["catalogue"]),
            "4BT41 - Turquoise White Red Marble Halfmoon Male",
        )

    def test_unknown_sex_defaults_male(self):
        cat = dict(self.item["catalogue"], sex=None, sex_confidence=0)
        self.assertEqual(bb.expected_catalogue_title(cat), "4BT41 - Turquoise White Red Marble Halfmoon Male")

    def test_low_confidence_female_defaults_male(self):
        cat = dict(self.item["catalogue"], sex="Female", sex_confidence=0.70)
        self.assertEqual(bb.expected_catalogue_title(cat), "4BT41 - Turquoise White Red Marble Halfmoon Male")

    def test_confident_female_is_female(self):
        cat = dict(self.item["catalogue"], sex="Female", sex_confidence=0.95)
        self.assertEqual(bb.expected_catalogue_title(cat), "4BT41 - Turquoise White Red Marble Halfmoon Female")

    def test_rejects_deviated_title(self):
        self.item["catalogue"]["title"] = "Turquoise Marble Betta HM"
        self.item["mutation"]["title"] = self.item["catalogue"]["title"]
        with self.assertRaises(bb.LedgerError): bb.validate_ledger(self.ledger)

    def test_rejects_missing_tail_type(self):
        self.item["catalogue"]["tail_type"] = ""
        with self.assertRaises(bb.LedgerError): bb.validate_ledger(self.ledger)

    def test_rejects_description_mutation(self):
        self.item["mutation"]["description"] = "changed"
        with self.assertRaises(bb.LedgerError): bb.validate_ledger(self.ledger)

    def test_rejects_fake_missing_call(self):
        self.item["image_qa"]["visual"]["call_id"] = ""
        with self.assertRaises(bb.LedgerError): bb.validate_ledger(self.ledger)

    def test_rejects_reused_call_id(self):
        self.item["image_qa"]["visual"]["call_id"] = "cat-1"
        with self.assertRaises(bb.LedgerError): bb.validate_ledger(self.ledger)

    def test_rejects_changed_file(self):
        Path(self.item["images"]["hero"]["path"]).write_bytes(b"tampered")
        with self.assertRaises(bb.LedgerError): bb.validate_ledger(self.ledger)

    def test_rejects_wrong_arrival_date(self):
        self.item["mutation"]["arrival_date"] = "2026-09-05"
        with self.assertRaises(bb.LedgerError): bb.validate_ledger(self.ledger)

    def test_rejects_derived_or_cropped_original(self):
        path = Path(self.tmp.name) / "cropped.png"; path.write_bytes(b"cropped")
        self.item["source"] = {"path": str(path), "sha256": hashlib.sha256(b"cropped").hexdigest()}
        with self.assertRaises(bb.LedgerError): bb.validate_ledger(self.ledger)

    def test_rejects_duplicate_shopify_product(self):
        duplicate = copy.deepcopy(self.item)
        self.retank(duplicate, "4BT42")
        duplicate["catalogue"]["evidence"]["call_id"] = "cat-2"
        duplicate["image_qa"]["visual"]["call_id"] = "qa-2"
        self.ledger["items"].append(duplicate)
        with self.assertRaises(bb.LedgerError): bb.validate_ledger(self.ledger)

    def test_parallel_preparation_schedules_both_missing_branches(self):
        item = self.visual_item()
        item.pop("product")
        item.pop("images")
        self.ledger["items"] = [item]
        plan = bb.parallel_preparation_plan(self.ledger, 4)
        self.assertEqual(
            {task["operation"] for task in plan["tasks"]},
            {"shopify_resolve", "grok_hero"},
        )
        self.assertEqual(plan["ready_to_join"], [])

    def test_parallel_preparation_resumes_only_missing_grok_branch(self):
        item = self.visual_item()
        item.pop("images")
        self.ledger["items"] = [item]
        plan = bb.parallel_preparation_plan(self.ledger, 4)
        self.assertEqual([task["operation"] for task in plan["tasks"]], ["grok_hero"])

    def test_parallel_preparation_resumes_only_missing_shopify_branch(self):
        item = self.visual_item()
        item.pop("product")
        self.ledger["items"] = [item]
        plan = bb.parallel_preparation_plan(self.ledger, 4)
        self.assertEqual([task["operation"] for task in plan["tasks"]], ["shopify_resolve"])

    def test_parallel_preparation_joins_only_when_both_outputs_valid(self):
        item = self.visual_item()
        self.ledger["items"] = [item]
        plan = bb.parallel_preparation_plan(self.ledger, 4)
        self.assertEqual(plan["tasks"], [])
        self.assertEqual(plan["ready_to_join"], ["4BT41"])

    def test_product_resolved_join_requires_hero_and_product(self):
        item = self.visual_item()
        item.pop("images")
        self.ledger["items"] = [item]
        with self.assertRaises(bb.LedgerError):
            bb.advance(self.ledger, "4BT41", "PRODUCT_RESOLVED")
        self.assertEqual(item["state"], "VISUAL_ACCEPTED")

        item["images"] = copy.deepcopy(self.item["images"])
        item.pop("product")
        with self.assertRaises(bb.LedgerError):
            bb.advance(self.ledger, "4BT41", "PRODUCT_RESOLVED")
        self.assertEqual(item["state"], "VISUAL_ACCEPTED")

    def test_execution_plan_exposes_parallel_prep_and_skips_serial_visual_wave(self):
        item = self.visual_item()
        item.pop("product")
        item.pop("images")
        self.ledger["items"] = [item]
        plan = bb.execution_plan(self.ledger, 9)
        self.assertEqual(plan["workers"], 4)
        self.assertEqual(plan["parallel_preparation"]["max_concurrency"], 4)
        self.assertEqual(len(plan["parallel_preparation"]["tasks"]), 2)
        self.assertFalse(any(wave["state"] == "VISUAL_ACCEPTED" for wave in plan["waves"]))

    def test_execution_plan_caps_workers(self):
        items = []
        for n in range(9):
            item = copy.deepcopy(self.item)
            self.retank(item, f"4BT{n}")
            item["product"]["id"] = f"gid://shopify/Product/{n}"
            item["catalogue"]["evidence"]["call_id"] = f"cat-{n}"
            item["image_qa"]["visual"]["call_id"] = f"qa-{n}"
            items.append(item)
        self.ledger["items"] = items
        bb.validate_ledger(self.ledger)
        plan = bb.execution_plan(self.ledger, 20)
        self.assertEqual(plan["workers"], 4)
        mutation_waves = [wave for wave in plan["waves"] if wave["state"] == "MUTATION_PENDING"]
        self.assertEqual([len(wave["items"]) for wave in mutation_waves], [4, 4, 1])

    def test_verified_requires_preserved_fields(self):
        item = copy.deepcopy(self.item); item["state"] = "VERIFIED"
        item["readback"] = dict(item["product"]["before"], product_id=item["product"]["id"],
            title=item["mutation"]["title"], arrival_date=item["mutation"]["arrival_date"], inventory=1, media_hashes=item["mutation"]["media"])
        bb.validate_item(item)
        item["readback"]["description"] = "changed"
        with self.assertRaises(bb.LedgerError): bb.validate_item(item)


if __name__ == "__main__": unittest.main()
