"""Unit tests for URL dedup checking (investigation_dedup)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from i4g.services.investigation_dedup import check_url_duplicate
from i4g.store.sql import METADATA, site_scans
from i4g.utils.url_normalization import normalize_url


def _engine_and_session(tmp_path: object) -> tuple[sa.engine.Engine, sessionmaker[Session]]:
    """Create a file-based SQLite engine with all tables."""
    db_path = tmp_path / "test_dedup.db"  # type: ignore[operator]
    engine = sa.create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    METADATA.create_all(engine, checkfirst=True)
    sf = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return engine, sf


def _insert_scan(
    session: Session,
    *,
    scan_id: str = "scan-1",
    url: str = "https://example.com",
    normalized_url: str | None = None,
    status: str = "completed",
    risk_score: float | None = 7.5,
    completed_at: datetime | None = None,
) -> None:
    """Insert a minimal site_scans row."""
    session.execute(
        sa.insert(site_scans).values(
            scan_id=scan_id,
            url=url,
            normalized_url=normalized_url or normalize_url(url),
            scan_type="passive",
            status=status,
            risk_score=risk_score,
            completed_at=completed_at,
        )
    )
    session.commit()


class TestCheckUrlDuplicateNoPriorScan:
    """When no prior scan exists, should return is_duplicate=False."""

    def test_no_prior_scan(self, tmp_path: object) -> None:
        _, sf = _engine_and_session(tmp_path)
        result = check_url_duplicate("https://never-scanned.com", session_factory=sf)
        assert result.is_duplicate is False
        assert result.reason == "no_prior_scan"
        assert result.existing_scan_id is None


class TestCheckUrlDuplicateFreshScan:
    """When a fresh completed scan exists, should return is_duplicate=True."""

    def test_fresh_completed_scan(self, tmp_path: object) -> None:
        _, sf = _engine_and_session(tmp_path)
        recently = datetime.now(UTC) - timedelta(days=5)
        with sf() as session:
            _insert_scan(
                session,
                url="https://example.com",
                status="completed",
                risk_score=8.0,
                completed_at=recently,
            )

        result = check_url_duplicate("https://example.com", session_factory=sf, staleness_days=30)
        assert result.is_duplicate is True
        assert result.reason == "fresh_scan_exists"
        assert result.existing_scan_id == "scan-1"
        assert result.existing_risk_score == 8.0
        assert result.days_since_scan is not None
        assert result.days_since_scan <= 6


class TestCheckUrlDuplicateStaleScan:
    """When an old completed scan exists past the staleness window."""

    def test_stale_completed_scan(self, tmp_path: object) -> None:
        _, sf = _engine_and_session(tmp_path)
        old = datetime.now(UTC) - timedelta(days=60)
        with sf() as session:
            _insert_scan(
                session,
                url="https://example.com",
                status="completed",
                completed_at=old,
            )

        result = check_url_duplicate("https://example.com", session_factory=sf, staleness_days=30)
        assert result.is_duplicate is False
        assert result.reason == "stale_scan"
        assert result.existing_scan_id == "scan-1"
        assert result.days_since_scan is not None
        assert result.days_since_scan >= 59


class TestCheckUrlDuplicateInProgress:
    """When a scan is running or pending, should return is_duplicate=True."""

    def test_scan_running(self, tmp_path: object) -> None:
        _, sf = _engine_and_session(tmp_path)
        with sf() as session:
            _insert_scan(session, status="running", completed_at=None)

        result = check_url_duplicate("https://example.com", session_factory=sf)
        assert result.is_duplicate is True
        assert result.reason == "scan_in_progress"

    def test_scan_pending(self, tmp_path: object) -> None:
        _, sf = _engine_and_session(tmp_path)
        with sf() as session:
            _insert_scan(session, status="pending", completed_at=None)

        result = check_url_duplicate("https://example.com", session_factory=sf)
        assert result.is_duplicate is True
        assert result.reason == "scan_in_progress"


class TestCheckUrlDuplicateFailedScan:
    """Failed scans should not be considered duplicates."""

    def test_failed_scan_not_duplicate(self, tmp_path: object) -> None:
        _, sf = _engine_and_session(tmp_path)
        with sf() as session:
            _insert_scan(
                session,
                status="failed",
                completed_at=datetime.now(UTC) - timedelta(days=1),
            )

        result = check_url_duplicate("https://example.com", session_factory=sf)
        assert result.is_duplicate is False
        assert result.reason == "no_prior_scan"


class TestCheckUrlDuplicateStalenesssBoundary:
    """Test the exact boundary of the staleness window."""

    def test_exactly_at_boundary(self, tmp_path: object) -> None:
        _, sf = _engine_and_session(tmp_path)
        # Just inside the 30-day window (29 days, 23 hours ago)
        boundary = datetime.now(UTC) - timedelta(days=29, hours=23)
        with sf() as session:
            _insert_scan(session, status="completed", completed_at=boundary)

        result = check_url_duplicate("https://example.com", session_factory=sf, staleness_days=30)
        assert result.is_duplicate is True
        assert result.reason == "fresh_scan_exists"

    def test_just_past_boundary(self, tmp_path: object) -> None:
        _, sf = _engine_and_session(tmp_path)
        # 31 days ago — should be stale
        past = datetime.now(UTC) - timedelta(days=31)
        with sf() as session:
            _insert_scan(session, status="completed", completed_at=past)

        result = check_url_duplicate("https://example.com", session_factory=sf, staleness_days=30)
        assert result.is_duplicate is False
        assert result.reason == "stale_scan"
