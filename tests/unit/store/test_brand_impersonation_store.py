"""Tests for BrandImpersonationStore."""

from __future__ import annotations

from decimal import Decimal

import sqlalchemy as sa

from i4g.store.brand_impersonation_store import BrandImpersonationStore
from i4g.store.sql import METADATA


def _make_store(tmp_path) -> BrandImpersonationStore:
    db_path = tmp_path / "test_brand_impersonation.db"
    return BrandImpersonationStore(db_path=str(db_path))


def _seed_indicator(store: BrandImpersonationStore, indicator_id: str) -> None:
    """Seed a minimal cases + indicators row to satisfy FKs."""
    case_id = f"case-for-{indicator_id}"
    with store._session_factory() as session:
        existing_case = session.execute(
            sa.select(METADATA.tables["cases"]).where(METADATA.tables["cases"].c.case_id == case_id)
        ).first()
        if existing_case is None:
            session.execute(
                sa.insert(METADATA.tables["cases"]).values(
                    case_id=case_id,
                    dataset="test",
                    source_type="manual",
                    raw_text_sha256=f"sha-{indicator_id}",
                )
            )
        session.execute(
            sa.insert(METADATA.tables["indicators"]).values(
                indicator_id=indicator_id,
                case_id=case_id,
                category="domain",
                type="domain",
                number=f"example-{indicator_id}.com",
                dataset="test",
            )
        )
        session.commit()


class TestBrandImpersonationUpsert:
    def test_upsert_inserts_new_row(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_indicator(store, "ind-brand-1")
        result = store.upsert_by_indicator_brand(
            indicator_id="ind-brand-1",
            brand="PayPal",
            confidence=Decimal("0.950"),
            detected_by="ml",
            source_provenance={"source": "phishdestroy.archive.brands", "record_id": "b-001"},
        )
        assert result["impersonation_id"] is not None
        assert result["indicator_id"] == "ind-brand-1"
        assert result["brand"] == "PayPal"
        assert result["detected_by"] == "ml"

    def test_upsert_idempotency_same_key_updates_content(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_indicator(store, "ind-brand-2")

        first = store.upsert_by_indicator_brand(
            indicator_id="ind-brand-2",
            brand="Visa",
            confidence=Decimal("0.700"),
            detected_by="regex",
        )
        second = store.upsert_by_indicator_brand(
            indicator_id="ind-brand-2",
            brand="Visa",
            confidence=Decimal("0.950"),
            detected_by="analyst",
        )

        # Same impersonation_id; content updated
        assert first["impersonation_id"] == second["impersonation_id"]
        assert Decimal(str(second["confidence"])) == Decimal("0.950")
        assert second["detected_by"] == "analyst"

        # Exactly one row for this (indicator_id, brand)
        tbl = METADATA.tables["brand_impersonations"]
        with store._session_factory() as session:
            count = session.execute(
                sa.select(sa.func.count())
                .select_from(tbl)
                .where(
                    sa.and_(
                        tbl.c.indicator_id == "ind-brand-2",
                        tbl.c.brand == "Visa",
                    )
                )
            ).scalar()
        assert count == 1

    def test_upsert_different_brands_create_separate_rows(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_indicator(store, "ind-brand-3")
        store.upsert_by_indicator_brand(indicator_id="ind-brand-3", brand="PayPal")
        store.upsert_by_indicator_brand(indicator_id="ind-brand-3", brand="Visa")

        tbl = METADATA.tables["brand_impersonations"]
        with store._session_factory() as session:
            count = session.execute(
                sa.select(sa.func.count()).select_from(tbl).where(tbl.c.indicator_id == "ind-brand-3")
            ).scalar()
        assert count == 2


class TestBrandImpersonationListByIndicator:
    def test_list_by_indicator_returns_all_brands(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_indicator(store, "ind-brand-4")
        store.upsert_by_indicator_brand(indicator_id="ind-brand-4", brand="Amazon")
        store.upsert_by_indicator_brand(indicator_id="ind-brand-4", brand="Google")

        results = store.list_by_indicator("ind-brand-4")
        assert len(results) == 2
        brands = [r["brand"] for r in results]
        assert brands == ["Amazon", "Google"]  # ordered by brand ASC

    def test_list_by_indicator_empty(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.list_by_indicator("no-such-indicator") == []


class TestBrandImpersonationListByBrand:
    def test_list_by_brand_returns_rows_across_multiple_indicators(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_indicator(store, "ind-brand-5a")
        _seed_indicator(store, "ind-brand-5b")
        _seed_indicator(store, "ind-brand-5c")

        store.upsert_by_indicator_brand(indicator_id="ind-brand-5a", brand="Netflix")
        store.upsert_by_indicator_brand(indicator_id="ind-brand-5b", brand="Netflix")
        store.upsert_by_indicator_brand(indicator_id="ind-brand-5c", brand="Netflix")
        store.upsert_by_indicator_brand(indicator_id="ind-brand-5a", brand="Hulu")  # different brand

        netflix_results = store.list_by_brand("Netflix")
        assert len(netflix_results) == 3
        indicator_ids = {r["indicator_id"] for r in netflix_results}
        assert indicator_ids == {"ind-brand-5a", "ind-brand-5b", "ind-brand-5c"}

    def test_list_by_brand_empty(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.list_by_brand("UnknownBrand") == []
