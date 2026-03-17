"""E2E smoke test: Ingest case -> auto-investigate -> view result on case.

This test exercises the full SSI-case integration flow:

1. Bootstrap a minimal case with a suspicious URL in source_documents
2. Run linkage extraction to create URL indicators
3. Verify URL indicator exists for the case
4. Run auto-investigate to trigger SSI investigation (mocked SSI service)
5. Verify case_investigations row created
6. Query case detail API for investigation data
7. Query case activity API for running/completed status

The SSI service trigger is mocked via ``httpx.Client`` so the test
runs without a live SSI instance.

Requirements:
    - Local environment (SQLite)
    - ``I4G_AUTO_INVESTIGATE__ENABLED=true``
    - ``I4G_LLM__PROVIDER=mock``

Usage::

    conda run -n i4g I4G_PROJECT_ROOT=$PWD I4G_ENV=local \\
        I4G_AUTO_INVESTIGATE__ENABLED=true \\
        I4G_LLM__PROVIDER=mock \\
        pytest tests/adhoc/test_ssi_case_integration_e2e.py -v

For real SSI (manual validation only)::

    conda run -n i4g I4G_PROJECT_ROOT=$PWD I4G_ENV=local \\
        I4G_AUTO_INVESTIGATE__ENABLED=true \\
        I4G_SSI__SERVICE_URL=http://localhost:8100 \\
        pytest tests/adhoc/test_ssi_case_integration_e2e.py -v -k real_ssi
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from i4g.api.app import app
from i4g.store.review_store import ReviewStore
from i4g.store.sql import (
    METADATA,
    case_investigations,
    cases,
    indicators,
    review_queue,
    scam_records,
    site_scans,
    source_documents,
)
from i4g.store.ssi_store import SsiStore

CASE_ID = f"e2e-ssi-{uuid.uuid4().hex[:8]}"
SUSPICIOUS_URL = "https://suspicious-giveaway.example.com/claim"
CASE_NARRATIVE = (
    "The victim reported visiting https://suspicious-giveaway.example.com/claim "
    "where they were asked to connect their wallet and send 2 ETH as a "
    "'verification deposit'. The site mimicked a well-known exchange."
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Create a fresh SQLite database for each test."""
    db_path = tmp_path / "e2e.db"
    engine = sa.create_engine(f"sqlite:///{db_path}", future=True)
    METADATA.create_all(engine, checkfirst=True)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    store = SsiStore(session_factory=factory)
    review_store = ReviewStore(session_factory=factory)

    # Patch stores/factories used by API handlers and worker jobs
    monkeypatch.setattr("i4g.api.cases.build_ssi_store", lambda **kw: store)
    monkeypatch.setattr("i4g.api.cases.build_sql_session_factory", lambda: factory)
    monkeypatch.setattr("i4g.api.cases.build_review_store", lambda **kw: review_store)
    monkeypatch.setattr("i4g.api.ssi_investigations.build_ssi_store", lambda **kw: store)
    monkeypatch.setattr("i4g.api.ssi_evidence.build_ssi_store", lambda **kw: store)

    # Patch auto_investigate's session factory
    monkeypatch.setattr(
        "i4g.worker.jobs.auto_investigate.build_sql_session_factory",
        lambda: factory,
    )

    # Patch build_ssi_store inside auto_investigate._trigger_investigation
    monkeypatch.setattr("i4g.services.factories.build_ssi_store", lambda **kw: store)

    yield {"store": store, "factory": factory, "engine": engine}
    engine.dispose()


@pytest.fixture()
def db_ctx(_isolated_db: dict[str, Any]) -> dict[str, Any]:
    """Convenience alias for the test context."""
    return _isolated_db


def _seed_case_with_url(factory: sessionmaker, case_id: str = CASE_ID) -> str:
    """Insert a case row, review_queue entry, scam_record, and a source_document."""
    review_id = f"rev-{uuid.uuid4().hex[:8]}"
    with factory() as session:
        session.execute(
            sa.insert(cases).values(
                case_id=case_id,
                dataset="batch",
                source_type="manual",
                status="open",
                classification_status="completed",
                raw_text_sha256=f"sha-{uuid.uuid4().hex[:16]}",
            )
        )
        session.execute(
            sa.insert(scam_records).values(
                case_id=case_id,
                text=CASE_NARRATIVE,
                classification="crypto_investment",
                confidence=0.9,
            )
        )
        session.execute(
            sa.insert(review_queue).values(
                review_id=review_id,
                case_id=case_id,
                status="in_review",
                priority="high",
                queued_at=datetime.now(UTC),
            )
        )
        session.execute(
            sa.insert(source_documents).values(
                document_id=str(uuid.uuid4()),
                case_id=case_id,
                title="Victim Report",
                text=CASE_NARRATIVE,
                chunk_index=0,
                chunk_count=1,
            )
        )
        session.commit()
    return case_id


def _mock_llm_response() -> str:
    """Return a mock LLM JSON response containing the suspicious URL."""
    return '[{"type": "url", ' f'"value": "{SUSPICIOUS_URL}", ' '"confidence": 0.95}]'


# ---------------------------------------------------------------------------
# Step tests — run in order via class
# ---------------------------------------------------------------------------

client = TestClient(app)


class TestSSICaseIntegrationE2E:
    """Full flow: seed case -> extract URLs -> auto-investigate -> verify API."""

    def test_step1_seed_case_and_extract_urls(self, db_ctx: dict[str, Any]) -> None:
        """Seed a case with a URL narrative and run linkage extraction."""
        factory = db_ctx["factory"]
        case_id = _seed_case_with_url(factory)

        # Mock the LLM client
        mock_llm = MagicMock()
        mock_llm.generate.return_value = _mock_llm_response()

        from i4g.task_status import TaskStatusReporter
        from i4g.worker.jobs.linkage_extract import _run_case_url_extraction

        reporter = TaskStatusReporter()

        with factory() as session:
            successes, failures = _run_case_url_extraction(session, mock_llm, reporter=reporter)

        assert successes >= 1, f"Expected at least 1 success, got {successes}"
        assert failures == 0, f"Expected 0 failures, got {failures}"

        # Verify URL indicator was created
        with factory() as session:
            row = session.execute(
                sa.select(indicators.c.indicator_id, indicators.c.number).where(
                    indicators.c.case_id == case_id,
                    indicators.c.category == "url",
                    indicators.c.type == "url",
                )
            ).fetchone()

        assert row is not None, "URL indicator not created"
        assert SUSPICIOUS_URL in row.number
        print(f"  [PASS] URL indicator created: {row.number}")

    def test_step2_auto_investigate_triggers(self, db_ctx: dict[str, Any]) -> None:
        """Seed case + URL indicator, then run auto-investigate with mocked SSI."""
        factory = db_ctx["factory"]
        case_id = _seed_case_with_url(factory)

        # Pre-create the URL indicator (simulates linkage_extract output)
        with factory() as session:
            session.execute(
                sa.insert(indicators).values(
                    indicator_id=str(uuid.uuid4()),
                    case_id=case_id,
                    category="url",
                    type="url",
                    number=SUSPICIOUS_URL,
                    item=SUSPICIOUS_URL.lower(),
                    status="active",
                    confidence=0.95,
                    dataset="batch",
                )
            )
            session.commit()

        # Mock the SSI HTTP trigger
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        mock_http_client = MagicMock()
        mock_http_client.__enter__ = MagicMock(return_value=mock_http_client)
        mock_http_client.__exit__ = MagicMock(return_value=False)
        mock_http_client.post.return_value = mock_response

        with patch("i4g.worker.jobs.auto_investigate.get_settings") as mock_settings:
            settings = MagicMock()
            settings.auto_investigate.enabled = True
            settings.auto_investigate.staleness_days = 30
            settings.auto_investigate.max_concurrent = 10
            settings.auto_investigate.domain_blocklist = []
            settings.ssi.service_url = "http://mock-ssi:8100"
            settings.runtime.log_level = "WARNING"
            mock_settings.return_value = settings

            with patch("httpx.Client", return_value=mock_http_client):
                from i4g.worker.jobs.auto_investigate import main as auto_investigate_main

                rc = auto_investigate_main(dry_run=False, limit=10)

        assert rc == 0, f"auto_investigate returned {rc}"

        # Verify case_investigations row
        with factory() as session:
            ci_row = session.execute(
                sa.select(case_investigations).where(case_investigations.c.case_id == case_id)
            ).fetchone()

        assert ci_row is not None, "case_investigations row not created"
        assert ci_row.trigger_type == "auto"
        print(f"  [PASS] case_investigations linked: scan_id={ci_row.scan_id}")

        # Verify site_scans row was created
        with factory() as session:
            scan_row = session.execute(
                sa.select(site_scans.c.scan_id, site_scans.c.url).where(site_scans.c.scan_id == ci_row.scan_id)
            ).fetchone()

        assert scan_row is not None, "site_scans row not created"
        print(f"  [PASS] site_scans row: url={scan_row.url}")

    def test_step3_case_detail_includes_investigations(self, db_ctx: dict[str, Any]) -> None:
        """Verify GET /cases/{id} returns the linked investigation."""
        factory = db_ctx["factory"]
        store = db_ctx["store"]
        case_id = _seed_case_with_url(factory)

        # Seed a completed scan and link it
        scan_id = str(uuid.uuid4())
        store.create_scan(
            scan_id=scan_id,
            url=SUSPICIOUS_URL,
            scan_type="full",
            domain="suspicious-giveaway.example.com",
        )

        # Mark scan as completed with a risk score
        with factory() as session:
            session.execute(
                sa.update(site_scans)
                .where(site_scans.c.scan_id == scan_id)
                .values(
                    status="completed",
                    risk_score=78.5,
                    completed_at=datetime.now(UTC),
                )
            )
            session.execute(
                sa.insert(case_investigations).values(
                    case_id=case_id,
                    scan_id=scan_id,
                    trigger_type="auto",
                )
            )
            session.commit()

        resp = client.get(f"/cases/{case_id}")
        assert resp.status_code == 200, f"GET /cases/{case_id} returned {resp.status_code}: {resp.text}"

        data = resp.json()
        assert "investigations" in data, "Response missing 'investigations' field"
        assert len(data["investigations"]) >= 1, "Expected at least 1 investigation"

        inv = data["investigations"][0]
        assert inv["scanId"] == scan_id
        assert inv["url"] == SUSPICIOUS_URL
        assert inv["triggerType"] == "auto"
        assert inv["status"] == "completed"
        assert inv["riskScore"] == 78.5
        print(f"  [PASS] GET /cases/{case_id}: {len(data['investigations'])} investigation(s)")

    def test_step4_case_activity_includes_investigation(self, db_ctx: dict[str, Any]) -> None:
        """Verify GET /cases/{id}/activity returns SSI investigation activity."""
        factory = db_ctx["factory"]
        store = db_ctx["store"]
        case_id = _seed_case_with_url(factory)

        scan_id = str(uuid.uuid4())
        store.create_scan(
            scan_id=scan_id,
            url=SUSPICIOUS_URL,
            scan_type="full",
            domain="suspicious-giveaway.example.com",
        )

        with factory() as session:
            session.execute(
                sa.insert(case_investigations).values(
                    case_id=case_id,
                    scan_id=scan_id,
                    trigger_type="auto",
                )
            )
            session.commit()

        resp = client.get(f"/cases/{case_id}/activity")
        assert resp.status_code == 200, f"GET /cases/{case_id}/activity returned {resp.status_code}"

        data = resp.json()
        assert data["caseId"] == case_id

        ssi_activities = [a for a in data["activities"] if a["type"] == "ssi_investigation"]
        assert len(ssi_activities) >= 1, "Expected at least 1 SSI investigation activity"
        assert ssi_activities[0]["scanId"] == scan_id
        assert ssi_activities[0]["url"] == SUSPICIOUS_URL

        # Scan was created with status="running", so hasRunning should be True
        assert data["hasRunning"] is True
        print(f"  [PASS] GET /cases/{case_id}/activity: {len(ssi_activities)} SSI activities")


# ---------------------------------------------------------------------------
# Full flow test (combines all steps in sequence)
# ---------------------------------------------------------------------------


class TestFullFlowE2E:
    """Runs the complete flow in a single test for maximum E2E coverage."""

    def test_full_ingest_investigate_verify(self, db_ctx: dict[str, Any]) -> None:
        """Ingest -> linkage extract -> auto-investigate -> verify API."""
        factory = db_ctx["factory"]
        case_id = _seed_case_with_url(factory)

        # ── Step 1: Linkage extraction ────────────────────────────────
        mock_llm = MagicMock()
        mock_llm.generate.return_value = _mock_llm_response()

        from i4g.task_status import TaskStatusReporter
        from i4g.worker.jobs.linkage_extract import _run_case_url_extraction

        reporter = TaskStatusReporter()

        with factory() as session:
            successes, _failures = _run_case_url_extraction(session, mock_llm, reporter=reporter)
        assert successes >= 1
        print(f"  Step 1: Linkage extraction created {successes} URL indicators")

        # ── Step 2: Auto-investigate ──────────────────────────────────
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        mock_http_client = MagicMock()
        mock_http_client.__enter__ = MagicMock(return_value=mock_http_client)
        mock_http_client.__exit__ = MagicMock(return_value=False)
        mock_http_client.post.return_value = mock_response

        with patch("i4g.worker.jobs.auto_investigate.get_settings") as mock_settings:
            settings = MagicMock()
            settings.auto_investigate.enabled = True
            settings.auto_investigate.staleness_days = 30
            settings.auto_investigate.max_concurrent = 10
            settings.auto_investigate.domain_blocklist = []
            settings.ssi.service_url = "http://mock-ssi:8100"
            settings.runtime.log_level = "WARNING"
            mock_settings.return_value = settings

            with patch("httpx.Client", return_value=mock_http_client):
                from i4g.worker.jobs.auto_investigate import main as auto_investigate_main

                rc = auto_investigate_main(dry_run=False, limit=10)

        assert rc == 0
        print("  Step 2: Auto-investigate completed")

        # ── Step 3: Verify case_investigations ────────────────────────
        with factory() as session:
            ci_row = session.execute(
                sa.select(case_investigations).where(case_investigations.c.case_id == case_id)
            ).fetchone()

        assert ci_row is not None
        scan_id = str(ci_row.scan_id)
        print(f"  Step 3: case_investigations row found (scan_id={scan_id})")

        # Mark scan completed for API verification
        with factory() as session:
            session.execute(
                sa.update(site_scans)
                .where(site_scans.c.scan_id == scan_id)
                .values(
                    status="completed",
                    risk_score=85.0,
                    completed_at=datetime.now(UTC),
                )
            )
            session.commit()

        # ── Step 4: Verify GET /cases/{id} ────────────────────────────
        resp = client.get(f"/cases/{case_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["investigations"]) >= 1
        assert data["investigations"][0]["scanId"] == scan_id
        assert data["investigations"][0]["riskScore"] == 85.0
        print(f"  Step 4: GET /cases/{case_id} shows {len(data['investigations'])} investigation(s)")

        # ── Step 5: Verify GET /cases/{id}/activity ───────────────────
        resp = client.get(f"/cases/{case_id}/activity")
        assert resp.status_code == 200
        activity = resp.json()
        ssi_acts = [a for a in activity["activities"] if a["type"] == "ssi_investigation"]
        assert len(ssi_acts) >= 1
        print(f"  Step 5: GET /cases/{case_id}/activity shows {len(ssi_acts)} SSI activities")

        print("\n  === FULL E2E FLOW PASSED ===")
