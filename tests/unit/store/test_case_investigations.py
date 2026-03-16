"""Unit tests for case_investigations table and relationships."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from i4g.store.sql import METADATA, case_investigations, cases, site_scans


def _engine_and_session(tmp_path: object) -> tuple[sa.engine.Engine, sessionmaker[Session]]:
    """Create an in-memory SQLite engine with all tables."""
    db_path = tmp_path / "test_case_inv.db"  # type: ignore[operator]
    engine = sa.create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    METADATA.create_all(engine, checkfirst=True)
    sf = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return engine, sf


def _seed_case_and_scan(session: Session, *, case_id: str = "case-1", scan_id: str = "scan-1") -> None:
    """Insert a minimal case and scan row for FK satisfaction."""
    session.execute(
        sa.insert(cases).values(
            case_id=case_id,
            dataset="test",
            source_type="unit_test",
            raw_text_sha256="sha256_placeholder",
            status="open",
        )
    )
    session.execute(
        sa.insert(site_scans).values(
            scan_id=scan_id,
            url="https://example.com",
            scan_type="passive",
            status="completed",
        )
    )
    session.commit()


class TestCaseInvestigationsInsert:
    """Test basic insert into case_investigations."""

    def test_insert_valid_row(self, tmp_path) -> None:
        _, sf = _engine_and_session(tmp_path)
        with sf() as session:
            _seed_case_and_scan(session)
            session.execute(
                sa.insert(case_investigations).values(
                    case_id="case-1",
                    scan_id="scan-1",
                    trigger_type="manual",
                )
            )
            session.commit()

            row = session.execute(
                sa.select(case_investigations).where(case_investigations.c.case_id == "case-1")
            ).first()
            assert row is not None
            assert row.scan_id == "scan-1"
            assert row.trigger_type == "manual"


class TestCompositePKPrevents:
    """Test that the composite PK prevents duplicate (case_id, scan_id) pairs."""

    def test_duplicate_raises_integrity_error(self, tmp_path) -> None:
        _, sf = _engine_and_session(tmp_path)
        with sf() as session:
            _seed_case_and_scan(session)
            session.execute(
                sa.insert(case_investigations).values(case_id="case-1", scan_id="scan-1", trigger_type="manual")
            )
            session.commit()

            with pytest.raises(sa.exc.IntegrityError):
                session.execute(
                    sa.insert(case_investigations).values(case_id="case-1", scan_id="scan-1", trigger_type="auto")
                )
                session.commit()


class TestCascadeDelete:
    """Test CASCADE delete behavior."""

    def test_delete_case_removes_investigations(self, tmp_path) -> None:
        _, sf = _engine_and_session(tmp_path)
        with sf() as session:
            _seed_case_and_scan(session)
            session.execute(
                sa.insert(case_investigations).values(case_id="case-1", scan_id="scan-1", trigger_type="manual")
            )
            session.commit()

            # Enable FK enforcement for SQLite
            session.execute(sa.text("PRAGMA foreign_keys = ON"))
            session.execute(sa.delete(cases).where(cases.c.case_id == "case-1"))
            session.commit()

            rows = session.execute(
                sa.select(case_investigations).where(case_investigations.c.case_id == "case-1")
            ).fetchall()
            assert len(rows) == 0

    def test_delete_scan_removes_investigations(self, tmp_path) -> None:
        _, sf = _engine_and_session(tmp_path)
        with sf() as session:
            _seed_case_and_scan(session)
            session.execute(
                sa.insert(case_investigations).values(case_id="case-1", scan_id="scan-1", trigger_type="auto")
            )
            session.commit()

            session.execute(sa.text("PRAGMA foreign_keys = ON"))
            session.execute(sa.delete(site_scans).where(site_scans.c.scan_id == "scan-1"))
            session.commit()

            rows = session.execute(
                sa.select(case_investigations).where(case_investigations.c.scan_id == "scan-1")
            ).fetchall()
            assert len(rows) == 0


class TestTriggerTypeDefault:
    """Test that trigger_type defaults to 'manual'."""

    def test_default_trigger_type(self, tmp_path) -> None:
        _, sf = _engine_and_session(tmp_path)
        with sf() as session:
            _seed_case_and_scan(session)
            # Insert without specifying trigger_type
            session.execute(
                sa.insert(case_investigations).values(
                    case_id="case-1",
                    scan_id="scan-1",
                )
            )
            session.commit()

            row = session.execute(
                sa.select(case_investigations.c.trigger_type).where(case_investigations.c.case_id == "case-1")
            ).scalar()
            assert row == "manual"
