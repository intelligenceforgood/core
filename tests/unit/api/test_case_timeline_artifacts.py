"""Unit tests for the timeline and artifacts enrichment (Phase 1).

Tests cover:
- POST /cases/{case_id}/timeline — batch timeline event creation
- GET /cases/{case_id} — source_documents appear as artifacts
- GET /cases/{case_id} — SSI timeline events render with proper descriptions
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from fastapi.testclient import TestClient

from i4g.api.app import app
from i4g.store.review_store import ReviewStore
from i4g.store.sql import METADATA, source_documents

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Redirect all SQL access to a disposable per-test SQLite database."""
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


def _create_case(**overrides: object) -> str:
    """Create a case and return its id."""
    payload = {
        "dataset": "ssi",
        "source_type": "ssi_investigation",
        "source_url": f"https://timeline-test-{uuid.uuid4().hex[:8]}.example.com",
        "metadata": {"title": "Test Case"},
    }
    payload.update(overrides)
    resp = client.post("/cases", json=payload)
    assert resp.status_code == 201
    return resp.json()["caseId"]


# ---------------------------------------------------------------------------
# POST /cases/{case_id}/timeline
# ---------------------------------------------------------------------------


class TestTimelineEndpoint:
    """Tests for ``POST /cases/{case_id}/timeline``."""

    def test_add_single_event(self) -> None:
        """A single timeline event is created successfully."""
        case_id = _create_case()
        resp = client.post(
            f"/cases/{case_id}/timeline",
            json={
                "events": [
                    {
                        "type": "investigation_submitted",
                        "description": "SSI investigation initiated for https://scam.example.com",
                        "actor": "ssi-agent",
                    }
                ]
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["caseId"] == case_id
        assert data["created"] == 1

    def test_add_multiple_events(self) -> None:
        """Multiple timeline events are created in a single batch."""
        case_id = _create_case()
        resp = client.post(
            f"/cases/{case_id}/timeline",
            json={
                "events": [
                    {
                        "type": "investigation_submitted",
                        "description": "SSI investigation initiated",
                        "actor": "ssi-agent",
                        "timestamp": "2026-02-28T10:00:00Z",
                    },
                    {
                        "type": "classification_completed",
                        "description": "Classified as Investment Scam (risk score: 85)",
                        "actor": "ssi-agent",
                        "timestamp": "2026-02-28T10:05:00Z",
                    },
                    {
                        "type": "wallets_harvested",
                        "description": "Found 3 wallet addresses (ETH, BTC)",
                        "actor": "ssi-agent",
                    },
                    {
                        "type": "evidence_collected",
                        "description": "Collected 12 evidence artifacts",
                        "actor": "ssi-agent",
                    },
                    {
                        "type": "report_generated",
                        "description": "Investigation report generated",
                        "actor": "ssi-agent",
                    },
                    {
                        "type": "case_created",
                        "description": "Case created from SSI investigation abc-123",
                        "actor": "ssi-agent",
                    },
                ]
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["created"] == 6

    def test_timeline_events_appear_in_case_detail(self) -> None:
        """Timeline events appear in the GET /cases/{case_id} response."""
        case_id = _create_case()
        client.post(
            f"/cases/{case_id}/timeline",
            json={
                "events": [
                    {
                        "type": "investigation_submitted",
                        "description": "SSI investigation initiated for https://scam.example.com",
                        "actor": "ssi-agent",
                    },
                    {
                        "type": "case_created",
                        "description": "Case created from SSI investigation inv-001",
                        "actor": "ssi-agent",
                    },
                ]
            },
        )

        resp = client.get(f"/cases/{case_id}")
        assert resp.status_code == 200
        detail = resp.json()
        timeline = detail["timeline"]
        # Should contain the 2 events we added + 1 auto "enqueued" event
        assert len(timeline) >= 2

        descriptions = [e["description"] for e in timeline]
        assert any("SSI investigation initiated" in d for d in descriptions)
        assert any("Case created from SSI investigation" in d for d in descriptions)

    def test_timeline_nonexistent_case(self) -> None:
        """POST returns 404 for a nonexistent case_id."""
        resp = client.post(
            "/cases/nonexistent-case-id/timeline",
            json={
                "events": [
                    {
                        "type": "test",
                        "description": "Should fail",
                        "actor": "test",
                    }
                ]
            },
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Artifacts from source_documents
# ---------------------------------------------------------------------------


class TestArtifactsFromEvidence:
    """Tests for source_documents appearing in the case detail artifacts."""

    def test_source_documents_appear_as_artifacts(self, _isolated_db) -> None:
        """Evidence files in source_documents show up in the artifacts list."""
        case_id = _create_case()
        engine = _isolated_db

        # Insert source_documents rows directly (simulating evidence upload)
        doc_id_1 = str(uuid.uuid4())
        doc_id_2 = str(uuid.uuid4())
        with engine.connect() as conn:
            conn.execute(
                sa.insert(source_documents).values(
                    document_id=doc_id_1,
                    case_id=case_id,
                    title="investigation.json",
                    mime_type="application/json",
                    source_url=None,
                    chunk_index=0,
                    chunk_count=1,
                )
            )
            conn.execute(
                sa.insert(source_documents).values(
                    document_id=doc_id_2,
                    case_id=case_id,
                    title="screenshot.png",
                    mime_type="image/png",
                    source_url=None,
                    chunk_index=0,
                    chunk_count=1,
                )
            )
            conn.commit()

        resp = client.get(f"/cases/{case_id}")
        assert resp.status_code == 200
        detail = resp.json()
        artifacts = detail["artifacts"]
        assert len(artifacts) >= 2

        artifact_names = [a["name"] for a in artifacts]
        assert "investigation.json" in artifact_names
        assert "screenshot.png" in artifact_names

        # Check types
        json_art = next(a for a in artifacts if a["name"] == "investigation.json")
        assert json_art["type"] == "data"

        png_art = next(a for a in artifacts if a["name"] == "screenshot.png")
        assert png_art["type"] == "screenshot"

        # Check download URL format
        assert f"/cases/{case_id}/evidence/" in json_art["url"]

    def test_no_artifacts_when_no_documents(self) -> None:
        """A case with no source_documents has an empty artifacts list."""
        case_id = _create_case()
        resp = client.get(f"/cases/{case_id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["artifacts"] == []

    def test_ssi_pdf_report_artifact(self) -> None:
        """Cases with ssi_investigation_id in metadata include a PDF report artifact."""
        inv_id = str(uuid.uuid4())
        case_id = _create_case(
            metadata={"title": "SSI Case", "ssi_investigation_id": inv_id}
        )
        resp = client.get(f"/cases/{case_id}")
        assert resp.status_code == 200
        detail = resp.json()
        artifacts = detail["artifacts"]
        pdf_arts = [a for a in artifacts if a["type"] == "report"]
        assert len(pdf_arts) == 1
        pdf = pdf_arts[0]
        assert pdf["name"] == "Investigation Report (PDF)"
        assert pdf["url"] == f"/ssi/report/{inv_id}"
        assert pdf["metadata"]["mime_type"] == "application/pdf"

    def test_no_pdf_artifact_without_ssi_metadata(self) -> None:
        """Cases without ssi_investigation_id do not include a PDF report artifact."""
        case_id = _create_case(metadata={"title": "Regular Case"})
        resp = client.get(f"/cases/{case_id}")
        assert resp.status_code == 200
        detail = resp.json()
        pdf_arts = [a for a in detail["artifacts"] if a["type"] == "report"]
        assert len(pdf_arts) == 0


# ---------------------------------------------------------------------------
# Timeline description formatting
# ---------------------------------------------------------------------------


class TestTimelineFormatting:
    """Tests for the improved timeline description rendering."""

    def test_ssi_event_uses_description_from_payload(self) -> None:
        """SSI events with a 'description' payload key render that directly."""
        case_id = _create_case()
        client.post(
            f"/cases/{case_id}/timeline",
            json={
                "events": [
                    {
                        "type": "wallets_harvested",
                        "description": "Found 5 wallet addresses (ETH, BTC, USDT)",
                        "actor": "ssi-agent",
                    }
                ]
            },
        )
        resp = client.get(f"/cases/{case_id}")
        detail = resp.json()
        wallet_event = next(
            (e for e in detail["timeline"] if e["type"] == "wallets_harvested"),
            None,
        )
        assert wallet_event is not None
        assert wallet_event["description"] == "Found 5 wallet addresses (ETH, BTC, USDT)"
        assert wallet_event["actor"] == "ssi-agent"
