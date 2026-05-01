"""Unit tests for the PhishDestroy /actors API endpoints RBAC and audit paths."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from i4g.api.auth import require_token
from i4g.store.threat_actor_store import ThreatActorStore


def _make_actor_store(tmp_path) -> ThreatActorStore:
    return ThreatActorStore(db_path=str(tmp_path / "actor_api_test.db"))


def _insert_actor(store: ThreatActorStore, has_pii: bool = False) -> dict:
    return store.create(
        display_name="Test Actor",
        real_name="John Doe" if has_pii else None,
    )


@pytest.fixture()
def client(tmp_path):
    """TestClient with store wired to a temp SQLite db. Auth is not bypassed globally so we can override it per test."""
    store = _make_actor_store(tmp_path)
    from i4g.api.app import app

    with patch("i4g.api.phishdestroy_actors.build_threat_actor_store", return_value=store):
        yield TestClient(app), store, app


class TestListActorsRBAC:
    def test_analyst_cannot_see_pii(self, client):
        c, store, app = client
        _insert_actor(store, has_pii=True)

        app.dependency_overrides[require_token] = lambda: {"username": "user1", "role": "analyst"}
        try:
            resp = c.get("/actors")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["items"]) == 1
            assert data["items"][0]["realName"] is None
        finally:
            app.dependency_overrides.pop(require_token, None)

    def test_senior_analyst_without_reason_gets_400(self, client):
        c, store, app = client
        _insert_actor(store, has_pii=True)

        app.dependency_overrides[require_token] = lambda: {"username": "user1", "role": "senior_analyst"}
        try:
            resp = c.get("/actors")
            assert resp.status_code == 400
            assert "Reason code required" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(require_token, None)

    def test_senior_analyst_with_reason_sees_pii_and_audits(self, client):
        c, store, app = client
        actor_row = _insert_actor(store, has_pii=True)

        app.dependency_overrides[require_token] = lambda: {"username": "user1", "role": "senior_analyst"}
        try:
            with patch("i4g.api.phishdestroy_actors._log_pii_access") as mock_audit:
                resp = c.get("/actors?reason=Investigation123")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["items"]) == 1
                assert data["items"][0]["realName"] == "John Doe"

                mock_audit.assert_called_once_with("user1", "threat_actor", actor_row["actor_id"], "Investigation123")
        finally:
            app.dependency_overrides.pop(require_token, None)


class TestGetActorRBAC:
    def test_analyst_cannot_see_pii(self, client):
        c, store, app = client
        actor_row = _insert_actor(store, has_pii=True)

        app.dependency_overrides[require_token] = lambda: {"username": "user1", "role": "analyst"}
        try:
            resp = c.get(f"/actors/{actor_row['actor_id']}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["actor"]["realName"] is None
        finally:
            app.dependency_overrides.pop(require_token, None)

    def test_senior_analyst_without_reason_gets_400(self, client):
        c, store, app = client
        actor_row = _insert_actor(store, has_pii=True)

        app.dependency_overrides[require_token] = lambda: {"username": "user1", "role": "senior_analyst"}
        try:
            resp = c.get(f"/actors/{actor_row['actor_id']}")
            assert resp.status_code == 400
            assert "Reason code required" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(require_token, None)

    def test_senior_analyst_with_reason_sees_pii_and_audits(self, client):
        c, store, app = client
        actor_row = _insert_actor(store, has_pii=True)

        app.dependency_overrides[require_token] = lambda: {"username": "user1", "role": "senior_analyst"}
        try:
            with patch("i4g.api.phishdestroy_actors._log_pii_access") as mock_audit:
                resp = c.get(f"/actors/{actor_row['actor_id']}", headers={"x-reason": "HeaderReason"})
                assert resp.status_code == 200
                data = resp.json()
                assert data["actor"]["realName"] == "John Doe"

                mock_audit.assert_called_once_with("user1", "threat_actor", actor_row["actor_id"], "HeaderReason")
        finally:
            app.dependency_overrides.pop(require_token, None)
