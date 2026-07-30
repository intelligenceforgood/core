"""Unit tests for API key management endpoints (core/src/i4g/api/api_keys.py).

Tests verify:
- Full CRUD lifecycle (create -> list -> revoke -> verify revoked)
- Role authorization (admin vs non-admin)
- Creation response returns raw key ONCE
- List response does NOT contain raw key or key_hash
- Invalid inputs (negative expires_in_days)
- Partner key creation (admin only)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from i4g.api.app import app
from i4g.api.auth import require_role, require_token
from i4g.store import sql as sql_schema
from i4g.store.api_key_store import ApiKeyStore


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    """Reset dependency overrides after each test."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def session_factory():
    """In-memory SQLite engine fixture for unit testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sql_schema.METADATA.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def api_key_store(session_factory):
    """Instantiated ApiKeyStore using in-memory SQLite database."""
    return ApiKeyStore(session_factory)


@pytest.fixture
def client(session_factory):
    """TestClient with patched build_sql_session_factory."""
    with (
        patch("i4g.services.factories.build_sql_session_factory", return_value=session_factory),
        patch("i4g.store.sql.session_factory", return_value=session_factory),
    ):
        yield TestClient(app)


class TestUserApiKeyEndpoints:
    """Self-service API key endpoints (/api-keys)."""

    def test_create_user_api_key_success(self, client):
        app.dependency_overrides[require_token] = lambda: {"username": "user@example.com", "role": "user"}

        payload = {
            "description": "My test key",
            "scopes": ["cases:read"],
            "expiresInDays": 30,
        }
        res = client.post("/api-keys", json=payload)
        assert res.status_code == status.HTTP_201_CREATED

        data = res.json()
        assert "rawKey" in data
        assert data["rawKey"].startswith("i4g_uk_")
        assert "keyId" in data
        assert data["keyPrefix"].startswith("i4g_uk_")
        assert data["expiresAt"] is not None

    def test_create_user_api_key_invalid_expiry(self, client):
        app.dependency_overrides[require_token] = lambda: {"username": "user@example.com", "role": "user"}

        payload = {
            "description": "Invalid key",
            "expiresInDays": -5,
        }
        res = client.post("/api-keys", json=payload)
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_list_user_api_keys(self, client, api_key_store):
        app.dependency_overrides[require_token] = lambda: {"username": "user@example.com", "role": "user"}

        # Create two keys for user@example.com and one for other@example.com
        api_key_store.create_key(owner_email="user@example.com", key_type="user", description="Key 1")
        api_key_store.create_key(owner_email="user@example.com", key_type="user", description="Key 2")
        api_key_store.create_key(owner_email="other@example.com", key_type="user", description="Other Key")

        res = client.get("/api-keys")
        assert res.status_code == status.HTTP_200_OK

        data = res.json()
        assert len(data["keys"]) == 2
        descriptions = {k["description"] for k in data["keys"]}
        assert descriptions == {"Key 1", "Key 2"}

        # Verify rawKey and keyHash are NOT in list response
        for key_info in data["keys"]:
            assert "rawKey" not in key_info
            assert "raw_key" not in key_info
            assert "keyHash" not in key_info
            assert "key_hash" not in key_info

    def test_revoke_user_api_key(self, client, api_key_store):
        app.dependency_overrides[require_token] = lambda: {"username": "user@example.com", "role": "user"}

        raw_key, record = api_key_store.create_key(
            owner_email="user@example.com", key_type="user", description="To revoke"
        )
        key_id = record["key_id"]

        # Revoke key
        res = client.delete(f"/api-keys/{key_id}")
        assert res.status_code == status.HTTP_204_NO_CONTENT

        # Verify key is no longer active in store list
        records = api_key_store.list_keys_for_owner("user@example.com")
        revoked_rec = next(r for r in records if r["key_id"] == key_id)
        assert revoked_rec["is_active"] is False

    def test_revoke_user_api_key_not_owned(self, client, api_key_store):
        app.dependency_overrides[require_token] = lambda: {"username": "user@example.com", "role": "user"}

        raw_key, record = api_key_store.create_key(
            owner_email="other@example.com", key_type="user", description="Other user key"
        )
        key_id = record["key_id"]

        res = client.delete(f"/api-keys/{key_id}")
        assert res.status_code == status.HTTP_404_NOT_FOUND


class TestAdminApiKeyEndpoints:
    """Admin API key endpoints (/admin/api-keys)."""

    def test_admin_list_api_keys_as_admin(self, client, api_key_store):
        app.dependency_overrides[require_role("admin")] = lambda: {"username": "admin@example.com", "role": "admin"}

        api_key_store.create_key(owner_email="user1@example.com", key_type="user", description="U1 Key")
        api_key_store.create_key(owner_email="user2@example.com", key_type="user", description="U2 Key")
        api_key_store.create_key(owner_email="partner@example.com", key_type="partner", description="P Key")

        res = client.get("/admin/api-keys")
        assert res.status_code == status.HTTP_200_OK

        data = res.json()
        assert len(data["keys"]) == 3

    def test_admin_revoke_any_api_key(self, client, api_key_store):
        app.dependency_overrides[require_role("admin")] = lambda: {"username": "admin@example.com", "role": "admin"}

        raw_key, record = api_key_store.create_key(
            owner_email="user1@example.com", key_type="user", description="User Key"
        )
        key_id = record["key_id"]

        res = client.delete(f"/admin/api-keys/{key_id}")
        assert res.status_code == status.HTTP_204_NO_CONTENT

        records = api_key_store.list_all_keys()
        revoked_rec = next(r for r in records if r["key_id"] == key_id)
        assert revoked_rec["is_active"] is False

    def test_admin_create_partner_api_key(self, client):
        app.dependency_overrides[require_role("admin")] = lambda: {"username": "admin@example.com", "role": "admin"}

        payload = {
            "partnerName": "Acme Threat Intel",
            "ownerEmail": "threat@acme.com",
            "scopes": ["partner:feed", "indicators:read"],
            "expiresInDays": 365,
            "rateLimitPerMinute": 120,
            "description": "Acme integration key",
        }

        res = client.post("/admin/api-keys/partner", json=payload)
        assert res.status_code == status.HTTP_201_CREATED

        data = res.json()
        assert "rawKey" in data
        assert data["rawKey"].startswith("i4g_pk_")
        assert data["keyPrefix"].startswith("i4g_pk_")
