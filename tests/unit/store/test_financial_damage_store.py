"""Tests for FinancialDamageStore."""

from __future__ import annotations

from decimal import Decimal

import sqlalchemy as sa

from i4g.store.financial_damage_store import FinancialDamageStore
from i4g.store.sql import METADATA


def _make_store(tmp_path) -> FinancialDamageStore:
    db_path = tmp_path / "test_financial_damage.db"
    return FinancialDamageStore(db_path=str(db_path))


def _seed_campaign(store: FinancialDamageStore, campaign_id: str) -> None:
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


class TestFinancialDamageCreate:
    def test_create_returns_all_fields(self, tmp_path):
        store = _make_store(tmp_path)
        result = store.create(
            currency="USDT",
            amount_claimed=Decimal("500.123456789012345678"),
            verification_status="unverified",
        )
        assert result["claim_id"] is not None
        assert result["currency"] == "USDT"
        assert Decimal(str(result["amount_claimed"])) == Decimal("500.123456789012345678")
        assert result["verification_status"] == "unverified"
        assert result["amount_confirmed"] is None

    def test_create_persists_and_get_reads_back(self, tmp_path):
        store = _make_store(tmp_path)
        created = store.create(
            currency="BTC",
            amount_claimed=Decimal("1.5"),
            amount_confirmed=Decimal("1.2"),
            tx_hash="0xabc",
            wallet_address="bc1q...",
            verification_status="confirmed",
            source_provenance={"source": "phishdestroy.archive.damage", "record_id": "d-001"},
        )
        fetched = store.get(created["claim_id"])
        assert fetched is not None
        assert fetched["verification_status"] == "confirmed"
        assert fetched["tx_hash"] == "0xabc"
        assert fetched["source_provenance"]["record_id"] == "d-001"

    def test_get_returns_none_for_missing(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.get("no-such-id") is None


class TestFinancialDamageUpsertByProvenance:
    def test_upsert_inserts_new_row(self, tmp_path):
        store = _make_store(tmp_path)
        prov = {"source": "phishdestroy.archive.damage", "record_id": "d-100"}
        result = store.upsert_by_provenance(
            source_provenance=prov,
            currency="ETH",
            amount_claimed=Decimal("2.0"),
        )
        assert result["claim_id"] is not None
        assert result["currency"] == "ETH"

    def test_upsert_idempotency_same_key_updates_content(self, tmp_path):
        store = _make_store(tmp_path)
        prov = {"source": "phishdestroy.archive.damage", "record_id": "d-200"}

        first = store.upsert_by_provenance(
            source_provenance=prov,
            currency="USDT",
            amount_claimed=Decimal("100"),
        )
        second = store.upsert_by_provenance(
            source_provenance=prov,
            currency="USDT",
            amount_claimed=Decimal("150"),
            amount_confirmed=Decimal("150"),
            verification_status="confirmed",
        )

        assert first["claim_id"] == second["claim_id"]
        assert Decimal(str(second["amount_claimed"])) == Decimal("150")
        assert second["verification_status"] == "confirmed"

        tbl = METADATA.tables["financial_damage_claims"]
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


class TestFinancialDamageListByCampaign:
    def test_list_by_campaign_returns_all(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_campaign(store, "camp-B")
        store.create(currency="USDT", amount_claimed=Decimal("10"), campaign_id="camp-B")
        store.create(currency="BTC", amount_claimed=Decimal("0.1"), campaign_id="camp-B")
        store.create(currency="ETH", amount_claimed=Decimal("5"))  # no campaign

        results = store.list_by_campaign("camp-B")
        assert len(results) == 2

    def test_list_by_campaign_filtered_by_currency(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_campaign(store, "camp-C")
        store.create(currency="USDT", amount_claimed=Decimal("10"), campaign_id="camp-C")
        store.create(currency="USDT", amount_claimed=Decimal("20"), campaign_id="camp-C")
        store.create(currency="BTC", amount_claimed=Decimal("0.1"), campaign_id="camp-C")

        results = store.list_by_campaign("camp-C", currency="USDT")
        assert len(results) == 2
        assert all(r["currency"] == "USDT" for r in results)


class TestFinancialDamageTotalsByCurrency:
    def test_totals_span_multiple_currencies(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_campaign(store, "camp-D")
        # 3 USDT claims: 100 + 200 + 300 = 600 claimed; 100 + 200 = 300 confirmed
        store.create(
            currency="USDT",
            amount_claimed=Decimal("100"),
            amount_confirmed=Decimal("100"),
            campaign_id="camp-D",
        )
        store.create(
            currency="USDT",
            amount_claimed=Decimal("200"),
            amount_confirmed=Decimal("200"),
            campaign_id="camp-D",
        )
        store.create(
            currency="USDT",
            amount_claimed=Decimal("300"),
            amount_confirmed=None,
            campaign_id="camp-D",
        )
        # 2 BTC claims: 0.5 + 1.0 = 1.5 claimed; 0.5 confirmed
        store.create(
            currency="BTC",
            amount_claimed=Decimal("0.5"),
            amount_confirmed=Decimal("0.5"),
            campaign_id="camp-D",
        )
        store.create(
            currency="BTC",
            amount_claimed=Decimal("1.0"),
            amount_confirmed=None,
            campaign_id="camp-D",
        )

        totals = store.totals_by_currency("camp-D")

        assert set(totals.keys()) == {"USDT", "BTC"}
        assert totals["USDT"]["claimed"] == Decimal("600")
        assert totals["USDT"]["confirmed"] == Decimal("300")
        assert totals["BTC"]["claimed"] == Decimal("1.5")
        assert totals["BTC"]["confirmed"] == Decimal("0.5")

    def test_totals_empty_campaign(self, tmp_path):
        store = _make_store(tmp_path)
        totals = store.totals_by_currency("no-such-campaign")
        assert totals == {}
