"""Tests for LeakRecordStore."""

from __future__ import annotations

import sqlalchemy as sa

from i4g.store.leak_record_store import LeakRecordStore
from i4g.store.sql import METADATA


def _make_store(tmp_path) -> LeakRecordStore:
    db_path = tmp_path / "test_leak_record.db"
    return LeakRecordStore(db_path=str(db_path))


def _seed_actor(store: LeakRecordStore, actor_id: str) -> None:
    with store._session_factory() as session:
        session.execute(
            sa.insert(METADATA.tables["threat_actors"]).values(
                actor_id=actor_id,
                display_name="Test Actor",
            )
        )
        session.commit()


class TestLeakRecordStore:
    def test_upsert_inserts_new(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_actor(store, "actor-1")

        prov = {"commit_sha": "abc", "team": "team_a", "record_id": "rec-1"}
        res = store.upsert(
            actor_id="actor-1",
            breach_name="Test Breach",
            email="test@example.com",
            source_provenance=prov,
        )
        assert res["leak_id"] is not None
        assert res["breach_name"] == "Test Breach"

        fetched = store.get(res["leak_id"])
        assert fetched is not None
        assert fetched["email"] == "test@example.com"

    def test_upsert_updates_existing_by_provenance(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_actor(store, "actor-1")

        prov = {"commit_sha": "abc", "team": "team_a", "record_id": "rec-1"}
        res1 = store.upsert(
            actor_id="actor-1",
            breach_name="Test Breach",
            email="old@example.com",
            source_provenance=prov,
        )

        # Upsert with same provenance
        res2 = store.upsert(
            actor_id="actor-1",
            breach_name="Test Breach",
            email="new@example.com",
            source_provenance=prov,
        )

        assert res1["leak_id"] == res2["leak_id"]
        assert res2["email"] == "new@example.com"

        all_recs = store.list_by_actor("actor-1")
        assert len(all_recs) == 1

    def test_list_by_actor(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_actor(store, "actor-1")
        store.upsert(actor_id="actor-1", breach_name="B1")
        store.upsert(actor_id="actor-1", breach_name="B2")

        res = store.list_by_actor("actor-1")
        assert len(res) == 2
        assert {r["breach_name"] for r in res} == {"B1", "B2"}
