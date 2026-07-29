"""Unit tests for ApiKeyStore."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from i4g.store import sql as sql_schema
from i4g.store.api_key_store import ApiKeyStore


@pytest.fixture
def session_factory():
    """In-memory SQLite engine fixture for unit testing ApiKeyStore."""
    engine = create_engine("sqlite:///:memory:")
    sql_schema.METADATA.create_all(engine)
    sf = sessionmaker(bind=engine)
    return sf


@pytest.fixture
def api_key_store(session_factory):
    """Instantiated ApiKeyStore using in-memory database."""
    return ApiKeyStore(session_factory)


def test_create_key_user(api_key_store):
    """Verify user key creation generates correct prefix, hash, and metadata."""
    raw_key, record = api_key_store.create_key(
        owner_email="alice@example.com",
        key_type="user",
        description="Test user key",
    )

    assert raw_key.startswith("i4g_uk_")
    assert record["key_prefix"].startswith("i4g_uk_")
    assert record["owner_email"] == "alice@example.com"
    assert record["key_type"] == "user"
    assert record["is_active"] is True
    assert record["key_hash"] != raw_key  # Raw key is never stored


def test_create_key_partner(api_key_store):
    """Verify partner key creation prefix and partner_name fields."""
    raw_key, record = api_key_store.create_key(
        owner_email="partner@example.com",
        key_type="partner",
        partner_name="Acme Corp",
        scopes=["partner:feed"],
    )

    assert raw_key.startswith("i4g_pk_")
    assert record["key_prefix"].startswith("i4g_pk_")
    assert record["partner_name"] == "Acme Corp"
    assert record["scopes"] == ["partner:feed"]


def test_create_key_service(api_key_store):
    """Verify service key creation prefix."""
    raw_key, record = api_key_store.create_key(
        key_type="service",
        description="Service bot",
    )

    assert raw_key.startswith("i4g_sk_")
    assert record["key_prefix"].startswith("i4g_sk_")
    assert record["key_type"] == "service"


def test_validate_key_success(api_key_store):
    """Valid key returns record and updates last_used_at."""
    raw_key, record = api_key_store.create_key(
        owner_email="bob@example.com",
        key_type="user",
    )

    assert record["last_used_at"] is None

    validated = api_key_store.validate_key(raw_key)
    assert validated is not None
    assert validated["key_id"] == record["key_id"]
    assert validated["owner_email"] == "bob@example.com"
    assert validated["last_used_at"] is not None


def test_validate_key_invalid(api_key_store):
    """Non-existent raw key returns None."""
    assert api_key_store.validate_key("i4g_uk_invalid_key_12345") is None
    assert api_key_store.validate_key("") is None


def test_validate_key_revoked(api_key_store):
    """Revoked key returns None upon validation."""
    raw_key, record = api_key_store.create_key(
        owner_email="charlie@example.com",
        key_type="user",
    )

    revoked = api_key_store.revoke_key(record["key_id"])
    assert revoked is True

    validated = api_key_store.validate_key(raw_key)
    assert validated is None


def test_validate_key_expired(api_key_store):
    """Expired key returns None upon validation."""
    raw_key, record = api_key_store.create_key(
        owner_email="dave@example.com",
        key_type="user",
        expires_in_days=-1,  # Already expired
    )

    validated = api_key_store.validate_key(raw_key)
    assert validated is None


def test_list_keys_for_owner(api_key_store):
    """Listing keys filters correctly by owner_email and key_type."""
    _, k1 = api_key_store.create_key(owner_email="eve@example.com", key_type="user")
    _, k2 = api_key_store.create_key(owner_email="eve@example.com", key_type="partner")
    _, _ = api_key_store.create_key(owner_email="other@example.com", key_type="user")

    user_keys = api_key_store.list_keys_for_owner("eve@example.com")
    assert len(user_keys) == 2

    user_only = api_key_store.list_keys_for_owner("eve@example.com", key_type="user")
    assert len(user_only) == 1
    assert user_only[0]["key_id"] == k1["key_id"]


def test_list_all_keys(api_key_store):
    """Listing all keys for admin with filtering options."""
    _, k1 = api_key_store.create_key(owner_email="u1@example.com", key_type="user")
    _, k2 = api_key_store.create_key(owner_email="u2@example.com", key_type="partner")

    api_key_store.revoke_key(k1["key_id"])

    all_keys = api_key_store.list_all_keys()
    assert len(all_keys) == 2

    active_keys = api_key_store.list_all_keys(active_only=True)
    assert len(active_keys) == 1
    assert active_keys[0]["key_id"] == k2["key_id"]


def test_delete_key(api_key_store):
    """Deleting key removes row completely."""
    raw_key, record = api_key_store.create_key(owner_email="frank@example.com", key_type="user")

    deleted = api_key_store.delete_key(record["key_id"], owner_email="frank@example.com")
    assert deleted is True

    keys = api_key_store.list_keys_for_owner("frank@example.com")
    assert len(keys) == 0

    assert api_key_store.validate_key(raw_key) is None
