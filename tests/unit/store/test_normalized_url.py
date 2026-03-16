"""Unit tests for the normalized_url column on site_scans."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from i4g.store.sql import METADATA, site_scans


def _engine_and_session(tmp_path: object) -> tuple[sa.engine.Engine, sessionmaker[Session]]:
    """Create a SQLite engine with all tables."""
    db_path = tmp_path / "test_norm_url.db"  # type: ignore[operator]
    engine = sa.create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    METADATA.create_all(engine, checkfirst=True)
    sf = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return engine, sf


class TestNormalizedUrlColumn:
    """Test the normalized_url column on site_scans."""

    def test_column_is_nullable(self, tmp_path) -> None:
        """Existing rows without normalized_url should be unaffected."""
        _, sf = _engine_and_session(tmp_path)
        with sf() as session:
            session.execute(
                sa.insert(site_scans).values(
                    scan_id="scan-no-norm",
                    url="https://example.com",
                    scan_type="passive",
                    status="completed",
                )
            )
            session.commit()

            row = session.execute(
                sa.select(site_scans.c.normalized_url).where(site_scans.c.scan_id == "scan-no-norm")
            ).scalar()
            assert row is None

    def test_insert_with_normalized_url(self, tmp_path) -> None:
        _, sf = _engine_and_session(tmp_path)
        with sf() as session:
            session.execute(
                sa.insert(site_scans).values(
                    scan_id="scan-with-norm",
                    url="https://Example.Com/Path/",
                    normalized_url="https://example.com/Path",
                    scan_type="passive",
                    status="completed",
                )
            )
            session.commit()

            row = session.execute(
                sa.select(site_scans.c.normalized_url).where(site_scans.c.scan_id == "scan-with-norm")
            ).scalar()
            assert row == "https://example.com/Path"

    def test_query_by_normalized_url_and_status(self, tmp_path) -> None:
        """Composite index query should work for dedup lookups."""
        _, sf = _engine_and_session(tmp_path)
        with sf() as session:
            session.execute(
                sa.insert(site_scans).values(
                    scan_id="scan-dedup-1",
                    url="https://scam.example.com",
                    normalized_url="https://scam.example.com",
                    scan_type="full",
                    status="completed",
                )
            )
            session.execute(
                sa.insert(site_scans).values(
                    scan_id="scan-dedup-2",
                    url="https://other.example.com",
                    normalized_url="https://other.example.com",
                    scan_type="passive",
                    status="running",
                )
            )
            session.commit()

            # Query matching the composite index columns
            rows = session.execute(
                sa.select(site_scans.c.scan_id).where(
                    site_scans.c.normalized_url == "https://scam.example.com",
                    site_scans.c.status == "completed",
                )
            ).fetchall()
            assert len(rows) == 1
            assert rows[0].scan_id == "scan-dedup-1"
