"""Tests for RegistrantPivotStore."""

from __future__ import annotations

import sqlalchemy as sa

from i4g.store.registrant_pivot_store import RegistrantPivotStore
from i4g.store.sql import METADATA


def _make_store(tmp_path) -> RegistrantPivotStore:
    db_path = tmp_path / "test_registrant_pivot.db"
    return RegistrantPivotStore(db_path=str(db_path))


def _seed_actor(store: RegistrantPivotStore, actor_id: str) -> None:
    with store._session_factory() as session:
        session.execute(
            sa.insert(METADATA.tables["threat_actors"]).values(
                actor_id=actor_id,
                display_name="Test Actor",
            )
        )
        session.commit()


class TestRegistrantPivotStore:
    def test_upsert_inserts_new(self, tmp_path):
        store = _make_store(tmp_path)
        res = store.upsert(pivot_type="email", pivot_value="test@example.com")
        assert res["pivot_id"] is not None
        assert res["pivot_type"] == "email"
        assert res["pivot_value"] == "test@example.com"

        fetched = store.get(res["pivot_id"])
        assert fetched is not None
        assert fetched["pivot_value"] == "test@example.com"

    def test_upsert_updates_existing_by_type_value(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_actor(store, "actor-1")

        # Insert
        res1 = store.upsert(
            pivot_type="email",
            pivot_value="shared@example.com",
            actor_id=None,
        )

        # Update, link actor
        res2 = store.upsert(
            pivot_type="email",
            pivot_value="shared@example.com",
            actor_id="actor-1",
        )

        assert res1["pivot_id"] == res2["pivot_id"]
        assert res2["actor_id"] == "actor-1"

    def test_list_by_actor(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_actor(store, "actor-1")

        store.upsert(pivot_type="email", pivot_value="e1@test.com", actor_id="actor-1")
        store.upsert(pivot_type="name", pivot_value="John Doe", actor_id="actor-1")

        res = store.list_by_actor("actor-1")
        assert len(res) == 2
        assert {r["pivot_value"] for r in res} == {"e1@test.com", "John Doe"}
