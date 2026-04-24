"""Tests for BlocklistHitStore."""

from __future__ import annotations

import sqlalchemy as sa

from i4g.store.blocklist_hit_store import BlocklistHitStore
from i4g.store.sql import METADATA


def _make_store(tmp_path) -> BlocklistHitStore:
    db_path = tmp_path / "test_blocklist_hit.db"
    return BlocklistHitStore(db_path=str(db_path))


def _seed_indicator(store: BlocklistHitStore, indicator_id: str) -> None:
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
                    raw_text_sha256=f"sha-{case_id}",
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


class TestBlocklistHitUpsert:
    def test_upsert_inserts_new_hit(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_indicator(store, "ind-1")

        hit = store.upsert(indicator_id="ind-1", source="spamhaus")
        assert hit["hit_id"] is not None
        assert hit["source"] == "spamhaus"

    def test_upsert_is_idempotent(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_indicator(store, "ind-2")

        store.upsert(indicator_id="ind-2", source="blocklist_de")
        store.upsert(indicator_id="ind-2", source="blocklist_de")

        results = store.list_by_indicator("ind-2")
        assert len(results) == 1

    def test_upsert_distinct_sources_create_separate_rows(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_indicator(store, "ind-3")

        store.upsert(indicator_id="ind-3", source="spamhaus")
        store.upsert(indicator_id="ind-3", source="blocklist_de")

        results = store.list_by_indicator("ind-3")
        assert len(results) == 2


class TestBlocklistHitListByIndicator:
    def test_list_by_indicator_returns_all_hits(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_indicator(store, "ind-4")

        store.upsert(indicator_id="ind-4", source="src-A")
        store.upsert(indicator_id="ind-4", source="src-B")

        results = store.list_by_indicator("ind-4")
        assert len(results) == 2

    def test_list_by_indicator_empty(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.list_by_indicator("no-such-indicator") == []


class TestBlocklistHitListBySource:
    def test_list_by_source_returns_matching_hits(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_indicator(store, "ind-5")
        _seed_indicator(store, "ind-6")

        store.upsert(indicator_id="ind-5", source="spamhaus")
        store.upsert(indicator_id="ind-6", source="spamhaus")
        store.upsert(indicator_id="ind-5", source="other-list")

        results = store.list_by_source("spamhaus")
        assert len(results) == 2

    def test_list_by_source_empty(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.list_by_source("nonexistent-source") == []
