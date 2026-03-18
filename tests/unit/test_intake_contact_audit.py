"""Unit tests for IntakeStore.get_contact and audit logging."""

from __future__ import annotations

import sqlalchemy as sa
from cryptography.fernet import Fernet

from i4g.store import sql as sql_schema
from i4g.store.intake_store import IntakeStore


def test_get_contact_returns_decrypted_fields(tmp_path) -> None:
    """get_contact returns decrypted victim contact fields."""
    key = Fernet.generate_key().decode()
    store = IntakeStore(db_path=str(tmp_path / "test.db"), pii_key=key)

    intake_id = store.create_intake(
        reporter_name="Alice Smith",
        summary="Report",
        details="Details",
        submitted_by="analyst-1",
        contact_email="alice@example.com",
        contact_phone="+1-555-0100",
        contact_handle="@alice",
        preferred_contact="email",
    )

    contact = store.get_contact(intake_id, actor="analyst-1")
    assert contact is not None
    assert contact["reporter_name"] == "Alice Smith"
    assert contact["contact_email"] == "alice@example.com"
    assert contact["contact_phone"] == "+1-555-0100"
    assert contact["contact_handle"] == "@alice"
    assert contact["preferred_contact"] == "email"


def test_get_contact_returns_none_for_missing(tmp_path) -> None:
    """get_contact returns None when intake_id does not exist."""
    store = IntakeStore(db_path=str(tmp_path / "test.db"))
    assert store.get_contact("nonexistent-id", actor="analyst-1") is None


def test_get_contact_creates_audit_log_entry(tmp_path) -> None:
    """get_contact writes an audit_log row."""
    key = Fernet.generate_key().decode()
    store = IntakeStore(db_path=str(tmp_path / "test.db"), pii_key=key)

    intake_id = store.create_intake(
        reporter_name="Bob",
        summary="Report",
        details="Details",
        submitted_by="analyst-2",
        contact_email="bob@example.com",
    )

    store.get_contact(intake_id, actor="analyst-2")

    # Verify audit log entry
    with store._session_factory() as session:
        rows = session.execute(
            sa.select(sql_schema.audit_log).where(
                sql_schema.audit_log.c.resource_id == intake_id,
            )
        ).all()

    assert len(rows) == 1
    row = dict(rows[0]._mapping)
    assert row["actor"] == "analyst-2"
    assert row["action"] == "view_contact"
    assert row["resource_type"] == "intake"
    assert row["resource_id"] == intake_id
