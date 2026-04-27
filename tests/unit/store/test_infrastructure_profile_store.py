"""Tests for InfrastructureProfileStore."""

from __future__ import annotations

import sqlalchemy as sa

from i4g.store.infrastructure_profile_store import InfrastructureProfileStore
from i4g.store.sql import METADATA


def _make_store(tmp_path) -> InfrastructureProfileStore:
    db_path = tmp_path / "test_infra_profile.db"
    return InfrastructureProfileStore(db_path=str(db_path))


def _seed_campaign(store: InfrastructureProfileStore, campaign_id: str) -> None:
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


class TestInfrastructureProfileUpsert:
    def test_upsert_inserts_new_row(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_campaign(store, "camp-infra-1")
        result = store.upsert_by_campaign_domain(
            campaign_id="camp-infra-1",
            primary_domain="evil.com",
            auth_model="jwt",
            source_maps_exposed=True,
            source_provenance={"source": "phishdestroy.archive.infrastructure", "record_id": "i-001"},
        )
        assert result["profile_id"] is not None
        assert result["campaign_id"] == "camp-infra-1"
        assert result["primary_domain"] == "evil.com"
        assert result["auth_model"] == "jwt"
        assert result["source_maps_exposed"] is True

    def test_upsert_idempotency_same_key_updates_content(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_campaign(store, "camp-infra-2")
        first = store.upsert_by_campaign_domain(
            campaign_id="camp-infra-2",
            primary_domain="target.io",
            auth_model="basic",
        )
        second = store.upsert_by_campaign_domain(
            campaign_id="camp-infra-2",
            primary_domain="target.io",
            auth_model="oauth2",
            source_maps_exposed=True,
            tech_stack={"frontend": "React"},
        )

        # Same profile_id; content updated
        assert first["profile_id"] == second["profile_id"]
        assert second["auth_model"] == "oauth2"
        assert second["source_maps_exposed"] is True
        assert second["tech_stack"] == {"frontend": "React"}

        # Exactly one row for this (campaign_id, primary_domain)
        tbl = METADATA.tables["infrastructure_profiles"]
        with store._session_factory() as session:
            count = session.execute(
                sa.select(sa.func.count())
                .select_from(tbl)
                .where(
                    sa.and_(
                        tbl.c.campaign_id == "camp-infra-2",
                        tbl.c.primary_domain == "target.io",
                    )
                )
            ).scalar()
        assert count == 1

    def test_upsert_different_domains_create_separate_rows(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_campaign(store, "camp-infra-3")
        store.upsert_by_campaign_domain(campaign_id="camp-infra-3", primary_domain="a.com")
        store.upsert_by_campaign_domain(campaign_id="camp-infra-3", primary_domain="b.com")

        tbl = METADATA.tables["infrastructure_profiles"]
        with store._session_factory() as session:
            count = session.execute(
                sa.select(sa.func.count()).select_from(tbl).where(tbl.c.campaign_id == "camp-infra-3")
            ).scalar()
        assert count == 2


class TestInfrastructureProfileGet:
    def test_get_by_id_returns_row(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_campaign(store, "camp-infra-4")
        created = store.upsert_by_campaign_domain(
            campaign_id="camp-infra-4",
            primary_domain="c.com",
        )
        fetched = store.get(created["profile_id"])
        assert fetched is not None
        assert fetched["primary_domain"] == "c.com"

    def test_get_returns_none_for_missing(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.get("no-such-id") is None

    def test_get_by_campaign_returns_all_profiles(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_campaign(store, "camp-infra-5")
        store.upsert_by_campaign_domain(campaign_id="camp-infra-5", primary_domain="x.com")
        store.upsert_by_campaign_domain(campaign_id="camp-infra-5", primary_domain="y.com")
        store.upsert_by_campaign_domain(campaign_id="camp-infra-5", primary_domain="z.com")

        profiles = store.get_by_campaign("camp-infra-5")
        assert len(profiles) == 3
        domains = [p["primary_domain"] for p in profiles]
        assert domains == ["x.com", "y.com", "z.com"]  # ordered by primary_domain ASC

    def test_get_by_campaign_empty(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.get_by_campaign("no-such-campaign") == []
