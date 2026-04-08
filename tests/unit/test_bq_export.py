"""Unit tests for BigQuery export job (Phase 4 — Looker + Cross-Engagement Intelligence)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.store.sql import METADATA


def _make_session(db_path: Path) -> sessionmaker:
    """Build a session factory backed by a temporary SQLite file."""
    engine = sa.create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    METADATA.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed_engagements(sf: sessionmaker) -> tuple[str, str]:
    """Create two engagements and return their IDs."""
    from i4g.store import sql as sql_schema

    eng_1_id = "eng-uab-spring-2026"
    eng_2_id = "eng-gwu-spring-2026"
    now = datetime.now(UTC)

    with sf() as session:
        for eid, name, uni in [
            (eng_1_id, "Spring 2026 — UAB", "UAB"),
            (eng_2_id, "Spring 2026 — GWU", "GWU"),
        ]:
            session.execute(
                sa.insert(sql_schema.engagements).values(
                    engagement_id=eid,
                    name=name,
                    status="active",
                    starts_at=now - timedelta(days=30),
                    ends_at=now + timedelta(days=14),
                    metadata={"university": uni},
                    created_at=now,
                    updated_at=now,
                )
            )
        session.commit()
    return eng_1_id, eng_2_id


def _seed_cases(sf: sessionmaker, eng_1_id: str, eng_2_id: str) -> None:
    """Insert cases assigned to each engagement + some unassigned."""
    from i4g.store import sql as sql_schema

    now = datetime.now(UTC)
    with sf() as session:
        for i in range(5):
            session.execute(
                sa.insert(sql_schema.cases).values(
                    case_id=f"case-uab-{i}",
                    dataset="test",
                    source_type="proactive" if i % 2 == 0 else "reactive",
                    raw_text_sha256=f"sha-uab-{i}",
                    engagement_id=eng_1_id,
                    created_at=now,
                    updated_at=now,
                )
            )
        for i in range(3):
            session.execute(
                sa.insert(sql_schema.cases).values(
                    case_id=f"case-gwu-{i}",
                    dataset="test",
                    source_type="reactive",
                    raw_text_sha256=f"sha-gwu-{i}",
                    engagement_id=eng_2_id,
                    created_at=now,
                    updated_at=now,
                )
            )
        # Unassigned case
        session.execute(
            sa.insert(sql_schema.cases).values(
                case_id="case-unassigned",
                dataset="test",
                source_type="reactive",
                raw_text_sha256="sha-unassigned",
                engagement_id=None,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def _seed_platform_kpis(sf: sessionmaker, eng_1_id: str, eng_2_id: str) -> None:
    """Insert platform_kpis rows for testing cross-engagement queries."""
    from i4g.store import sql as sql_schema

    now = datetime.now(UTC)
    today = now.date()
    with sf() as session:
        for eid in [eng_1_id, eng_2_id, "__global__"]:
            session.execute(
                sa.insert(sql_schema.platform_kpis).values(
                    period_type="weekly",
                    period_start=today - timedelta(days=7),
                    engagement_id=eid,
                    total_cases=5 if eid == eng_1_id else 3,
                    proactive_cases=3 if eid == eng_1_id else 0,
                    reactive_cases=2 if eid == eng_1_id else 3,
                    total_loss=50000 if eid == eng_1_id else 30000,
                    new_indicators=10 if eid == eng_1_id else 5,
                    new_entities=8 if eid == eng_1_id else 4,
                    cases_actioned=3 if eid == eng_1_id else 1,
                    updated_at=now,
                )
            )
        session.commit()


def _seed_analyst_stats(sf: sessionmaker, eng_1_id: str, eng_2_id: str) -> None:
    """Insert engagement_analyst_stats rows."""
    from i4g.store import sql as sql_schema

    now = datetime.now(UTC)
    with sf() as session:
        for eid, analysts in [
            (eng_1_id, [("alice@uab.edu", 4, 0.85), ("bob@uab.edu", 3, 0.72)]),
            (eng_2_id, [("carol@gwu.edu", 2, 0.90)]),
        ]:
            for email, reviewed, accuracy in analysts:
                session.execute(
                    sa.insert(sql_schema.engagement_analyst_stats).values(
                        engagement_id=eid,
                        analyst_email=email,
                        cases_reviewed=reviewed,
                        classification_accuracy=accuracy,
                        actions_logged=reviewed * 2,
                        computed_at=now,
                    )
                )
        session.commit()


# ---------------------------------------------------------------------------
# Test: Dry-run export
# ---------------------------------------------------------------------------


class TestDryRunExport:
    def test_dry_run_counts_rows(self, tmp_path):
        sf = _make_session(tmp_path / "test.db")
        eng_1_id, eng_2_id = _seed_engagements(sf)
        _seed_platform_kpis(sf, eng_1_id, eng_2_id)
        _seed_analyst_stats(sf, eng_1_id, eng_2_id)

        from i4g.worker.jobs.bq_export import _dry_run_export

        with sf() as session:
            results = _dry_run_export(session)

        assert results["engagements"] == 2
        assert results["platform_kpis"] == 3  # 2 engagements + global
        assert results["engagement_analyst_stats"] == 3

    def test_dry_run_empty_tables(self, tmp_path):
        sf = _make_session(tmp_path / "test.db")

        from i4g.worker.jobs.bq_export import _dry_run_export

        with sf() as session:
            results = _dry_run_export(session)

        for table_name, count in results.items():
            assert count == 0, f"{table_name} should be empty"


# ---------------------------------------------------------------------------
# Test: Cross-engagement KPIs
# ---------------------------------------------------------------------------


class TestCrossEngagementKPIs:
    def test_returns_per_engagement_rows(self, tmp_path):
        sf = _make_session(tmp_path / "test.db")
        eng_1_id, eng_2_id = _seed_engagements(sf)
        _seed_platform_kpis(sf, eng_1_id, eng_2_id)

        from i4g.worker.jobs.bq_export import get_cross_engagement_kpis

        with sf() as session:
            results = get_cross_engagement_kpis(session)

        # Should exclude __global__ row
        assert len(results) == 2
        eids = {r["engagement_id"] for r in results}
        assert eng_1_id in eids
        assert eng_2_id in eids
        assert "__global__" not in eids

    def test_kpis_have_expected_fields(self, tmp_path):
        sf = _make_session(tmp_path / "test.db")
        eng_1_id, eng_2_id = _seed_engagements(sf)
        _seed_platform_kpis(sf, eng_1_id, eng_2_id)

        from i4g.worker.jobs.bq_export import get_cross_engagement_kpis

        with sf() as session:
            results = get_cross_engagement_kpis(session)

        for r in results:
            assert "engagement_name" in r
            assert "total_cases" in r
            assert "total_loss" in r

    def test_empty_kpis(self, tmp_path):
        sf = _make_session(tmp_path / "test.db")

        from i4g.worker.jobs.bq_export import get_cross_engagement_kpis

        with sf() as session:
            results = get_cross_engagement_kpis(session)

        assert results == []


# ---------------------------------------------------------------------------
# Test: Semester trends
# ---------------------------------------------------------------------------


class TestSemesterTrends:
    def test_returns_all_engagements_by_default(self, tmp_path):
        sf = _make_session(tmp_path / "test.db")
        eng_1_id, eng_2_id = _seed_engagements(sf)
        _seed_platform_kpis(sf, eng_1_id, eng_2_id)

        from i4g.worker.jobs.bq_export import get_semester_trends

        with sf() as session:
            results = get_semester_trends(session)

        assert len(results) == 2  # one weekly row each, no global

    def test_filter_by_engagement_ids(self, tmp_path):
        sf = _make_session(tmp_path / "test.db")
        eng_1_id, eng_2_id = _seed_engagements(sf)
        _seed_platform_kpis(sf, eng_1_id, eng_2_id)

        from i4g.worker.jobs.bq_export import get_semester_trends

        with sf() as session:
            results = get_semester_trends(session, engagement_ids=[eng_1_id])

        assert len(results) == 1
        assert results[0]["engagement_id"] == eng_1_id


# ---------------------------------------------------------------------------
# Test: University comparison
# ---------------------------------------------------------------------------


class TestUniversityComparison:
    def test_groups_by_university(self, tmp_path):
        sf = _make_session(tmp_path / "test.db")
        eng_1_id, eng_2_id = _seed_engagements(sf)
        _seed_platform_kpis(sf, eng_1_id, eng_2_id)

        from i4g.worker.jobs.bq_export import get_university_comparison

        with sf() as session:
            results = get_university_comparison(session)

        assert len(results) == 2
        unis = {r["university"] for r in results}
        assert "UAB" in unis
        assert "GWU" in unis

    def test_aggregates_kpis(self, tmp_path):
        sf = _make_session(tmp_path / "test.db")
        eng_1_id, eng_2_id = _seed_engagements(sf)
        _seed_platform_kpis(sf, eng_1_id, eng_2_id)

        from i4g.worker.jobs.bq_export import get_university_comparison

        with sf() as session:
            results = get_university_comparison(session)

        uab = next(r for r in results if r["university"] == "UAB")
        assert uab["total_cases"] == 5
        assert uab["engagement_count"] == 1
        assert len(uab["engagements"]) == 1

    def test_empty_returns_empty(self, tmp_path):
        sf = _make_session(tmp_path / "test.db")

        from i4g.worker.jobs.bq_export import get_university_comparison

        with sf() as session:
            results = get_university_comparison(session)

        assert results == []


# ---------------------------------------------------------------------------
# Test: _EXPORT_TABLES spec completeness
# ---------------------------------------------------------------------------


class TestExportTableSpecs:
    def test_all_specs_have_required_keys(self):
        from i4g.worker.jobs.bq_export import _EXPORT_TABLES

        for spec in _EXPORT_TABLES:
            assert "source" in spec
            assert "bq_table" in spec
            assert "columns" in spec
            assert len(spec["columns"]) > 0

    def test_column_names_match_source_table(self):
        from i4g.worker.jobs.bq_export import _EXPORT_TABLES

        for spec in _EXPORT_TABLES:
            source_cols = {c.name for c in spec["source"].columns}
            for col_name in spec["columns"]:
                assert (
                    col_name in source_cols
                ), f"Column {col_name!r} in spec {spec['bq_table']!r} not found in source table"


# ---------------------------------------------------------------------------
# Test: BigQueryExportSettings
# ---------------------------------------------------------------------------


class TestBigQueryExportSettings:
    def test_defaults(self):
        from i4g.settings.sections.jobs import BigQueryExportSettings

        s = BigQueryExportSettings()
        assert s.project_id == "i4g-dev"
        assert s.dataset_id == "i4g_analytics"
        assert s.enabled is False

    def test_override_via_env(self, monkeypatch):
        from i4g.settings.sections.jobs import BigQueryExportSettings

        monkeypatch.setenv("BQ_EXPORT__PROJECT_ID", "i4g-prod")
        monkeypatch.setenv("BQ_EXPORT__DATASET_ID", "analytics_prod")
        monkeypatch.setenv("BQ_EXPORT__ENABLED", "true")

        s = BigQueryExportSettings()
        assert s.project_id == "i4g-prod"
        assert s.dataset_id == "analytics_prod"
        assert s.enabled is True


# ---------------------------------------------------------------------------
# Test: platform_kpis engagement_id dimension
# ---------------------------------------------------------------------------


class TestPlatformKPIsEngagementDimension:
    """Verify the updated _refresh_platform_kpis produces per-engagement + global rows."""

    def test_produces_global_and_per_engagement_rows(self, tmp_path):
        sf = _make_session(tmp_path / "test.db")
        eng_1_id, _ = _seed_engagements(sf)
        _seed_cases(sf, eng_1_id, "eng-gwu-spring-2026")

        from i4g.store import sql as sql_schema
        from i4g.worker.jobs.analytics_aggregation import _refresh_platform_kpis

        with sf() as session:
            count = _refresh_platform_kpis(session)
            session.commit()

        # 2 period types × (2 engagements + 1 global) = 6
        assert count == 6

        with sf() as session:
            rows = session.execute(sa.select(sql_schema.platform_kpis)).fetchall()

        eids = {r.engagement_id for r in rows}
        assert "__global__" in eids
        assert eng_1_id in eids

    def test_global_row_includes_all_cases(self, tmp_path):
        sf = _make_session(tmp_path / "test.db")
        eng_1_id, eng_2_id = _seed_engagements(sf)
        _seed_cases(sf, eng_1_id, eng_2_id)

        from i4g.store import sql as sql_schema
        from i4g.worker.jobs.analytics_aggregation import _refresh_platform_kpis

        with sf() as session:
            _refresh_platform_kpis(session)
            session.commit()

        with sf() as session:
            global_daily = session.execute(
                sa.select(sql_schema.platform_kpis).where(
                    sql_schema.platform_kpis.c.engagement_id == "__global__",
                    sql_schema.platform_kpis.c.period_type == "daily",
                )
            ).first()

        # 5 UAB + 3 GWU + 1 unassigned = 9
        assert global_daily.total_cases == 9

    def test_per_engagement_row_only_counts_own_cases(self, tmp_path):
        sf = _make_session(tmp_path / "test.db")
        eng_1_id, eng_2_id = _seed_engagements(sf)
        _seed_cases(sf, eng_1_id, eng_2_id)

        from i4g.store import sql as sql_schema
        from i4g.worker.jobs.analytics_aggregation import _refresh_platform_kpis

        with sf() as session:
            _refresh_platform_kpis(session)
            session.commit()

        with sf() as session:
            uab_daily = session.execute(
                sa.select(sql_schema.platform_kpis).where(
                    sql_schema.platform_kpis.c.engagement_id == eng_1_id,
                    sql_schema.platform_kpis.c.period_type == "daily",
                )
            ).first()

        assert uab_daily.total_cases == 5
        # 3 proactive (indices 0, 2, 4)
        assert uab_daily.proactive_cases == 3
