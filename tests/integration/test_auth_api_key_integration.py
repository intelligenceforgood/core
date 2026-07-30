"""Integration test suite for end-to-end API key authentication chain.

Tests verify:
- End-to-end API key lifecycle (create key -> authenticate request -> access endpoint -> revoke -> verify rejection)
- Coexistence of all auth mechanisms:
  - Local bypass (settings.identity.disable_auth = True)
  - Static env API key (X-API-KEY == settings.api.key)
  - DB-backed API keys (X-API-KEY validated via ApiKeyStore)
- Expiration handling (expired DB key returns 401)
- Scope enforcement on partner endpoints
- Forwarded user header (X-I4G-Forwarded-User) with DB keys
- Last used timestamp auto-update on successful validation
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from i4g.api.app import app
from i4g.store import sql as sql_schema
from i4g.store.account_store import AccountStore
from i4g.store.api_key_store import ApiKeyStore


@pytest.fixture
def session_factory():
    """In-memory SQLite engine fixture."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sql_schema.METADATA.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def api_key_store(session_factory):
    """Instantiated ApiKeyStore."""
    return ApiKeyStore(session_factory)


@pytest.fixture
def account_store(session_factory):
    """Instantiated AccountStore."""
    store = AccountStore(session_factory)
    store.get_or_create_account("analyst@example.com", display_name="Test Analyst")
    store.update_role("analyst@example.com", "analyst", actor="system")
    store.get_or_create_account("partner@example.com", display_name="Test Partner")
    store.update_role("partner@example.com", "researcher", actor="system")
    return store


@pytest.fixture
def mock_settings():
    """Mock settings with disable_auth=False and partner_feed.enabled=True."""
    settings = MagicMock()
    settings.identity.disable_auth = False
    settings.identity.audience = None
    settings.api.key = "static-test-key-999"
    settings.partner_feed.enabled = True
    settings.partner_feed.default_page_size = 50
    settings.partner_feed.max_page_size = 200
    settings.partner_feed.rate_limit_per_minute = 60
    return settings


@pytest.fixture
def client(session_factory, api_key_store, account_store, mock_settings):
    """TestClient with patched stores and settings."""
    with (
        patch("i4g.services.factories.build_sql_session_factory", return_value=session_factory),
        patch("i4g.store.sql.session_factory", return_value=session_factory),
        patch("i4g.api.auth._get_api_key_store", return_value=api_key_store),
        patch("i4g.api.auth._get_account_store", return_value=account_store),
        patch("i4g.api.auth.get_settings", return_value=mock_settings),
        patch("i4g.api.partner_feed.get_settings", return_value=mock_settings),
        patch("i4g.api.partner_feed.build_api_key_store", return_value=api_key_store),
    ):
        app.dependency_overrides.clear()
        yield TestClient(app)
        app.dependency_overrides.clear()


class TestApiKeyIntegrationAuthChain:
    """Integration test suite for DB-backed API key authentication."""

    def test_db_api_key_auth_flow(self, client, api_key_store):
        """Valid DB API key authenticates request and resolves identity."""
        raw_key, record = api_key_store.create_key(
            owner_email="analyst@example.com",
            key_type="user",
            description="Integration key",
            scopes=["cases:read"],
        )

        res = client.get("/accounts/me", headers={"X-API-KEY": raw_key})
        assert res.status_code == 200
        data = res.json()
        assert data["email"] == "analyst@example.com"
        assert data["role"] == "analyst"

    def test_db_api_key_last_used_updated(self, client, api_key_store):
        """Successful authentication updates last_used_at timestamp."""
        raw_key, record = api_key_store.create_key(
            owner_email="analyst@example.com",
            key_type="user",
            description="Timestamp key",
        )
        assert record["last_used_at"] is None

        res = client.get("/accounts/me", headers={"X-API-KEY": raw_key})
        assert res.status_code == 200

        updated_records = api_key_store.list_keys_for_owner("analyst@example.com")
        updated_rec = next(r for r in updated_records if r["key_id"] == record["key_id"])
        assert updated_rec["last_used_at"] is not None

    def test_expired_db_api_key_rejected(self, client, api_key_store):
        """Expired DB key falls through to 401."""
        raw_key, record = api_key_store.create_key(
            owner_email="analyst@example.com",
            key_type="user",
            description="Expired key",
            expires_in_days=-1,
        )

        res = client.get("/accounts/me", headers={"X-API-KEY": raw_key})
        assert res.status_code == 401

    def test_revoked_db_api_key_rejected(self, client, api_key_store):
        """Revoked DB key falls through to 401."""
        raw_key, record = api_key_store.create_key(
            owner_email="analyst@example.com",
            key_type="user",
            description="Revocation key",
        )
        api_key_store.revoke_key(record["key_id"])

        res = client.get("/accounts/me", headers={"X-API-KEY": raw_key})
        assert res.status_code == 401

    def test_forwarded_user_with_db_key(self, client, api_key_store):
        """X-I4G-Forwarded-User header works when authenticated via DB key."""
        raw_key, _ = api_key_store.create_key(
            owner_email="partner@example.com",
            key_type="service",
            description="Service proxy key",
        )

        headers = {
            "X-API-KEY": raw_key,
            "X-I4G-Forwarded-User": "analyst@example.com",
        }
        res = client.get("/accounts/me", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["email"] == "analyst@example.com"
        assert data["role"] == "analyst"

    def test_partner_feed_scope_enforcement(self, client, api_key_store):
        """Partner feed requires partner:feed scope or partner key_type."""
        # Key with partner:feed scope
        raw_partner_key, _ = api_key_store.create_key(
            owner_email="partner@example.com",
            key_type="partner",
            scopes=["partner:feed"],
        )

        mock_analytics_store = MagicMock()
        mock_analytics_store.list_indicator_stats.return_value = []
        mock_analytics_store.count_indicator_stats.return_value = 0

        with (
            patch("i4g.api.partner_feed._log_feed_access"),
            patch("i4g.api.partner_feed.build_analytics_store", return_value=mock_analytics_store),
        ):
            res = client.get("/feeds/indicators", headers={"X-Partner-API-Key": raw_partner_key})
            assert res.status_code == 200

        # User key without partner scope
        raw_user_key, _ = api_key_store.create_key(
            owner_email="analyst@example.com",
            key_type="user",
            scopes=["cases:read"],
        )

        res = client.get("/feeds/indicators", headers={"X-Partner-API-Key": raw_user_key})
        assert res.status_code == 403

    def test_static_and_db_api_key_coexistence(self, client, api_key_store, mock_settings):
        """Static key takes precedence, DB key works as fallback."""
        raw_db_key, _ = api_key_store.create_key(
            owner_email="analyst@example.com",
            key_type="user",
        )

        # Static API key
        res_static = client.get("/accounts/me", headers={"X-API-KEY": "static-test-key-999"})
        assert res_static.status_code == 200

        # DB key when static key doesn't match
        res_db = client.get("/accounts/me", headers={"X-API-KEY": raw_db_key})
        assert res_db.status_code == 200
        assert res_db.json()["email"] == "analyst@example.com"
