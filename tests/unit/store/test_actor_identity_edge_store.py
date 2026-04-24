"""Tests for ActorIdentityEdgeStore."""

from __future__ import annotations

import sqlalchemy as sa

from i4g.store.actor_identity_edge_store import ActorIdentityEdgeStore
from i4g.store.sql import METADATA


def _make_store(tmp_path) -> ActorIdentityEdgeStore:
    db_path = tmp_path / "test_actor_identity_edge.db"
    return ActorIdentityEdgeStore(db_path=str(db_path))


def _seed_identity(store: ActorIdentityEdgeStore, identity_id: str) -> None:
    """Seed actor_identities (and threat_actors) rows to satisfy FKs."""
    actor_id = f"actor-for-{identity_id}"
    with store._session_factory() as session:
        # Insert parent actor first
        existing_actor = session.execute(
            sa.select(METADATA.tables["threat_actors"]).where(METADATA.tables["threat_actors"].c.actor_id == actor_id)
        ).first()
        if existing_actor is None:
            session.execute(
                sa.insert(METADATA.tables["threat_actors"]).values(
                    actor_id=actor_id,
                    display_name=f"Actor for {identity_id}",
                )
            )
        session.execute(
            sa.insert(METADATA.tables["actor_identities"]).values(
                identity_id=identity_id,
                actor_id=actor_id,
                platform="twitter",
                handle=f"handle-{identity_id}",
            )
        )
        session.commit()


class TestActorIdentityEdgeUpsert:
    def test_upsert_creates_edge(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_identity(store, "id-A")
        _seed_identity(store, "id-B")

        edge = store.upsert_edge(
            source_identity_id="id-A",
            target_identity_id="id-B",
            edge_type="same_person",
        )
        assert edge["edge_id"] is not None
        assert edge["edge_type"] == "same_person"

    def test_upsert_is_idempotent(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_identity(store, "id-C")
        _seed_identity(store, "id-D")

        store.upsert_edge(source_identity_id="id-C", target_identity_id="id-D", edge_type="linked")
        store.upsert_edge(source_identity_id="id-C", target_identity_id="id-D", edge_type="linked")

        neighbors = store.neighbors("id-C")
        assert len(neighbors) == 1

    def test_upsert_updates_weight(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_identity(store, "id-E")
        _seed_identity(store, "id-F")

        store.upsert_edge(source_identity_id="id-E", target_identity_id="id-F", edge_type="alias", weight=0.5)
        updated = store.upsert_edge(source_identity_id="id-E", target_identity_id="id-F", edge_type="alias", weight=0.9)
        assert float(updated["weight"]) == 0.9


class TestActorIdentityEdgeNeighbors:
    def test_neighbors_returns_edges_as_source(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_identity(store, "id-G")
        _seed_identity(store, "id-H")
        _seed_identity(store, "id-I")

        store.upsert_edge(source_identity_id="id-G", target_identity_id="id-H", edge_type="linked")
        store.upsert_edge(source_identity_id="id-G", target_identity_id="id-I", edge_type="linked")

        neighbors = store.neighbors("id-G")
        assert len(neighbors) == 2

    def test_neighbors_returns_edges_as_target(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_identity(store, "id-J")
        _seed_identity(store, "id-K")

        store.upsert_edge(source_identity_id="id-J", target_identity_id="id-K", edge_type="linked")

        neighbors = store.neighbors("id-K")
        assert len(neighbors) == 1

    def test_neighbors_empty(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.neighbors("no-such-identity") == []
