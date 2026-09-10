import sqlite3
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from gumtree_registry import initialize_registry  # noqa: E402


def make_registry(tmp_path):
    return initialize_registry(tmp_path / "gumtree.db")


def base_product(**overrides):
    data = {
        "shopify_product_id": "123",
        "shopify_gid": "gid://shopify/Product/123",
        "title": "Red Cherry Shrimp",
        "handle": "red-cherry-shrimp",
        "product_type": "Shrimp",
        "status": "ACTIVE",
        "management_state": "MANAGED",
        "config_state": "CONFIGURED",
        "policy": "WHEN_IN_STOCK",
        "priority": "HIGH",
        "availability_status": "AVAILABLE",
    }
    data.update(overrides)
    return data


def test_initialize_is_idempotent(tmp_path):
    db = tmp_path / "gumtree.db"
    r1 = initialize_registry(db)
    r2 = initialize_registry(db)
    assert r1.db_path == r2.db_path
    with r2.connect() as conn:
        version = conn.execute("SELECT version FROM schema_migrations").fetchone()[0]
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert version == 1
    assert {
        "products",
        "advertisements",
        "product_ad_links",
        "gumtree_instances",
        "snapshots",
        "actions",
        "runs",
    }.issubset(tables)


def test_product_upsert_updates_same_row(tmp_path):
    registry = make_registry(tmp_path)
    registry.upsert_product(base_product())
    registry.upsert_product(base_product(title="RCS Red Cherry Shrimp", priority="CORE_TRAFFIC"))
    product = registry.get_product("123")
    assert product["title"] == "RCS Red Cherry Shrimp"
    assert product["priority"] == "CORE_TRAFFIC"
    with registry.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1


def test_invalid_management_state_is_rejected(tmp_path):
    registry = make_registry(tmp_path)
    with pytest.raises(ValueError):
        registry.upsert_product(base_product(management_state="AUTO_PUBLISH"))


def test_product_ad_link_is_idempotent(tmp_path):
    registry = make_registry(tmp_path)
    registry.upsert_product(base_product())
    registry.upsert_advertisement({"ad_id": "GT-NTA-000001"})
    registry.link_product_ad("123", "GT-NTA-000001")
    registry.link_product_ad("123", "GT-NTA-000001")
    with registry.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM product_ad_links").fetchone()[0]
    assert count == 1


def test_listing_id_is_unique_and_repeat_observation_updates_instance(tmp_path):
    registry = make_registry(tmp_path)
    registry.upsert_advertisement({"ad_id": "GT-NTA-000001"})
    first = registry.record_instance({
        "ad_id": "GT-NTA-000001",
        "gumtree_listing_id": "987654321",
        "actual_state": "DRAFT",
        "title": "Red Cherry Shrimp",
    })
    second = registry.record_instance({
        "ad_id": "GT-NTA-000001",
        "gumtree_listing_id": "987654321",
        "actual_state": "ACTIVE",
        "title": "RCS Red Cherry Shrimp",
    })
    assert first == second
    rows = registry.list_instances("GT-NTA-000001")
    assert len(rows) == 1
    assert rows[0]["actual_state"] == "ACTIVE"
    assert rows[0]["title"] == "RCS Red Cherry Shrimp"


def test_one_canonical_live_instance_per_ad(tmp_path):
    registry = make_registry(tmp_path)
    registry.upsert_advertisement({"ad_id": "GT-NTA-000001"})
    registry.record_instance({
        "ad_id": "GT-NTA-000001",
        "gumtree_listing_id": "1",
        "actual_state": "ACTIVE",
        "is_canonical": True,
    })
    with pytest.raises(sqlite3.IntegrityError):
        registry.record_instance({
            "ad_id": "GT-NTA-000001",
            "gumtree_listing_id": "2",
            "actual_state": "DRAFT",
            "is_canonical": True,
        })


def test_multiple_historical_instances_are_allowed(tmp_path):
    registry = make_registry(tmp_path)
    registry.upsert_advertisement({"ad_id": "GT-NTA-000001"})
    registry.record_instance({
        "ad_id": "GT-NTA-000001",
        "gumtree_listing_id": "old-1",
        "actual_state": "EXPIRED",
        "is_canonical": True,
    })
    registry.record_instance({
        "ad_id": "GT-NTA-000001",
        "gumtree_listing_id": "new-1",
        "actual_state": "ACTIVE",
        "is_canonical": True,
    })
    assert len(registry.list_instances("GT-NTA-000001")) == 2


def test_action_idempotency_prevents_duplicate_execution_record(tmp_path):
    registry = make_registry(tmp_path)
    registry.start_run("run-1", "RECONCILE")
    action1, created1 = registry.record_action(
        idempotency_key="run-1:123:CREATE_DRAFT",
        action="CREATE_DRAFT",
        run_id="run-1",
        payload={"product_id": "123"},
    )
    action2, created2 = registry.record_action(
        idempotency_key="run-1:123:CREATE_DRAFT",
        action="CREATE_DRAFT",
        run_id="run-1",
        payload={"product_id": "123"},
    )
    assert action1 == action2
    assert created1 is True
    assert created2 is False
    with registry.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0] == 1


def test_run_lifecycle_records_summary(tmp_path):
    registry = make_registry(tmp_path)
    registry.start_run("run-1", "CENSUS")
    registry.finish_run(
        "run-1",
        "COMPLETED",
        warning_count=2,
        summary={"discovered": 17},
    )
    with registry.connect() as conn:
        row = conn.execute("SELECT * FROM runs WHERE run_id='run-1'").fetchone()
    assert row["status"] == "COMPLETED"
    assert row["warning_count"] == 2
    assert row["summary_json"] == '{"discovered":17}'


def test_foreign_keys_block_orphan_product_ad_links(tmp_path):
    registry = make_registry(tmp_path)
    registry.upsert_advertisement({"ad_id": "GT-NTA-000001"})
    with pytest.raises(sqlite3.IntegrityError):
        registry.link_product_ad("missing-product", "GT-NTA-000001")


def test_invalid_actual_state_is_rejected(tmp_path):
    registry = make_registry(tmp_path)
    registry.upsert_advertisement({"ad_id": "GT-NTA-000001"})
    with pytest.raises(ValueError):
        registry.record_instance({
            "ad_id": "GT-NTA-000001",
            "gumtree_listing_id": "1",
            "actual_state": "PUBLISHED_BY_AI",
        })
