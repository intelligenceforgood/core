"""Unit tests for researcher anonymization layer (S5-32)."""

from __future__ import annotations

from i4g.services.anonymizer import anonymize_record, anonymize_records, anonymize_value, round_loss


def test_anonymize_value_pii_type() -> None:
    """PII entity types produce hashed output."""
    original = "john.doe@evil.com"
    hashed = anonymize_value(original, entity_type="email")
    assert hashed != original
    assert len(hashed) == 16  # SHA-256 prefix


def test_anonymize_value_non_pii_unchanged() -> None:
    """Non-PII entity types are returned unchanged."""
    domain = "evil.com"
    result = anonymize_value(domain, entity_type="domain")
    assert result == domain


def test_anonymize_value_deterministic() -> None:
    """Same input always produces same hash."""
    v1 = anonymize_value("test-value", entity_type="bank_account")
    v2 = anonymize_value("test-value", entity_type="bank_account")
    assert v1 == v2


def test_round_loss_default_precision() -> None:
    """Loss is rounded up to nearest $1,000."""
    assert round_loss(1500.0) == 2000.0
    assert round_loss(1000.0) == 1000.0
    assert round_loss(1.0) == 1000.0
    assert round_loss(0.0) == 0.0


def test_round_loss_custom_precision() -> None:
    """Loss is rounded to custom precision."""
    assert round_loss(1500.0, precision=500) == 1500.0
    assert round_loss(1501.0, precision=500) == 2000.0


def test_anonymize_record_hashes_pii_fields() -> None:
    """PII fields in a record are hashed."""
    record = {
        "entity_type": "bank_account",
        "canonical_value": "1234567890",
        "case_count": 5,
        "loss_sum": 1500.50,
    }
    result = anonymize_record(record)

    assert result["canonical_value"] != "1234567890"
    assert len(result["canonical_value"]) == 16
    assert result["case_count"] == 5
    assert result["loss_sum"] == 2000.0  # Rounded


def test_anonymize_record_non_pii_entity_unchanged() -> None:
    """Non-PII entity records keep their canonical_value."""
    record = {
        "entity_type": "domain",
        "canonical_value": "evil.com",
        "case_count": 3,
        "loss_sum": 500.0,
    }
    result = anonymize_record(record)

    assert result["canonical_value"] == "evil.com"
    assert result["loss_sum"] == 1000.0  # Loss still rounded


def test_anonymize_records_list() -> None:
    """anonymize_records processes a list of records."""
    records = [
        {"entity_type": "email", "canonical_value": "a@b.com", "loss_sum": 100.0},
        {"entity_type": "domain", "canonical_value": "d.com", "loss_sum": 3000.0},
    ]
    results = anonymize_records(records)

    assert len(results) == 2
    assert results[0]["canonical_value"] != "a@b.com"  # Hashed
    assert results[1]["canonical_value"] == "d.com"  # Unchanged
