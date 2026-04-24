"""Tests for ThreatActorStore."""

from __future__ import annotations

import sqlalchemy as sa

from i4g.store.sql import METADATA
from i4g.store.threat_actor_store import ThreatActorStore


def _make_store(tmp_path) -> ThreatActorStore:
    db_path = tmp_path / "test_threat_actor.db"
    return ThreatActorStore(db_path=str(db_path))


def _seed_campaign(store: ThreatActorStore, campaign_id: str) -> None:
    """Seed a campaigns row directly so FK constraint is satisfied."""
    with store._session_factory() as session:
        session.execute(
            sa.insert(METADATA.tables["campaigns"]).values(
                campaign_id=campaign_id,
                name="Test Campaign",
            )
        )
        session.commit()


class TestThreatActorCreate:
    def test_create_returns_actor_id(self, tmp_path):
        store = _make_store(tmp_path)
        actor = store.create(display_name="Alice")
        assert actor["actor_id"] is not None
        assert actor["display_name"] == "Alice"

    def test_create_persists_row(self, tmp_path):
        store = _make_store(tmp_path)
        actor = store.create(display_name="Bob", role="admin")
        fetched = store.get(actor["actor_id"])
        assert fetched is not None
        assert fetched["role"] == "admin"

    def test_get_returns_none_for_missing(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.get("nonexistent-id") is None


class TestThreatActorListByCampaign:
    def test_list_by_campaign_returns_matching_actors(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_campaign(store, "camp-1")
        store.create(display_name="Actor1", campaign_id="camp-1")
        store.create(display_name="Actor2", campaign_id="camp-1")
        store.create(display_name="Actor3")

        results = store.list_by_campaign("camp-1")
        assert len(results) == 2
        names = {r["display_name"] for r in results}
        assert names == {"Actor1", "Actor2"}

    def test_list_by_campaign_empty(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.list_by_campaign("no-such-campaign") == []


class TestThreatActorFindByIdentity:
    def test_find_by_identity_returns_actor(self, tmp_path):
        from i4g.store.actor_identity_store import ActorIdentityStore

        store = _make_store(tmp_path)
        actor = store.create(display_name="Charlie")
        actor_id = actor["actor_id"]

        id_store = ActorIdentityStore(db_path=str(tmp_path / "test_threat_actor.db"))
        identity = id_store.upsert_by_handle(actor_id=actor_id, platform="twitter", handle="charlie_x")

        found = store.find_by_identity(identity["identity_id"])
        assert found is not None
        assert found["actor_id"] == actor_id

    def test_find_by_identity_returns_none_for_missing(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.find_by_identity("nonexistent-identity-id") is None
