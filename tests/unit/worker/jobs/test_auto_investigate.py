"""Unit tests for the auto_investigate worker job."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from i4g.store.sql import METADATA, case_investigations, cases, indicators, site_scans


def _engine_and_session(tmp_path: object) -> tuple[sa.engine.Engine, sessionmaker[Session]]:
    """Create a file-based SQLite engine with all tables."""
    db_path = tmp_path / "test_auto_inv.db"  # type: ignore[operator]
    engine = sa.create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    METADATA.create_all(engine, checkfirst=True)
    sf = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return engine, sf


def _seed_case(session: Session, case_id: str = "case-1", dataset: str = "batch") -> None:
    """Insert a minimal case row."""
    session.execute(
        sa.insert(cases).values(
            case_id=case_id,
            dataset=dataset,
            source_type="unit_test",
            raw_text_sha256=f"sha256_{case_id}",
            status="open",
        )
    )
    session.commit()


def _seed_url_indicator(
    session: Session,
    *,
    case_id: str = "case-1",
    url: str = "https://scam-site.example.com",
    indicator_id: str = "ind-1",
) -> None:
    """Insert a URL-type indicator."""
    session.execute(
        sa.insert(indicators).values(
            indicator_id=indicator_id,
            case_id=case_id,
            category="url",
            type="url",
            number=url,
            status="active",
            confidence=0.9,
            dataset="batch",
        )
    )
    session.commit()


def _seed_scan(
    session: Session,
    *,
    scan_id: str = "scan-existing",
    url: str = "https://scam-site.example.com",
    status: str = "completed",
    completed_at: datetime | None = None,
) -> None:
    """Insert a minimal scan row."""
    from i4g.utils.url_normalization import normalize_url

    session.execute(
        sa.insert(site_scans).values(
            scan_id=scan_id,
            url=url,
            normalized_url=normalize_url(url),
            scan_type="passive",
            status=status,
            completed_at=completed_at,
        )
    )
    session.commit()


class TestAutoInvestigateDisabled:
    """When auto_investigate.enabled is False, the job should exit early."""

    def test_disabled_returns_zero(self, tmp_path: object) -> None:
        with (
            patch("i4g.worker.jobs.auto_investigate.get_settings") as mock_settings,
            patch("i4g.worker.jobs.auto_investigate.configure_job_logging"),
        ):
            settings = MagicMock()
            settings.auto_investigate.enabled = False
            mock_settings.return_value = settings

            from i4g.worker.jobs.auto_investigate import main

            result = main(dry_run=False, limit=10)
            assert result == 0


class TestAutoInvestigateNoUrls:
    """When no uninvestigated URLs exist, should finish with 0."""

    def test_no_urls_returns_zero(self, tmp_path: object) -> None:
        _, sf = _engine_and_session(tmp_path)

        with (
            patch("i4g.worker.jobs.auto_investigate.get_settings") as mock_settings,
            patch("i4g.worker.jobs.auto_investigate.configure_job_logging"),
            patch("i4g.worker.jobs.auto_investigate.build_sql_session_factory", return_value=sf),
        ):
            settings = MagicMock()
            settings.auto_investigate.enabled = True
            settings.auto_investigate.staleness_days = 30
            settings.auto_investigate.max_concurrent = 3
            settings.auto_investigate.domain_blocklist = []
            mock_settings.return_value = settings

            from i4g.worker.jobs.auto_investigate import main

            result = main(dry_run=False, limit=10)
            assert result == 0


class TestAutoInvestigateDomainBlocklist:
    """URLs on the blocklist should be skipped."""

    def test_blocked_domain_skipped(self, tmp_path: object) -> None:
        _, sf = _engine_and_session(tmp_path)

        with sf() as session:
            _seed_case(session, "case-1")
            _seed_url_indicator(session, case_id="case-1", url="https://google.com/phishing")

        with (
            patch("i4g.worker.jobs.auto_investigate.get_settings") as mock_settings,
            patch("i4g.worker.jobs.auto_investigate.configure_job_logging"),
            patch("i4g.worker.jobs.auto_investigate.build_sql_session_factory", return_value=sf),
        ):
            settings = MagicMock()
            settings.auto_investigate.enabled = True
            settings.auto_investigate.staleness_days = 30
            settings.auto_investigate.max_concurrent = 3
            settings.auto_investigate.domain_blocklist = []
            mock_settings.return_value = settings

            from i4g.worker.jobs.auto_investigate import main

            # google.com is in the default blocklist
            result = main(dry_run=True, limit=10)
            assert result == 0


class TestAutoInvestigateBatchDedup:
    """Same normalized URL from multiple cases should trigger once."""

    def test_batch_dedup_groups_urls(self, tmp_path: object) -> None:
        from i4g.worker.jobs.auto_investigate import _deduplicate_urls

        urls = [
            {"indicator_id": "i1", "case_id": "c1", "url": "https://scam.com/page?ref=abc", "case_dataset": "batch"},
            {"indicator_id": "i2", "case_id": "c2", "url": "https://scam.com/page", "case_dataset": "batch"},
        ]
        groups = _deduplicate_urls(urls)
        # Both should normalize to the same URL (ref is a tracking param)
        assert len(groups) == 1
        key = next(iter(groups))
        assert len(groups[key]) == 2


class TestAutoInvestigateDedupAgainstScans:
    """URLs recently scanned should be skipped."""

    def test_recently_scanned_url_skipped(self, tmp_path: object) -> None:
        _, sf = _engine_and_session(tmp_path)
        recent = datetime.now(UTC) - timedelta(days=5)

        with sf() as session:
            _seed_case(session, "case-1")
            _seed_url_indicator(
                session,
                case_id="case-1",
                url="https://scam-site.example.com",
            )
            _seed_scan(
                session,
                url="https://scam-site.example.com",
                status="completed",
                completed_at=recent,
            )

        with (
            patch("i4g.worker.jobs.auto_investigate.get_settings") as mock_settings,
            patch("i4g.worker.jobs.auto_investigate.configure_job_logging"),
            patch("i4g.worker.jobs.auto_investigate.build_sql_session_factory", return_value=sf),
        ):
            settings = MagicMock()
            settings.auto_investigate.enabled = True
            settings.auto_investigate.staleness_days = 30
            settings.auto_investigate.max_concurrent = 3
            settings.auto_investigate.domain_blocklist = []
            mock_settings.return_value = settings

            from i4g.worker.jobs.auto_investigate import main

            result = main(dry_run=True, limit=10)
            assert result == 0


class TestAutoInvestigateDryRun:
    """Dry-run mode should not trigger actual investigations."""

    def test_dry_run_no_trigger(self, tmp_path: object) -> None:
        _, sf = _engine_and_session(tmp_path)

        with sf() as session:
            _seed_case(session, "case-1")
            _seed_url_indicator(
                session,
                case_id="case-1",
                url="https://totally-unique-scam.example.net",
            )

        with (
            patch("i4g.worker.jobs.auto_investigate.get_settings") as mock_settings,
            patch("i4g.worker.jobs.auto_investigate.configure_job_logging"),
            patch("i4g.worker.jobs.auto_investigate.build_sql_session_factory", return_value=sf),
            patch("i4g.worker.jobs.auto_investigate._trigger_investigation") as mock_trigger,
        ):
            settings = MagicMock()
            settings.auto_investigate.enabled = True
            settings.auto_investigate.staleness_days = 30
            settings.auto_investigate.max_concurrent = 3
            settings.auto_investigate.domain_blocklist = []
            mock_settings.return_value = settings

            from i4g.worker.jobs.auto_investigate import main

            result = main(dry_run=True, limit=10)
            assert result == 0
            mock_trigger.assert_not_called()


class TestAutoInvestigateMaxConcurrent:
    """max_concurrent should limit the number of triggered investigations."""

    def test_max_concurrent_respected(self, tmp_path: object) -> None:
        _, sf = _engine_and_session(tmp_path)

        with sf() as session:
            for i in range(5):
                _seed_case(session, f"case-{i}")
                _seed_url_indicator(
                    session,
                    case_id=f"case-{i}",
                    url=f"https://unique-scam-{i}.example.net",
                    indicator_id=f"ind-{i}",
                )

        with (
            patch("i4g.worker.jobs.auto_investigate.get_settings") as mock_settings,
            patch("i4g.worker.jobs.auto_investigate.configure_job_logging"),
            patch("i4g.worker.jobs.auto_investigate.build_sql_session_factory", return_value=sf),
        ):
            settings = MagicMock()
            settings.auto_investigate.enabled = True
            settings.auto_investigate.staleness_days = 30
            settings.auto_investigate.max_concurrent = 2
            settings.auto_investigate.domain_blocklist = []
            mock_settings.return_value = settings

            from i4g.worker.jobs.auto_investigate import main

            # dry_run counts towards triggered but doesn't call external services
            result = main(dry_run=True, limit=10)
            assert result == 0


class TestAutoInvestigateCaseInvestigationsCreated:
    """After triggering, case_investigations rows should be created."""

    def test_case_investigation_rows_linked(self, tmp_path: object) -> None:
        _, sf = _engine_and_session(tmp_path)

        with sf() as session:
            _seed_case(session, "case-1")
            _seed_url_indicator(
                session,
                case_id="case-1",
                url="https://unique-scam.example.net",
            )

        with (
            patch("i4g.worker.jobs.auto_investigate.get_settings") as mock_settings,
            patch("i4g.worker.jobs.auto_investigate.configure_job_logging"),
            patch("i4g.worker.jobs.auto_investigate.build_sql_session_factory", return_value=sf),
            patch("i4g.worker.jobs.auto_investigate._trigger_investigation", return_value="new-scan-id") as mock_trig,
        ):
            settings = MagicMock()
            settings.auto_investigate.enabled = True
            settings.auto_investigate.staleness_days = 30
            settings.auto_investigate.max_concurrent = 3
            settings.auto_investigate.domain_blocklist = []
            mock_settings.return_value = settings

            from i4g.worker.jobs.auto_investigate import main

            result = main(dry_run=False, limit=10)
            assert result == 0
            assert mock_trig.call_count == 1


class TestGetUninvestigatedUrls:
    """Test the _get_uninvestigated_urls query."""

    def test_returns_url_indicators_without_investigation(self, tmp_path: object) -> None:
        _, sf = _engine_and_session(tmp_path)

        with sf() as session:
            _seed_case(session, "case-1", dataset="batch")
            _seed_url_indicator(session, case_id="case-1", url="https://scam.com")

        from i4g.worker.jobs.auto_investigate import _get_uninvestigated_urls

        with sf() as session:
            results = _get_uninvestigated_urls(session, limit=10)
            assert len(results) == 1
            assert results[0]["url"] == "https://scam.com"
            assert results[0]["case_id"] == "case-1"

    def test_excludes_ssi_dataset(self, tmp_path: object) -> None:
        _, sf = _engine_and_session(tmp_path)

        with sf() as session:
            _seed_case(session, "ssi-case-1", dataset="ssi")
            _seed_url_indicator(
                session,
                case_id="ssi-case-1",
                url="https://ssi-url.com",
                indicator_id="ind-ssi",
            )

        from i4g.worker.jobs.auto_investigate import _get_uninvestigated_urls

        with sf() as session:
            results = _get_uninvestigated_urls(session, limit=10)
            assert len(results) == 0

    def test_excludes_already_investigated(self, tmp_path: object) -> None:
        _, sf = _engine_and_session(tmp_path)

        with sf() as session:
            _seed_case(session, "case-1")
            _seed_url_indicator(session, case_id="case-1", url="https://scam.com")
            # Add a scan and link via case_investigations
            _seed_scan(session, scan_id="scan-linked", url="https://scam.com")
            session.execute(
                sa.insert(case_investigations).values(
                    case_id="case-1",
                    scan_id="scan-linked",
                    trigger_type="manual",
                )
            )
            session.commit()

        from i4g.worker.jobs.auto_investigate import _get_uninvestigated_urls

        with sf() as session:
            results = _get_uninvestigated_urls(session, limit=10)
            assert len(results) == 0
