"""Unit tests for the PhishDestroy /discoveries API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from i4g.api.auth import require_token
from i4g.store.domain_discovery_store import DomainDiscoveryStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_discovery_store(tmp_path) -> DomainDiscoveryStore:
    return DomainDiscoveryStore(db_path=str(tmp_path / "disc_api_test.db"))


def _insert_match(store: DomainDiscoveryStore, domain: str = "phish.example.com") -> dict:
    return store.insert(
        domain=domain,
        source="merklemap.tail",
        seen_at=datetime(2026, 4, 20, tzinfo=UTC),
        filter_match=True,
        filter_reason="brand_regex",
    )


@pytest.fixture()
def client(tmp_path):
    """TestClient with auth bypassed and store wired to a temp SQLite db."""
    store = _make_discovery_store(tmp_path)
    from i4g.api.app import app

    app.dependency_overrides[require_token] = lambda: {"sub": "test@test.com", "role": "analyst"}
    with patch("i4g.api.phishdestroy_discoveries.build_domain_discovery_store", return_value=store):
        yield TestClient(app), store
    app.dependency_overrides.pop(require_token, None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestListDiscoveries:
    def test_list_returns_only_filter_matches_and_excludes_dismissed(self, tmp_path):
        store = _make_discovery_store(tmp_path)
        from i4g.api.app import app

        app.dependency_overrides[require_token] = lambda: {"sub": "t", "role": "analyst"}
        try:
            with patch("i4g.api.phishdestroy_discoveries.build_domain_discovery_store", return_value=store):
                c = TestClient(app)
                # Insert one match and one non-match
                match_row = _insert_match(store)
                store.insert(
                    domain="safe.com",
                    source="merklemap.tail",
                    seen_at=datetime(2026, 4, 20, tzinfo=UTC),
                    filter_match=False,
                )
                # Dismiss the match row
                store.dismiss(match_row["discovery_id"], reason="test")

                resp = c.get("/discoveries")
                assert resp.status_code == 200
                data = resp.json()
                assert data["total"] == 0
                assert data["items"] == []
        finally:
            app.dependency_overrides.pop(require_token, None)

    def test_list_pagination_limit_offset_and_total(self, client):
        c, store = client
        t = datetime(2026, 4, 20, tzinfo=UTC)
        for i in range(5):
            store.insert(domain=f"phish{i}.com", source="m", seen_at=t, filter_match=True)

        resp = c.get("/discoveries?limit=2&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert data["limit"] == 2
        assert data["offset"] == 0
        assert len(data["items"]) == 2

    def test_list_since_filter_applied(self, client):
        c, store = client
        t_old = datetime(2026, 3, 1, tzinfo=UTC)
        t_new = datetime(2026, 4, 20, tzinfo=UTC)
        store.insert(domain="old.com", source="m", seen_at=t_old, filter_match=True)
        store.insert(domain="new.com", source="m", seen_at=t_new, filter_match=True)

        resp = c.get("/discoveries?since=2026-04-01T00:00:00Z")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["domain"] == "new.com"


class TestEnqueueDiscovery:
    def test_enqueue_404_for_unknown_discovery(self, client):
        c, _store = client
        resp = c.post("/discoveries/no-such-id/enqueue")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Discovery not found"

    def test_enqueue_409_when_already_enqueued(self, client):
        c, store = client
        row = _insert_match(store)
        store.mark_enqueued(row["discovery_id"], "existing-scan")

        resp = c.post(f"/discoveries/{row['discovery_id']}/enqueue")
        assert resp.status_code == 409
        assert resp.json()["detail"] == "Discovery already enqueued"

    def test_enqueue_creates_ssi_scan_and_marks_discovery(self, client):
        c, store = client
        row = _insert_match(store)

        with patch(
            "i4g.api.phishdestroy_discoveries._trigger_ssi_scan",
            return_value="scan-abc-123",
        ):
            resp = c.post(f"/discoveries/{row['discovery_id']}/enqueue")

        assert resp.status_code == 200
        data = resp.json()
        assert data["discoveryId"] == row["discovery_id"]
        assert data["enqueuedScanId"] == "scan-abc-123"

        # Discovery row should now carry the scan id in the list
        matches = store.list_recent_matches()
        assert matches[0]["enqueued_scan_id"] == "scan-abc-123"


class TestDismissDiscovery:
    def test_dismiss_404_for_unknown_discovery(self, client):
        c, _store = client
        resp = c.post("/discoveries/no-such-id/dismiss", json={})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Discovery not found"

    def test_dismiss_409_when_already_dismissed(self, client):
        c, store = client
        row = _insert_match(store)
        store.dismiss(row["discovery_id"], reason="first time")

        resp = c.post(f"/discoveries/{row['discovery_id']}/dismiss", json={"reason": "again"})
        assert resp.status_code == 409
        assert resp.json()["detail"] == "Discovery already dismissed"

    def test_dismiss_records_reason_and_excludes_from_list(self, client):
        c, store = client
        row = _insert_match(store)

        resp = c.post(f"/discoveries/{row['discovery_id']}/dismiss", json={"reason": "false positive"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["dismissReason"] == "false positive"
        assert data["dismissedAt"] is not None

        # Should not appear in subsequent list
        list_resp = c.get("/discoveries")
        assert list_resp.status_code == 200
        ids = [it["discoveryId"] for it in list_resp.json()["items"]]
        assert row["discovery_id"] not in ids

    def test_dismiss_reason_too_long_returns_422(self, client):
        c, store = client
        row = _insert_match(store)
        resp = c.post(
            f"/discoveries/{row['discovery_id']}/dismiss",
            json={"reason": "x" * 501},
        )
        assert resp.status_code == 422


class TestRoutesRequireToken:
    def test_routes_require_token_when_auth_enabled(self, tmp_path):
        """Routes are gated by require_token: when it raises 401, endpoints return 401."""
        from fastapi import HTTPException as FastAPIHTTPException

        store = _make_discovery_store(tmp_path)
        from i4g.api.app import app

        def _deny():
            raise FastAPIHTTPException(status_code=401, detail="Unauthorized")

        app.dependency_overrides[require_token] = _deny
        try:
            with patch("i4g.api.phishdestroy_discoveries.build_domain_discovery_store", return_value=store):
                c = TestClient(app, raise_server_exceptions=False)
                resp = c.get("/discoveries")
            assert resp.status_code == 401
        finally:
            app.dependency_overrides.pop(require_token, None)
