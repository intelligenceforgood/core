"""Tests for ChatSessionStore."""

from __future__ import annotations

import sqlalchemy as sa

from i4g.store.chat_session_store import ChatSessionStore
from i4g.store.sql import METADATA


def _make_store(tmp_path) -> ChatSessionStore:
    db_path = tmp_path / "test_chat_session.db"
    return ChatSessionStore(db_path=str(db_path))


def _seed_campaign(store: ChatSessionStore, campaign_id: str) -> None:
    """Seed a campaigns row to satisfy FK."""
    with store._session_factory() as session:
        existing = session.execute(
            sa.select(METADATA.tables["campaigns"]).where(METADATA.tables["campaigns"].c.campaign_id == campaign_id)
        ).first()
        if existing is None:
            session.execute(
                sa.insert(METADATA.tables["campaigns"]).values(
                    campaign_id=campaign_id,
                    name="Test Campaign",
                )
            )
            session.commit()


def _seed_actor(store: ChatSessionStore, actor_id: str) -> None:
    """Seed a threat_actors row to satisfy FK."""
    with store._session_factory() as session:
        session.execute(
            sa.insert(METADATA.tables["threat_actors"]).values(
                actor_id=actor_id,
                display_name="Test Actor",
            )
        )
        session.commit()


class TestChatSessionCreate:
    def test_create_returns_all_fields(self, tmp_path):
        store = _make_store(tmp_path)
        result = store.create(chat_ref="ref-001", message_count=5, language="en")
        assert result["session_id"] is not None
        assert result["chat_ref"] == "ref-001"
        assert result["message_count"] == 5
        assert result["language"] == "en"
        assert result["deposit_demand"] is False
        assert result["victim_confirmed_send"] is False

    def test_create_persists_and_get_reads_back(self, tmp_path):
        store = _make_store(tmp_path)
        created = store.create(
            chat_ref="ref-002",
            deposit_demand=True,
            victim_confirmed_send=True,
            source_provenance={"source": "phishdestroy.archive.chat", "record_id": "r-1"},
        )
        fetched = store.get(created["session_id"])
        assert fetched is not None
        assert fetched["session_id"] == created["session_id"]
        assert fetched["deposit_demand"] is True
        assert fetched["victim_confirmed_send"] is True
        assert fetched["source_provenance"]["record_id"] == "r-1"

    def test_get_returns_none_for_missing(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.get("nonexistent-id") is None


class TestChatSessionUpsertByProvenance:
    def test_upsert_inserts_new_row(self, tmp_path):
        store = _make_store(tmp_path)
        prov = {"source": "phishdestroy.archive.chat", "record_id": "chat-001"}
        result = store.upsert_by_provenance(source_provenance=prov, chat_ref="ref-A", message_count=3)
        assert result["session_id"] is not None
        assert result["chat_ref"] == "ref-A"

    def test_upsert_idempotency_same_key_updates_content(self, tmp_path):
        store = _make_store(tmp_path)
        prov = {"source": "phishdestroy.archive.chat", "record_id": "chat-002"}

        first = store.upsert_by_provenance(source_provenance=prov, chat_ref="ref-B1", message_count=1)
        second = store.upsert_by_provenance(source_provenance=prov, chat_ref="ref-B2", message_count=10)

        # Same session_id; content updated
        assert first["session_id"] == second["session_id"]
        assert second["chat_ref"] == "ref-B2"
        assert second["message_count"] == 10

        # Exactly one row in the table for this provenance key
        tbl = METADATA.tables["chat_sessions"]
        with store._session_factory() as session:
            count = session.execute(
                sa.select(sa.func.count())
                .select_from(tbl)
                .where(
                    sa.and_(
                        sa.func.json_extract(tbl.c.source_provenance, "$.source") == prov["source"],
                        sa.func.json_extract(tbl.c.source_provenance, "$.record_id") == prov["record_id"],
                    )
                )
            ).scalar()
        assert count == 1

    def test_upsert_different_keys_create_separate_rows(self, tmp_path):
        store = _make_store(tmp_path)
        prov_a = {"source": "phishdestroy.archive.chat", "record_id": "chat-003a"}
        prov_b = {"source": "phishdestroy.archive.chat", "record_id": "chat-003b"}
        store.upsert_by_provenance(source_provenance=prov_a, chat_ref="ref-C1")
        store.upsert_by_provenance(source_provenance=prov_b, chat_ref="ref-C2")

        tbl = METADATA.tables["chat_sessions"]
        with store._session_factory() as session:
            count = session.execute(sa.select(sa.func.count()).select_from(tbl)).scalar()
        assert count == 2


class TestChatSessionListByCampaign:
    def test_list_by_campaign_returns_matching_rows(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_campaign(store, "camp-A")
        store.create(chat_ref="r1", campaign_id="camp-A")
        store.create(chat_ref="r2", campaign_id="camp-A")
        store.create(chat_ref="r3")  # no campaign

        results = store.list_by_campaign("camp-A")
        assert len(results) == 2
        refs = {r["chat_ref"] for r in results}
        assert refs == {"r1", "r2"}

    def test_list_by_campaign_empty(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.list_by_campaign("no-such-campaign") == []


class TestChatSessionListByActor:
    def test_list_by_actor_returns_matching_rows(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_actor(store, "actor-X")
        store.create(chat_ref="ra1", actor_id="actor-X")
        store.create(chat_ref="ra2", actor_id="actor-X")
        store.create(chat_ref="ra3")  # no actor

        results = store.list_by_actor("actor-X")
        assert len(results) == 2

    def test_list_by_actor_empty(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.list_by_actor("no-such-actor") == []
