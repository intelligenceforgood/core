"""Unit tests for the AccountStore (WS-5: F30, F31, F34, F35).

Uses an in-memory SQLite database to verify CRUD operations, role
assignment, audit logging, and account provisioning.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from i4g.api.roles import DEFAULT_ROLE, Role
from i4g.store import sql as sql_schema
from i4g.store.account_store import AccountStore


@pytest.fixture()
def db_session_factory():
    """Create an in-memory SQLite engine with the full schema."""
    engine = create_engine("sqlite:///:memory:", future=True)
    sql_schema.METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return factory


@pytest.fixture()
def store(db_session_factory) -> AccountStore:
    """Return an AccountStore backed by the in-memory DB."""
    return AccountStore(db_session_factory)


class TestGetOrCreateAccount:
    """Verify auto-provisioning of accounts."""

    def test_creates_account_on_first_lookup(self, store: AccountStore):
        account = store.get_or_create_account("new@example.com")
        assert account is not None
        assert account["email"] == "new@example.com"
        assert account["role"] == DEFAULT_ROLE.value

    def test_default_display_name_from_email(self, store: AccountStore):
        account = store.get_or_create_account("alice@example.com")
        assert account["display_name"] == "alice"

    def test_custom_display_name(self, store: AccountStore):
        account = store.get_or_create_account("bob@test.io", display_name="Bob Test")
        assert account["display_name"] == "Bob Test"

    def test_returns_existing_on_second_call(self, store: AccountStore):
        first = store.get_or_create_account("same@test.io")
        second = store.get_or_create_account("same@test.io")
        assert first["email"] == second["email"]
        assert first["role"] == second["role"]

    def test_is_active_by_default(self, store: AccountStore):
        account = store.get_or_create_account("active@test.io")
        assert account["is_active"] is True


class TestGetAccount:
    """Verify account retrieval."""

    def test_returns_none_for_unknown(self, store: AccountStore):
        assert store.get_account("nobody@nowhere.com") is None

    def test_returns_account_after_creation(self, store: AccountStore):
        store.get_or_create_account("exists@test.io")
        result = store.get_account("exists@test.io")
        assert result is not None
        assert result["email"] == "exists@test.io"


class TestListAccounts:
    """Verify listing accounts."""

    def test_empty_initially(self, store: AccountStore):
        assert store.list_accounts() == []

    def test_lists_all_active(self, store: AccountStore):
        store.get_or_create_account("a@test.io")
        store.get_or_create_account("b@test.io")
        accounts = store.list_accounts()
        assert len(accounts) == 2
        emails = {a["email"] for a in accounts}
        assert emails == {"a@test.io", "b@test.io"}

    def test_excludes_deactivated(self, store: AccountStore):
        store.get_or_create_account("active@test.io")
        store.get_or_create_account("inactive@test.io")
        store.deactivate_account("inactive@test.io", actor="admin@test.io")
        active = store.list_accounts(active_only=True)
        assert len(active) == 1
        assert active[0]["email"] == "active@test.io"

    def test_includes_deactivated_when_requested(self, store: AccountStore):
        store.get_or_create_account("active@test.io")
        store.get_or_create_account("inactive@test.io")
        store.deactivate_account("inactive@test.io", actor="admin@test.io")
        all_accounts = store.list_accounts(active_only=False)
        assert len(all_accounts) == 2

    def test_excludes_service_accounts_by_default(self, store: AccountStore):
        store.get_or_create_account("user@test.io")
        store.get_or_create_account("sa-app@i4g-dev.iam.gserviceaccount.com")
        accounts = store.list_accounts()
        assert len(accounts) == 1
        assert accounts[0]["email"] == "user@test.io"

    def test_includes_service_accounts_when_requested(self, store: AccountStore):
        store.get_or_create_account("user@test.io")
        store.get_or_create_account("sa-app@i4g-dev.iam.gserviceaccount.com")
        accounts = store.list_accounts(include_service_accounts=True)
        assert len(accounts) == 2


class TestUpdateRole:
    """Verify role changes and audit logging (F34, F35)."""

    def test_valid_role_change(self, store: AccountStore):
        store.get_or_create_account("target@test.io")
        updated = store.update_role("target@test.io", "admin", actor="boss@test.io")
        assert updated is not None
        assert updated["role"] == "admin"

    def test_role_persists(self, store: AccountStore):
        store.get_or_create_account("target@test.io")
        store.update_role("target@test.io", "leo", actor="boss@test.io")
        account = store.get_account("target@test.io")
        assert account["role"] == "leo"

    def test_invalid_role_raises(self, store: AccountStore):
        store.get_or_create_account("target@test.io")
        with pytest.raises(ValueError, match="Invalid role"):
            store.update_role("target@test.io", "superuser", actor="boss@test.io")

    def test_nonexistent_account_returns_none(self, store: AccountStore):
        result = store.update_role("nobody@test.io", "admin", actor="boss@test.io")
        assert result is None

    def test_audit_log_written_on_role_change(self, store: AccountStore, db_session_factory):
        store.get_or_create_account("target@test.io")
        store.update_role("target@test.io", "admin", actor="boss@test.io")

        # Check account_actions table for the audit entry.
        with db_session_factory() as session:
            rows = session.execute(
                sa.select(sql_schema.account_actions).where(sql_schema.account_actions.c.action == "role_change")
            ).all()
            assert len(rows) == 1
            row = dict(rows[0]._mapping)
            assert row["actor"] == "boss@test.io"
            assert row["target_email"] == "target@test.io"
            assert row["payload"]["old_role"] == DEFAULT_ROLE.value
            assert row["payload"]["new_role"] == "admin"

    def test_all_valid_roles(self, store: AccountStore):
        store.get_or_create_account("multi@test.io")
        for role in Role:
            updated = store.update_role("multi@test.io", role.value, actor="admin@test.io")
            assert updated["role"] == role.value


class TestUpdateDisplayName:
    """Verify display name updates."""

    def test_update_display_name(self, store: AccountStore):
        store.get_or_create_account("name@test.io")
        updated = store.update_display_name("name@test.io", "New Name")
        assert updated is not None
        assert updated["display_name"] == "New Name"

    def test_nonexistent_returns_none(self, store: AccountStore):
        result = store.update_display_name("nobody@test.io", "Name")
        assert result is None


class TestDeactivateAccount:
    """Verify account deactivation (F34)."""

    def test_deactivate_existing(self, store: AccountStore):
        store.get_or_create_account("victim@test.io")
        success = store.deactivate_account("victim@test.io", actor="admin@test.io")
        assert success is True
        account = store.get_account("victim@test.io")
        assert account["is_active"] is False

    def test_deactivate_nonexistent_returns_false(self, store: AccountStore):
        result = store.deactivate_account("nobody@test.io", actor="admin@test.io")
        assert result is False

    def test_deactivation_audit_log(self, store: AccountStore, db_session_factory):
        store.get_or_create_account("victim@test.io")
        store.deactivate_account("victim@test.io", actor="admin@test.io")

        with db_session_factory() as session:
            rows = session.execute(
                sa.select(sql_schema.account_actions).where(
                    sql_schema.account_actions.c.action == "account_deactivated"
                )
            ).all()
            assert len(rows) == 1
            row = dict(rows[0]._mapping)
            assert row["actor"] == "admin@test.io"
            assert row["target_email"] == "victim@test.io"


class TestReactivateAccount:
    """Verify account reactivation."""

    def test_reactivate_deactivated(self, store: AccountStore):
        store.get_or_create_account("paused@test.io")
        store.deactivate_account("paused@test.io", actor="admin@test.io")
        assert store.get_account("paused@test.io")["is_active"] is False

        success = store.reactivate_account("paused@test.io", actor="admin@test.io")
        assert success is True
        assert store.get_account("paused@test.io")["is_active"] is True

    def test_reactivate_nonexistent_returns_false(self, store: AccountStore):
        result = store.reactivate_account("nobody@test.io", actor="admin@test.io")
        assert result is False

    def test_reactivation_audit_log(self, store: AccountStore, db_session_factory):
        store.get_or_create_account("paused@test.io")
        store.deactivate_account("paused@test.io", actor="admin@test.io")
        store.reactivate_account("paused@test.io", actor="admin@test.io")

        with db_session_factory() as session:
            rows = session.execute(
                sa.select(sql_schema.account_actions).where(
                    sql_schema.account_actions.c.action == "account_reactivated"
                )
            ).all()
            assert len(rows) == 1
            row = dict(rows[0]._mapping)
            assert row["actor"] == "admin@test.io"
            assert row["target_email"] == "paused@test.io"
