"""Unit tests for Phase 3 case-investigation endpoints.

Covers:
- GET /cases/{case_id}/activity
- POST /cases/{case_id}/investigate
- GET /cases/{case_id} with investigations array
- GET /investigations/ssi/{scan_id} with linked_cases array
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from i4g.api.app import app
from i4g.store.sql import METADATA
from i4g.store.ssi_store import SsiStore

client = TestClient(app)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_NOW_ISO = "2025-07-01T12:00:00+00:00"


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fresh in-memory SQLite for every test."""
    db_path = tmp_path / "test.db"
    engine = sa.create_engine(f"sqlite:///{db_path}", future=True)
    METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    store = SsiStore(session_factory=factory)

    # Patch everywhere the stores are called
    monkeypatch.setattr("i4g.api.cases.build_ssi_store", lambda **kw: store)
    monkeypatch.setattr("i4g.api.cases.build_sql_session_factory", lambda: factory)
    monkeypatch.setattr("i4g.api.ssi_investigations.build_ssi_store", lambda **kw: store)
    monkeypatch.setattr("i4g.api.ssi_evidence.build_ssi_store", lambda **kw: store)

    yield {"store": store, "factory": factory, "engine": engine}
    engine.dispose()


@pytest.fixture()
def db_ctx(_isolated_db: dict) -> dict:
    """Convenience alias for the test context dict."""
    return _isolated_db


def _seed_case(factory: Any, case_id: str = "case-001", dataset: str = "fraud") -> str:
    """Insert a minimal case row and return case_id."""
    from i4g.store.sql import cases

    with factory() as session:
        session.execute(
            sa.insert(cases).values(
                case_id=case_id,
                dataset=dataset,
                source_type="manual",
                status="in_review",
                classification_status="completed",
                raw_text_sha256="abc123",
            )
        )
        session.commit()
    return case_id


def _seed_scan(store: SsiStore, scan_id: str = "scan-001", **overrides: Any) -> str:
    """Insert a scan and return scan_id."""
    defaults: dict[str, Any] = {
        "url": "https://scam.example.com",
        "scan_type": "full",
        "domain": "scam.example.com",
    }
    defaults.update(overrides)
    store.create_scan(scan_id=scan_id, **defaults)
    return scan_id


def _link_investigation(factory: Any, case_id: str, scan_id: str, trigger_type: str = "auto") -> None:
    """Insert a case_investigations row."""
    from i4g.store.sql import case_investigations

    with factory() as session:
        session.execute(
            sa.insert(case_investigations).values(
                case_id=case_id,
                scan_id=scan_id,
                trigger_type=trigger_type,
            )
        )
        session.commit()


# =========================================================================
# GET /cases/{case_id}/activity
# =========================================================================


class TestCaseActivity:
    """Tests for GET /cases/{case_id}/activity."""

    def test_activity_case_not_found(self, db_ctx: dict) -> None:
        """Returns 404 for unknown case_id."""
        resp = client.get("/cases/nonexistent/activity")
        assert resp.status_code == 404

    def test_activity_empty(self, db_ctx: dict) -> None:
        """Returns classification activity only when no investigations linked."""
        _seed_case(db_ctx["factory"])

        # Mock build_review_store for get_case flow
        resp = client.get("/cases/case-001/activity")
        assert resp.status_code == 200
        data = resp.json()
        assert data["caseId"] == "case-001"
        assert data["hasRunning"] is False
        assert len(data["activities"]) == 1
        assert data["activities"][0]["type"] == "classification"
        assert data["activities"][0]["status"] == "completed"

    def test_activity_with_investigations(self, db_ctx: dict) -> None:
        """Returns investigation activities alongside classification."""
        _seed_case(db_ctx["factory"])
        _seed_scan(db_ctx["store"], scan_id="scan-a")
        _link_investigation(db_ctx["factory"], "case-001", "scan-a", "auto")

        resp = client.get("/cases/case-001/activity")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["activities"]) == 2

        inv_activity = [a for a in data["activities"] if a["type"] == "ssi_investigation"]
        assert len(inv_activity) == 1
        assert inv_activity[0]["scanId"] == "scan-a"
        assert inv_activity[0]["url"] == "https://scam.example.com"

    def test_activity_has_running(self, db_ctx: dict, monkeypatch: pytest.MonkeyPatch) -> None:
        """hasRunning is True when classification is pending."""
        from i4g.store.sql import cases

        _seed_case(db_ctx["factory"])
        # Update classification_status to pending
        with db_ctx["factory"]() as session:
            session.execute(
                sa.update(cases).where(cases.c.case_id == "case-001").values(classification_status="pending")
            )
            session.commit()

        resp = client.get("/cases/case-001/activity")
        assert resp.status_code == 200
        data = resp.json()
        assert data["hasRunning"] is True


# =========================================================================
# POST /cases/{case_id}/investigate
# =========================================================================


class TestInvestigateCaseUrl:
    """Tests for POST /cases/{case_id}/investigate."""

    def test_investigate_case_not_found(self, db_ctx: dict) -> None:
        """Returns 404 for unknown case_id."""
        resp = client.post("/cases/nonexistent/investigate", json={"url": "https://example.com"})
        assert resp.status_code == 404

    @patch("i4g.api.investigations._trigger_cloud_run_service")
    def test_investigate_triggers_scan(self, mock_trigger: MagicMock, db_ctx: dict) -> None:
        """Triggers Cloud Run and links scan to case."""
        _seed_case(db_ctx["factory"])

        # Mock the review store so audit logging doesn't fail
        mock_review_store = MagicMock()
        mock_review_store.get_extended_case.return_value = None
        with patch("i4g.api.cases.build_review_store", return_value=mock_review_store):
            resp = client.post("/cases/case-001/investigate", json={"url": "https://scam.test"})

        assert resp.status_code == 202
        data = resp.json()
        assert data["triggered"] is True
        assert data["status"] == "running"
        assert "scanId" in data
        mock_trigger.assert_called_once()

    @patch("i4g.api.cases.check_url_duplicate")
    def test_investigate_dedup_skip(self, mock_dedup: MagicMock, db_ctx: dict) -> None:
        """Returns dedup info when URL was already investigated."""
        from i4g.services.investigation_dedup import DedupResult

        _seed_case(db_ctx["factory"])
        _seed_scan(db_ctx["store"], scan_id="existing-scan")

        mock_dedup.return_value = DedupResult(
            is_duplicate=True,
            existing_scan_id="existing-scan",
            existing_risk_score=85.0,
            existing_completed_at=datetime(2025, 6, 15, tzinfo=UTC),
            days_since_scan=16,
            reason="Recent scan exists",
        )

        resp = client.post("/cases/case-001/investigate", json={"url": "https://scam.example.com"})
        assert resp.status_code == 202
        data = resp.json()
        assert data["triggered"] is False
        assert data["alreadyInvestigated"] is True
        assert data["existingScanId"] == "existing-scan"

    @patch("i4g.api.investigations._trigger_cloud_run_service")
    @patch("i4g.api.cases.check_url_duplicate")
    def test_investigate_force_bypasses_dedup(
        self, mock_dedup: MagicMock, mock_trigger: MagicMock, db_ctx: dict
    ) -> None:
        """force=True bypasses dedup check."""
        _seed_case(db_ctx["factory"])

        mock_review_store = MagicMock()
        with patch("i4g.api.cases.build_review_store", return_value=mock_review_store):
            resp = client.post("/cases/case-001/investigate", json={"url": "https://scam.test", "force": True})

        assert resp.status_code == 202
        mock_dedup.assert_not_called()
        mock_trigger.assert_called_once()


# =========================================================================
# SsiStore.get_case_investigations / get_scan_linked_cases
# =========================================================================


class TestSsiStoreCaseInvestigations:
    """Tests for SsiStore case-investigation query methods."""

    def test_get_case_investigations_empty(self, db_ctx: dict) -> None:
        """Returns empty list when no investigations linked."""
        result = db_ctx["store"].get_case_investigations("case-999")
        assert result == []

    def test_get_case_investigations_returns_rows(self, db_ctx: dict) -> None:
        """Returns joined scan data for linked investigations."""
        _seed_case(db_ctx["factory"])
        _seed_scan(db_ctx["store"], scan_id="scan-x", url="https://phish.test")
        _link_investigation(db_ctx["factory"], "case-001", "scan-x", "manual")

        rows = db_ctx["store"].get_case_investigations("case-001")
        assert len(rows) == 1
        assert rows[0]["scan_id"] == "scan-x"
        assert rows[0]["url"] == "https://phish.test"
        assert rows[0]["trigger_type"] == "manual"

    def test_get_scan_linked_cases_empty(self, db_ctx: dict) -> None:
        """Returns empty list when scan has no linked cases."""
        result = db_ctx["store"].get_scan_linked_cases("scan-999")
        assert result == []

    def test_get_scan_linked_cases_returns_rows(self, db_ctx: dict) -> None:
        """Returns case data for a scan linked to cases."""
        _seed_case(db_ctx["factory"])
        _seed_scan(db_ctx["store"], scan_id="scan-y")
        _link_investigation(db_ctx["factory"], "case-001", "scan-y", "auto")

        rows = db_ctx["store"].get_scan_linked_cases("scan-y")
        assert len(rows) == 1
        assert rows[0]["case_id"] == "case-001"
        assert rows[0]["trigger_type"] == "auto"
        assert rows[0]["dataset"] == "fraud"
        assert rows[0]["status"] == "in_review"


# =========================================================================
# GET /investigations/ssi/{scan_id} with linked_cases
# =========================================================================


class TestInvestigationDetailLinkedCases:
    """Tests that GET /investigations/ssi/{scan_id} includes linked_cases."""

    def test_investigation_detail_includes_linked_cases(self, db_ctx: dict) -> None:
        """Investigation detail response includes linked_cases array."""
        _seed_case(db_ctx["factory"])
        scan_id = _seed_scan(db_ctx["store"], scan_id="scan-lc")
        _link_investigation(db_ctx["factory"], "case-001", scan_id, "auto")

        resp = client.get(f"/investigations/ssi/{scan_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "linkedCases" in data
        assert len(data["linkedCases"]) == 1
        assert data["linkedCases"][0]["caseId"] == "case-001"

    def test_investigation_detail_no_linked_cases(self, db_ctx: dict) -> None:
        """Investigation detail returns empty linkedCases when none linked."""
        scan_id = _seed_scan(db_ctx["store"], scan_id="scan-alone")

        resp = client.get(f"/investigations/ssi/{scan_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["linkedCases"] == []
