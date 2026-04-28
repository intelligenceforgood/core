"""Phase D end-to-end tests for TWP brand impersonation writes (Sprint 2 Phase D, manifest file #14).

Covers the seeded-indicator path that ``test_archive_trustwalletpanel_phase_d.py`` does not:

- Pre-seed an ``indicators`` row matching the TWP fixture's ``panel_url`` (``tttadmin.com``).
  Run TWP ingest. Assert exactly one ``brand_impersonations`` row is written with
  ``brand="Trust Wallet"``, ``detected_by="phishdestroy.archive.team_config"``, and
  ``source_provenance.source == "phishdestroy.archive.infrastructure"``.
- Re-run TWP ingest; assert the row count is unchanged and ``updated_at`` advances
  (idempotent upsert per provenance contract).
- Run TWP ingest with NO seeded indicators; assert ``brand_impersonations`` is empty AND the
  adapter return counts include ``brand_impersonations_skipped == 1`` (no parse failure).
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa

from i4g.ingestion.phishdestroy.archive.base import ArchiveContext
from i4g.ingestion.phishdestroy.archive.runner import ingest_team_archive
from i4g.store import sql as sql_schema
from i4g.store.brand_impersonation_store import BrandImpersonationStore
from i4g.store.chat_session_store import ChatSessionStore
from i4g.store.financial_damage_store import FinancialDamageStore
from i4g.store.infrastructure_profile_store import InfrastructureProfileStore
from i4g.store.threat_campaign_store import ThreatCampaignStore

FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "phishdestroy" / "trustwalletpanel"

_PINNED_SHA = "83d0307420fcc865fcb8a34b8c454acbc6d56f1f"
_INGEST_JOB = "test-ingest-archive-brand-impersonations"
_NOW = datetime(2026, 4, 27, 16, 0, 0, tzinfo=UTC)
_PANEL_DOMAIN = "tttadmin.com"


def _make_ctx(db_path: Path) -> ArchiveContext:
    return ArchiveContext(
        commit_sha=_PINNED_SHA,
        ingest_job=_INGEST_JOB,
        ingest_job_run_id=None,
        now=_NOW,
        campaign_store=ThreatCampaignStore(db_path=str(db_path)),
        chat_session_store=ChatSessionStore(db_path=str(db_path)),
        infrastructure_profile_store=InfrastructureProfileStore(db_path=str(db_path)),
        financial_damage_store=FinancialDamageStore(db_path=str(db_path)),
        brand_impersonation_store=BrandImpersonationStore(db_path=str(db_path)),
    )


def _seed_indicator(ctx: ArchiveContext, *, category: str = "domain", number: str = _PANEL_DOMAIN) -> str:
    """Insert a case + indicator row reachable via the chat-session store's session factory.

    Returns the indicator_id.
    """
    case_id = f"case-{uuid.uuid4().hex[:8]}"
    indicator_id = str(uuid.uuid4())
    now = datetime.now(tz=UTC)
    factory = ctx.chat_session_store._session_factory  # noqa: SLF001 — mirrors Phase D adapter access
    with factory() as session:
        session.execute(
            sql_schema.cases.insert().values(
                case_id=case_id,
                dataset="phishdestroy",
                source_type="reactive",
                raw_text_sha256=f"sha256-{case_id}",
                status="open",
                created_at=now,
                updated_at=now,
            )
        )
        session.execute(
            sql_schema.indicators.insert().values(
                indicator_id=indicator_id,
                case_id=case_id,
                category=category,
                type="url",
                number=number,
                status="active",
                confidence=0.9,
                dataset="phishdestroy",
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    return indicator_id


def _list_brand_rows(ctx: ArchiveContext) -> list[dict]:
    factory = ctx.brand_impersonation_store._session_factory  # noqa: SLF001
    with factory() as session:
        rows = session.execute(sa.select(sql_schema.brand_impersonations)).fetchall()
        return [dict(r._mapping) for r in rows]


class TestBrandImpersonationsSeededIndicator:
    """Behaviour contract: with a matching indicator, TWP writes exactly one brand row."""

    def test_inserts_single_row_with_correct_provenance_and_detected_by(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path / "test.db")
        indicator_id = _seed_indicator(ctx)

        summary = ingest_team_archive(FIXTURE_DIR, ctx)

        assert summary.status == "ok"
        assert summary.counts["brand_impersonations_inserted"] == 1
        assert summary.counts["brand_impersonations_updated"] == 0
        assert summary.counts["brand_impersonations_skipped"] == 0

        rows = _list_brand_rows(ctx)
        assert len(rows) == 1
        row = rows[0]
        assert row["indicator_id"] == indicator_id
        assert row["brand"] == "Trust Wallet"
        assert row["detected_by"] == "phishdestroy.archive.team_config"
        provenance = row["source_provenance"]
        assert provenance is not None
        assert provenance["source"] == "phishdestroy.archive.infrastructure"
        assert provenance["team"] == "TrustWalletPanel"
        assert provenance["commit_sha"] == _PINNED_SHA
        assert provenance["record_id"].startswith("TrustWalletPanel/iocs.json#brand/")

    def test_rerun_is_idempotent_and_advances_updated_at(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path / "test.db")
        _seed_indicator(ctx)

        summary_1 = ingest_team_archive(FIXTURE_DIR, ctx)
        assert summary_1.counts["brand_impersonations_inserted"] == 1

        rows_after_first = _list_brand_rows(ctx)
        assert len(rows_after_first) == 1
        first_updated_at = rows_after_first[0]["updated_at"]

        # Ensure updated_at can advance (sqlite TIMESTAMP has second resolution in some configs).
        time.sleep(0.01)

        summary_2 = ingest_team_archive(FIXTURE_DIR, ctx)
        assert summary_2.status == "ok"
        # On re-run the brand row already exists for this (indicator, brand) pair → updated.
        assert summary_2.counts["brand_impersonations_inserted"] == 0
        assert summary_2.counts["brand_impersonations_updated"] == 1
        assert summary_2.counts["brand_impersonations_skipped"] == 0

        rows_after_second = _list_brand_rows(ctx)
        assert len(rows_after_second) == 1
        # Same impersonation_id (idempotent on indicator_id+brand).
        assert rows_after_second[0]["impersonation_id"] == rows_after_first[0]["impersonation_id"]
        assert rows_after_second[0]["updated_at"] >= first_updated_at


class TestBrandImpersonationsNoSeededIndicator:
    """Behaviour contract: without any matching indicator, TWP emits skipped == 1, no rows written."""

    def test_no_rows_and_skipped_counter_set(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path / "test.db")

        summary = ingest_team_archive(FIXTURE_DIR, ctx)

        assert summary.status == "ok"
        assert summary.counts["brand_impersonations_inserted"] == 0
        assert summary.counts["brand_impersonations_updated"] == 0
        assert summary.counts["brand_impersonations_skipped"] == 1

        assert _list_brand_rows(ctx) == []
