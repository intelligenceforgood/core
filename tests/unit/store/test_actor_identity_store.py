"""Tests for ActorIdentityStore."""

from __future__ import annotations

import sqlalchemy as sa

from i4g.store.actor_identity_store import ActorIdentityStore
from i4g.store.sql import METADATA


def _make_store(tmp_path) -> ActorIdentityStore:
    db_path = tmp_path / "test_actor_identity.db"
    return ActorIdentityStore(db_path=str(db_path))


def _seed_actor(store: ActorIdentityStore, actor_id: str) -> None:
    """Seed a threat_actors row directly so FK constraint is satisfied."""
    with store._session_factory() as session:
        session.execute(
            sa.insert(METADATA.tables["threat_actors"]).values(
                actor_id=actor_id,
                display_name="Test Actor",
            )
        )
        session.commit()


class TestActorIdentityUpsert:
    def test_upsert_inserts_new_identity(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_actor(store, "actor-1")

        identity = store.upsert_by_handle(actor_id="actor-1", platform="twitter", handle="alice")
        assert identity["identity_id"] is not None
        assert identity["platform"] == "twitter"
        assert identity["handle"] == "alice"

    def test_upsert_is_idempotent(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_actor(store, "actor-2")

        store.upsert_by_handle(actor_id="actor-2", platform="twitter", handle="bob")
        store.upsert_by_handle(actor_id="actor-2", platform="twitter", handle="bob")

        results = store.list_by_actor("actor-2")
        assert len(results) == 1

    def test_upsert_updates_last_seen(self, tmp_path):
        from datetime import UTC, datetime

        store = _make_store(tmp_path)
        _seed_actor(store, "actor-3")

        t1 = datetime(2026, 1, 1, tzinfo=UTC)
        t2 = datetime(2026, 6, 1, tzinfo=UTC)
        store.upsert_by_handle(actor_id="actor-3", platform="telegram", handle="carol", last_seen_at=t1)
        updated = store.upsert_by_handle(actor_id="actor-3", platform="telegram", handle="carol", last_seen_at=t2)
        # SQLite stores datetimes without timezone; compare naive value
        stored = updated["last_seen_at"]
        assert (stored.replace(tzinfo=None) if stored.tzinfo else stored) == t2.replace(tzinfo=None)


class TestActorIdentityListByActor:
    def test_list_by_actor_returns_all_identities(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_actor(store, "actor-4")

        store.upsert_by_handle(actor_id="actor-4", platform="twitter", handle="dave_t")
        store.upsert_by_handle(actor_id="actor-4", platform="telegram", handle="dave_tg")

        results = store.list_by_actor("actor-4")
        assert len(results) == 2

    def test_list_by_actor_empty(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.list_by_actor("no-such-actor") == []


class TestActorIdentityAppendHistory:
    def test_append_username_history_adds_entry(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_actor(store, "actor-5")

        identity = store.upsert_by_handle(actor_id="actor-5", platform="twitter", handle="eve")
        updated = store.append_username_history(identity["identity_id"], "eve_old")
        assert "eve_old" in updated["username_history"]

    def test_append_username_history_no_duplicates(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_actor(store, "actor-6")

        identity = store.upsert_by_handle(actor_id="actor-6", platform="twitter", handle="frank")
        store.append_username_history(identity["identity_id"], "frank_old")
        updated = store.append_username_history(identity["identity_id"], "frank_old")
        assert updated["username_history"].count("frank_old") == 1

    def test_append_username_history_returns_none_for_missing(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.append_username_history("no-such-id", "ghost") is None
