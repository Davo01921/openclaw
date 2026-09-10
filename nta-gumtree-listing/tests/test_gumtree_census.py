import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from gumtree_census import census_records, import_census, normalize_observation  # noqa: E402
from gumtree_registry import initialize_registry  # noqa: E402


def make_registry(tmp_path):
    registry = initialize_registry(tmp_path / "gumtree.db")
    registry.upsert_advertisement({"ad_id": "GT-NTA-000001"})
    return registry


def test_normalize_observation_accepts_explicit_id():
    obs = normalize_observation(
        {
            "listing_id": "123456789",
            "status": "live",
            "title": " Red Cherry Shrimp ",
            "price": "$5",
        }
    )
    assert obs.gumtree_listing_id == "123456789"
    assert obs.actual_state == "ACTIVE"
    assert obs.title == "Red Cherry Shrimp"


def test_normalize_observation_extracts_id_from_url():
    obs = normalize_observation(
        {
            "url": "https://www.gumtree.com.au/s-ad/croydon/fish/thing/123456789",
            "state": "paused",
        }
    )
    assert obs.gumtree_listing_id == "123456789"
    assert obs.actual_state == "PAUSED"


def test_unknown_state_stays_unknown_not_active():
    obs = normalize_observation({"listing_id": "123456789", "status": "maybe-live"})
    assert obs.actual_state == "UNKNOWN"


def test_missing_listing_identity_is_error():
    observations, results = census_records([{"title": "No identity"}])
    assert observations == []
    assert len(results) == 1
    assert results[0].outcome == "ERROR"


def test_duplicate_listing_identity_requires_review():
    observations, results = census_records(
        [
            {"listing_id": "123456789", "status": "active"},
            {"listing_id": "123456789", "status": "active"},
        ]
    )
    assert len(observations) == 1
    assert results[0].outcome == "DUPLICATE_REVIEW"


def test_unmatched_listing_is_not_imported(tmp_path):
    registry = make_registry(tmp_path)
    results = import_census(
        registry,
        [{"listing_id": "123456789", "status": "active"}],
        listing_to_ad={},
    )
    assert results[0].outcome == "IDENTITY_REVIEW"
    with registry.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM gumtree_instances").fetchone()[0]
    assert count == 0


def test_mapping_to_unknown_ad_is_not_imported(tmp_path):
    registry = make_registry(tmp_path)
    results = import_census(
        registry,
        [{"listing_id": "123456789", "status": "active"}],
        listing_to_ad={"123456789": "GT-NTA-999999"},
    )
    assert results[0].outcome == "IDENTITY_REVIEW"
    assert results[0].ad_id == "GT-NTA-999999"


def test_trusted_mapping_imports_observation(tmp_path):
    registry = make_registry(tmp_path)
    results = import_census(
        registry,
        [
            {
                "listing_id": "123456789",
                "status": "live",
                "title": "Red Cherry Shrimp",
                "captured_at": "2026-09-11T08:00:00+10:00",
            }
        ],
        listing_to_ad={"123456789": "GT-NTA-000001"},
    )
    assert results[0].outcome == "IMPORTED"
    rows = registry.list_instances("GT-NTA-000001")
    assert len(rows) == 1
    assert rows[0]["gumtree_listing_id"] == "123456789"
    assert rows[0]["actual_state"] == "ACTIVE"
    assert rows[0]["is_canonical"] == 0


def test_repeat_census_updates_same_registry_instance(tmp_path):
    registry = make_registry(tmp_path)
    mapping = {"123456789": "GT-NTA-000001"}
    first = import_census(
        registry,
        [{"listing_id": "123456789", "status": "draft", "title": "Old"}],
        listing_to_ad=mapping,
    )
    second = import_census(
        registry,
        [{"listing_id": "123456789", "status": "active", "title": "New"}],
        listing_to_ad=mapping,
    )
    assert first[0].instance_id == second[0].instance_id
    rows = registry.list_instances("GT-NTA-000001")
    assert len(rows) == 1
    assert rows[0]["actual_state"] == "ACTIVE"
    assert rows[0]["title"] == "New"


def test_census_never_marks_imported_instance_canonical(tmp_path):
    registry = make_registry(tmp_path)
    import_census(
        registry,
        [{"listing_id": "123456789", "status": "active"}],
        listing_to_ad={"123456789": "GT-NTA-000001"},
    )
    assert registry.list_instances("GT-NTA-000001")[0]["is_canonical"] == 0
