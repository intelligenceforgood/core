"""Unit tests for linkage_extract.py case URL extraction mode."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from i4g.store.sql import METADATA, cases, indicators, source_documents


def _engine_and_session(tmp_path: object) -> tuple[sa.engine.Engine, sessionmaker[Session]]:
    """Create a file-based SQLite engine with all tables."""
    db_path = tmp_path / "test_linkage_cases.db"  # type: ignore[operator]
    engine = sa.create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    METADATA.create_all(engine, checkfirst=True)
    sf = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return engine, sf


def _seed_case_with_document(
    session: Session,
    *,
    case_id: str = "case-1",
    dataset: str = "batch",
    text: str = "Found a scam at https://evil-scam.example.com/steal",
) -> None:
    """Insert a case with a source document containing narrative text."""
    session.execute(
        sa.insert(cases).values(
            case_id=case_id,
            dataset=dataset,
            source_type="unit_test",
            raw_text_sha256=f"sha256_{case_id}",
            status="open",
        )
    )
    from uuid import uuid4

    session.execute(
        sa.insert(source_documents).values(
            document_id=str(uuid4()),
            case_id=case_id,
            text=text,
            chunk_index=0,
            chunk_count=1,
        )
    )
    session.commit()


class TestProcessCaseUrls:
    """Test _process_case_urls extracts URL indicators from narratives."""

    def test_url_extraction_creates_indicator(self, tmp_path: object) -> None:
        _, sf = _engine_and_session(tmp_path)
        with sf() as session:
            _seed_case_with_document(session, case_id="case-1")

        mock_llm = MagicMock()
        mock_llm.generate.return_value = (
            '[{"type": "url", "value": "https://evil-scam.example.com/steal", "confidence": 0.95}]'
        )

        from i4g.worker.jobs.linkage_extract import _process_case_urls

        with sf() as session:
            count = _process_case_urls(
                session, mock_llm, "case-1", "Found a scam at https://evil-scam.example.com/steal"
            )
            session.commit()

        assert count == 1

        with sf() as session:
            rows = session.execute(
                sa.select(indicators).where(
                    indicators.c.case_id == "case-1",
                    indicators.c.category == "url",
                )
            ).fetchall()
            assert len(rows) == 1
            assert rows[0].number == "https://evil-scam.example.com/steal"

    def test_no_urls_in_narrative(self, tmp_path: object) -> None:
        _, sf = _engine_and_session(tmp_path)
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "[]"

        from i4g.worker.jobs.linkage_extract import _process_case_urls

        with sf() as session:
            _seed_case_with_document(session, case_id="case-1", text="No URLs here, just text")
            count = _process_case_urls(session, mock_llm, "case-1", "No URLs here, just text")
            session.commit()

        assert count == 0

    def test_non_url_indicators_ignored(self, tmp_path: object) -> None:
        _, sf = _engine_and_session(tmp_path)
        mock_llm = MagicMock()
        mock_llm.generate.return_value = '[{"type": "wallet", "value": "0xabc123", "confidence": 0.9}]'

        from i4g.worker.jobs.linkage_extract import _process_case_urls

        with sf() as session:
            _seed_case_with_document(session, case_id="case-1")
            count = _process_case_urls(session, mock_llm, "case-1", "Wallet 0xabc123")
            session.commit()

        assert count == 0


class TestRunCaseUrlExtraction:
    """Test _run_case_url_extraction end-to-end."""

    def test_ssi_cases_excluded(self, tmp_path: object) -> None:
        _, sf = _engine_and_session(tmp_path)
        with sf() as session:
            _seed_case_with_document(session, case_id="ssi-case", dataset="ssi")

        mock_llm = MagicMock()

        from i4g.worker.jobs.linkage_extract import _run_case_url_extraction

        reporter = MagicMock()
        reporter.is_enabled.return_value = False

        with sf() as session:
            successes, failures = _run_case_url_extraction(session, mock_llm, reporter=reporter)

        assert successes == 0
        assert failures == 0
        mock_llm.generate.assert_not_called()


class TestMainModeIntake:
    """Test that mode='intake' does not process cases."""

    def test_intake_mode_skips_cases(self, tmp_path: object) -> None:
        _, sf = _engine_and_session(tmp_path)
        with sf() as session:
            _seed_case_with_document(session, case_id="case-1")

        with (
            patch("i4g.worker.jobs.linkage_extract.get_settings") as mock_settings,
            patch("i4g.worker.jobs.linkage_extract.configure_job_logging"),
            patch("i4g.worker.jobs.linkage_extract.build_sql_session_factory", return_value=sf),
            patch("i4g.worker.jobs.linkage_extract.build_llm_client") as mock_llm_build,
            patch("i4g.worker.jobs.linkage_extract._run_case_url_extraction") as mock_case_extract,
        ):
            settings = MagicMock()
            settings.analytics.loss_linkage_confidence_threshold = 0.5
            mock_settings.return_value = settings
            mock_llm_build.return_value = MagicMock()

            from i4g.worker.jobs.linkage_extract import main

            main(backfill=False, mode="intake")
            mock_case_extract.assert_not_called()
