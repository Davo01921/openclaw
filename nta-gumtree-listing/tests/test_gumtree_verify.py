from gumtree_verify import build_health_metrics, verify_saved_draft


def plan():
    return {
        "ad_id": "GT-NTA-000001",
        "title": "Red Cherry Shrimp",
        "description": "Healthy aquarium shrimp",
        "price": "5.00",
        "category": "Pets",
        "location": "Croydon NSW",
        "image_urls": ["https://example.com/a.jpg"],
        "attributes": {"Type": "Shrimp"},
        "source_fingerprint": "fp-123",
    }


def write_result(**overrides):
    data = {
        "status": "DRAFT_SAVED",
        "gumtree_listing_id": "12345",
        "verification_required": True,
    }
    data.update(overrides)
    return data


def observed(**overrides):
    data = {
        "gumtree_listing_id": "12345",
        "actual_state": "DRAFT",
        "published": False,
        "title": "Red Cherry Shrimp",
        "description": "Healthy aquarium shrimp",
        "price": "$5.00",
        "category": "Pets",
        "location": "Croydon NSW",
        "image_urls": ["https://example.com/a.jpg"],
        "attributes": {"Type": "Shrimp"},
        "source_fingerprint": "fp-123",
    }
    data.update(overrides)
    return data


def test_matching_draft_is_verified():
    result = verify_saved_draft(plan(), write_result(), observed())
    assert result.status == "VERIFIED"
    assert result.mismatches == ()
    assert result.error_code is None


def test_verification_not_required_short_circuits():
    result = verify_saved_draft(plan(), write_result(verification_required=False), observed())
    assert result.status == "NOT_REQUIRED"


def test_failed_write_cannot_verify():
    result = verify_saved_draft(plan(), write_result(status="ERROR"), observed())
    assert result.status == "ERROR"
    assert result.error_code == "WRITE_NOT_SUCCESSFUL"


def test_stale_observation_fails_closed():
    result = verify_saved_draft(plan(), write_result(), observed(snapshot_stale=True))
    assert result.status == "ERROR"
    assert result.error_code == "OBSERVED_SNAPSHOT_UNSAFE"


def test_non_draft_state_is_error():
    result = verify_saved_draft(plan(), write_result(), observed(actual_state="ACTIVE"))
    assert result.status == "ERROR"
    assert result.error_code == "OBSERVED_STATE_NOT_DRAFT"


def test_unexpected_publish_is_error():
    result = verify_saved_draft(plan(), write_result(), observed(published=True))
    assert result.status == "ERROR"
    assert result.error_code == "UNEXPECTED_PUBLISH_STATE"


def test_field_mismatches_are_reported_deterministically():
    result = verify_saved_draft(
        plan(),
        write_result(),
        observed(title="Wrong", price="6", location="Burwood NSW"),
    )
    assert result.status == "MISMATCH"
    assert result.mismatches == (
        "LOCATION_MISMATCH",
        "PRICE_MISMATCH",
        "TITLE_MISMATCH",
    )


def test_image_and_attribute_mismatch_detected():
    result = verify_saved_draft(
        plan(),
        write_result(),
        observed(image_urls=["https://example.com/b.jpg"], attributes={"Type": "Fish"}),
    )
    assert result.status == "MISMATCH"
    assert "IMAGES_MISMATCH" in result.mismatches
    assert "ATTRIBUTES_MISMATCH" in result.mismatches


def test_source_fingerprint_checked_when_observed():
    result = verify_saved_draft(plan(), write_result(), observed(source_fingerprint="other"))
    assert result.status == "MISMATCH"
    assert result.mismatches == ("SOURCE_FINGERPRINT_MISMATCH",)


def test_missing_observed_fingerprint_does_not_invent_mismatch():
    data = observed()
    data.pop("source_fingerprint")
    result = verify_saved_draft(plan(), write_result(), data)
    assert result.status == "VERIFIED"


def test_health_metrics_healthy_when_all_verified():
    metrics = build_health_metrics([
        verify_saved_draft(plan(), write_result(), observed()),
        verify_saved_draft(plan(), write_result(), observed()),
    ])
    assert metrics["total"] == 2
    assert metrics["verified"] == 2
    assert metrics["healthy"] is True
    assert metrics["verification_rate"] == 1.0


def test_health_metrics_counts_mismatches_and_errors():
    results = [
        verify_saved_draft(plan(), write_result(), observed(title="Wrong")),
        verify_saved_draft(plan(), write_result(), observed(actual_state="ACTIVE")),
    ]
    metrics = build_health_metrics(results)
    assert metrics["healthy"] is False
    assert metrics["mismatch"] == 1
    assert metrics["error"] == 1
    assert metrics["mismatch_codes"] == {"TITLE_MISMATCH": 1}
    assert metrics["error_codes"] == {"OBSERVED_STATE_NOT_DRAFT": 1}


def test_invalid_health_status_fails_into_error_bucket():
    metrics = build_health_metrics([{"status": "BOGUS", "mismatches": []}])
    assert metrics["error"] == 1
    assert metrics["error_codes"] == {"INVALID_VERIFICATION_STATUS": 1}
