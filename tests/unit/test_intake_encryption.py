"""Unit tests for IntakeStore PII field encryption round-trip."""

from __future__ import annotations

from cryptography.fernet import Fernet

from i4g.store.intake_store import IntakeStore


def test_intake_encrypts_and_decrypts_contact_fields(tmp_path) -> None:
    """Contact fields should be encrypted at rest and decrypted on read."""
    key = Fernet.generate_key().decode()
    store = IntakeStore(db_path=str(tmp_path / "test.db"), pii_key=key)

    intake_id = store.create_intake(
        reporter_name="Alice Smith",
        summary="Lost funds",
        details="Sent crypto to scam site",
        submitted_by="analyst-1",
        contact_email="alice@example.com",
        contact_phone="+1-555-0100",
        contact_handle="@alice_reports",
    )

    record = store.get_intake(intake_id)
    assert record is not None
    assert record["reporter_name"] == "Alice Smith"
    assert record["contact_email"] == "alice@example.com"
    assert record["contact_phone"] == "+1-555-0100"
    assert record["contact_handle"] == "@alice_reports"


def test_intake_no_key_stores_cleartext(tmp_path) -> None:
    """Without a PII key, contact fields are stored as cleartext."""
    store = IntakeStore(db_path=str(tmp_path / "test.db"))

    intake_id = store.create_intake(
        reporter_name="Bob Jones",
        summary="Phishing",
        details="Received suspicious email",
        submitted_by="analyst-2",
        contact_email="bob@example.com",
    )

    record = store.get_intake(intake_id)
    assert record is not None
    assert record["reporter_name"] == "Bob Jones"
    assert record["contact_email"] == "bob@example.com"


def test_intake_list_decrypts(tmp_path) -> None:
    """list_intakes should also decrypt contact fields."""
    key = Fernet.generate_key().decode()
    store = IntakeStore(db_path=str(tmp_path / "test.db"), pii_key=key)

    store.create_intake(
        reporter_name="Carol",
        summary="Investment scam",
        details="Details here",
        submitted_by="analyst-3",
    )

    results = store.list_intakes()
    assert len(results) == 1
    assert results[0]["reporter_name"] == "Carol"
