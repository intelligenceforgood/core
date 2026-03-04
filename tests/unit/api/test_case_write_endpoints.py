"""Unit tests for the programmatic case creation endpoints (Phase 2.3).

These endpoints are called by the SSI ScanStore to push investigation
results into the core platform.

Tests use a disposable in-memory SQLite database via monkeypatch so they
never pollute the development/production datastore.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from fastapi.testclient import TestClient

from i4g.api.app import app
from i4g.store.review_store import ReviewStore
from i4g.store.sql import METADATA

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Redirect all SQL access to a disposable per-test SQLite database.

    Patches ``build_sql_session_factory`` and ``build_review_store`` in
    the ``cases`` module so each test gets a fresh, empty database.
    """
    db_path = tmp_path / "test.db"
    engine = sa.create_engine(f"sqlite:///{db_path}", future=True)
    METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    monkeypatch.setattr("i4g.api.cases.build_sql_session_factory", lambda **kw: factory)
    monkeypatch.setattr(
        "i4g.api.cases.build_review_store",
        lambda **kw: ReviewStore(session_factory=factory),
    )
    yield engine
    engine.dispose()


# ---------------------------------------------------------------------------
# POST /cases
# ---------------------------------------------------------------------------


class TestCreateCase:
    """Tests for ``POST /cases``."""

    def test_create_case_success(self) -> None:
        """A valid payload creates a case and returns the new case_id."""
        payload = {
            "dataset": "ssi",
            "source_type": "ssi_investigation",
            "source_url": "https://scam.example.com",
            "risk_score": 85.0,
            "metadata": {"ssi_investigation_id": "test-inv-001"},
        }
        resp = client.post("/cases", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert "caseId" in data
        assert data["created"] is True

    def test_create_case_dedup_returns_existing(self) -> None:
        """Submitting the same content twice returns the existing case_id."""
        payload = {
            "dataset": "ssi",
            "source_type": "ssi_investigation",
            "source_url": "https://dedup-test.example.com",
            "metadata": {"dedup": "test"},
        }
        resp1 = client.post("/cases", json=payload)
        assert resp1.status_code == 201
        case_id_1 = resp1.json()["caseId"]

        resp2 = client.post("/cases", json=payload)
        assert resp2.status_code == 201
        data2 = resp2.json()
        assert data2["caseId"] == case_id_1
        assert data2["created"] is False

    def test_create_case_with_classification(self) -> None:
        """A case with classification_result is created successfully."""
        payload = {
            "dataset": "ssi",
            "source_type": "ssi_investigation",
            "classification_result": {
                "intent": "investment_scam",
                "risk_score": 92.0,
            },
            "risk_score": 92.0,
            "metadata": {"my_unique_test": "classification_test"},
        }
        resp = client.post("/cases", json=payload)
        assert resp.status_code == 201

    def test_create_case_missing_dataset(self) -> None:
        """Missing required ``dataset`` field returns 422."""
        resp = client.post("/cases", json={"source_type": "test"})
        assert resp.status_code == 422  # Validation error


# ---------------------------------------------------------------------------
# PATCH /cases/{case_id}
# ---------------------------------------------------------------------------


class TestUpdateCase:
    """Tests for ``PATCH /cases/{case_id}``."""

    def _create_case(self) -> str:
        """Create a case and return its id."""
        resp = client.post(
            "/cases",
            json={
                "dataset": "ssi",
                "source_type": "ssi_investigation",
                "source_url": f"https://patch-test-{id(self)}.example.com",
                "metadata": {"unique_for": str(id(self))},
            },
        )
        return resp.json()["caseId"]

    def test_update_classification(self) -> None:
        """PATCH updates classification fields on an existing case."""
        case_id = self._create_case()
        resp = client.patch(
            f"/cases/{case_id}",
            json={
                "classification_result": {"intent": "pig_butchering"},
                "classification_status": "completed",
                "risk_score": 95.0,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["updated"] is True

    def test_update_nonexistent_case(self) -> None:
        """PATCH returns 404 for a nonexistent case_id."""
        resp = client.patch(
            "/cases/nonexistent-case-id-999",
            json={"status": "closed"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /cases/{case_id}/entities/batch
# ---------------------------------------------------------------------------


class TestBatchEntities:
    """Tests for ``POST /cases/{case_id}/entities/batch``."""

    def _create_case(self) -> str:
        """Create a case and return its id."""
        resp = client.post(
            "/cases",
            json={
                "dataset": "ssi",
                "source_type": "ssi_investigation",
                "source_url": f"https://entity-test-{id(self)}.example.com",
                "metadata": {"entity_test": str(id(self))},
            },
        )
        return resp.json()["caseId"]

    def test_batch_create_entities(self) -> None:
        """Batch-create entities returns count of created rows."""
        case_id = self._create_case()
        resp = client.post(
            f"/cases/{case_id}/entities/batch",
            json={
                "entities": [
                    {
                        "entity_type": "domain",
                        "canonical_value": "scam.example.com",
                        "confidence": 1.0,
                    },
                    {
                        "entity_type": "ip_address",
                        "canonical_value": "1.2.3.4",
                        "confidence": 0.9,
                        "metadata": {"source": "dns"},
                    },
                ]
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["caseId"] == case_id
        assert data["created"] == 2

    def test_batch_entities_nonexistent_case(self) -> None:
        """Batch-create returns 404 for a nonexistent case_id."""
        resp = client.post(
            "/cases/fake-case/entities/batch",
            json={"entities": [{"entity_type": "domain", "canonical_value": "x.com"}]},
        )
        assert resp.status_code == 404

    def test_batch_entities_upsert(self) -> None:
        """Submitting the same entity twice updates rather than duplicating."""
        case_id = self._create_case()
        entity_payload = {
            "entities": [
                {"entity_type": "domain", "canonical_value": "dup.example.com", "confidence": 0.5}
            ]
        }
        resp1 = client.post(f"/cases/{case_id}/entities/batch", json=entity_payload)
        assert resp1.status_code == 201

        # Re-submit same entity with higher confidence
        entity_payload["entities"][0]["confidence"] = 0.95
        resp2 = client.post(f"/cases/{case_id}/entities/batch", json=entity_payload)
        assert resp2.status_code == 201
        assert resp2.json()["created"] == 1


# ---------------------------------------------------------------------------
# POST /cases/{case_id}/indicators/batch
# ---------------------------------------------------------------------------


class TestBatchIndicators:
    """Tests for ``POST /cases/{case_id}/indicators/batch``."""

    def _create_case(self) -> str:
        """Create a case and return its id."""
        resp = client.post(
            "/cases",
            json={
                "dataset": "ssi",
                "source_type": "ssi_investigation",
                "source_url": f"https://indicator-test-{id(self)}.example.com",
                "metadata": {"indicator_test": str(id(self))},
            },
        )
        return resp.json()["caseId"]

    def test_batch_create_indicators(self) -> None:
        """Batch-create indicators returns count of created rows."""
        case_id = self._create_case()
        resp = client.post(
            f"/cases/{case_id}/indicators/batch",
            json={
                "indicators": [
                    {
                        "category": "crypto_wallet",
                        "type": "ETH",
                        "number": "0xabc123",
                        "dataset": "ssi",
                        "confidence": 0.9,
                    },
                    {
                        "category": "crypto_wallet",
                        "type": "BTC",
                        "number": "bc1qtest",
                        "dataset": "ssi",
                        "confidence": 0.85,
                    },
                ]
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["caseId"] == case_id
        assert data["created"] == 2

    def test_batch_indicators_nonexistent_case(self) -> None:
        """Batch-create returns 404 for a nonexistent case_id."""
        resp = client.post(
            "/cases/fake-case/indicators/batch",
            json={
                "indicators": [
                    {"category": "crypto_wallet", "type": "ETH", "number": "0x1"}
                ]
            },
        )
        assert resp.status_code == 404
