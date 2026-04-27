"""Unit tests for ``i4g.ingestion.phishdestroy.archive.brands`` (Sprint 2 Phase D)."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa

from i4g.ingestion.phishdestroy.archive.brands import lookup_indicators_for_domain
from i4g.store import sql as sql_schema
from i4g.store.sql import METADATA


def _make_session_factory(db_path: Path):
    """Return a session factory backed by a fresh SQLite database."""
    engine = sa.create_engine(f"sqlite:///{db_path}", future=True)
    METADATA.create_all(engine)

    @contextmanager
    def factory():
        with engine.connect() as conn:
            yield conn

    return factory


def _insert_case(factory, case_id: str) -> None:
    now = datetime.now(tz=UTC)
    with factory() as session:
        session.execute(
            sql_schema.cases.insert().values(
                case_id=case_id,
                dataset="test",
                source_type="reactive",
                raw_text_sha256=f"sha256-{case_id}",
                status="open",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def _insert_indicator(
    factory,
    indicator_id: str,
    case_id: str,
    category: str,
    number: str,
    dataset: str = "test",
) -> None:
    now = datetime.now(tz=UTC)
    with factory() as session:
        session.execute(
            sql_schema.indicators.insert().values(
                indicator_id=indicator_id,
                case_id=case_id,
                category=category,
                type="url",
                number=number,
                status="active",
                confidence=0.9,
                dataset=dataset,
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


class TestLookupIndicatorsForDomain:
    def test_empty_result_when_no_indicators(self, tmp_path: Path) -> None:
        factory = _make_session_factory(tmp_path / "test.db")
        result = lookup_indicators_for_domain(factory, "tttadmin.com")
        assert result == []

    def test_hit_on_category_domain(self, tmp_path: Path) -> None:
        factory = _make_session_factory(tmp_path / "test.db")
        case_id = "case-1"
        indicator_id = str(uuid.uuid4())
        _insert_case(factory, case_id)
        _insert_indicator(factory, indicator_id, case_id, "domain", "tttadmin.com")

        result = lookup_indicators_for_domain(factory, "tttadmin.com")
        assert result == [indicator_id]

    def test_hit_on_category_url(self, tmp_path: Path) -> None:
        factory = _make_session_factory(tmp_path / "test.db")
        case_id = "case-2"
        indicator_id = str(uuid.uuid4())
        _insert_case(factory, case_id)
        _insert_indicator(factory, indicator_id, case_id, "url", "tttadmin.com")

        result = lookup_indicators_for_domain(factory, "tttadmin.com")
        assert result == [indicator_id]

    def test_miss_on_category_email(self, tmp_path: Path) -> None:
        """category='email' must NOT match even if number is identical."""
        factory = _make_session_factory(tmp_path / "test.db")
        case_id = "case-3"
        indicator_id = str(uuid.uuid4())
        _insert_case(factory, case_id)
        _insert_indicator(factory, indicator_id, case_id, "email", "tttadmin.com")

        result = lookup_indicators_for_domain(factory, "tttadmin.com")
        assert result == []

    def test_multiple_matching_indicators_returned(self, tmp_path: Path) -> None:
        """Multiple indicators with domain/url category must all be returned."""
        factory = _make_session_factory(tmp_path / "test.db")
        case_id = "case-4"
        _insert_case(factory, case_id)

        ids = sorted(str(uuid.uuid4()) for _ in range(3))
        # Use distinct datasets to avoid the unique constraint on (dataset, category, number).
        _insert_indicator(factory, ids[0], case_id, "domain", "tttadmin.com", dataset="test-a")
        _insert_indicator(factory, ids[1], case_id, "url", "tttadmin.com", dataset="test-b")
        _insert_indicator(factory, ids[2], case_id, "domain", "tttadmin.com", dataset="test-c")

        result = lookup_indicators_for_domain(factory, "tttadmin.com")
        assert sorted(result) == sorted(ids)

    def test_no_cross_contamination_by_number(self, tmp_path: Path) -> None:
        """Lookup for domain A must not return indicators for domain B."""
        factory = _make_session_factory(tmp_path / "test.db")
        case_id = "case-5"
        indicator_id = str(uuid.uuid4())
        _insert_case(factory, case_id)
        _insert_indicator(factory, indicator_id, case_id, "domain", "other.example.com")

        result = lookup_indicators_for_domain(factory, "tttadmin.com")
        assert result == []
