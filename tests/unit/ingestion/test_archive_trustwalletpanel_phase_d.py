"""Phase D TWP adapter tests: financial_damage_claims and brand_impersonations (Sprint 2 Phase D).

Tests verify:
- `_ingest_successful_thefts` returns zero counts when successful_thefts/ is absent (TWP fixture).
- `brand_impersonations` returns zero counts when panel_url yields no indicators.
- Phase D new count keys are present in the adapter return dict.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from i4g.ingestion.phishdestroy.archive.base import ArchiveContext
from i4g.ingestion.phishdestroy.archive.runner import ingest_team_archive
from i4g.store.brand_impersonation_store import BrandImpersonationStore
from i4g.store.chat_session_store import ChatSessionStore
from i4g.store.financial_damage_store import FinancialDamageStore
from i4g.store.infrastructure_profile_store import InfrastructureProfileStore
from i4g.store.threat_campaign_store import ThreatCampaignStore

FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "phishdestroy" / "trustwalletpanel"

_PINNED_SHA = "83d0307420fcc865fcb8a34b8c454acbc6d56f1f"
_INGEST_JOB = "test-ingest-archive-phase-d"
_NOW = datetime(2026, 4, 27, 16, 0, 0, tzinfo=UTC)


def _make_ctx(tmp_path: Path) -> ArchiveContext:
    db = tmp_path / "test.db"
    return ArchiveContext(
        commit_sha=_PINNED_SHA,
        ingest_job=_INGEST_JOB,
        ingest_job_run_id=None,
        now=_NOW,
        campaign_store=ThreatCampaignStore(db_path=str(db)),
        chat_session_store=ChatSessionStore(db_path=str(db)),
        infrastructure_profile_store=InfrastructureProfileStore(db_path=str(db)),
        financial_damage_store=FinancialDamageStore(db_path=str(db)),
        brand_impersonation_store=BrandImpersonationStore(db_path=str(db)),
    )


class TestTrustWalletPanelPhaseDCounts:
    """Phase D count keys must be present and zero for TWP fixture (no successful_thefts/, no indicators)."""

    def test_financial_damage_claims_zero_when_no_successful_thefts_dir(self, tmp_path: Path) -> None:
        """TWP fixture has no successful_thefts/ — all financial_damage_claims_* must be 0."""
        ctx = _make_ctx(tmp_path)
        summary = ingest_team_archive(FIXTURE_DIR, ctx)

        assert summary.status == "ok"
        assert summary.counts["financial_damage_claims_inserted"] == 0
        assert summary.counts["financial_damage_claims_updated"] == 0
        assert summary.counts["financial_damage_claims_unchanged"] == 0
        assert summary.counts["financial_damage_claims_skipped"] == 0

    def test_brand_impersonations_skipped_when_no_matching_indicators(self, tmp_path: Path) -> None:
        """No indicators in DB for panel_url → skipped == 1, inserted/updated == 0 (Phase D contract).

        Brand linkage requires entity resolution (Sprint 3, PRD §5.5); when no indicator
        currently exists for the panel domain the adapter MUST surface this as a skip rather
        than a parse failure.
        """
        ctx = _make_ctx(tmp_path)
        summary = ingest_team_archive(FIXTURE_DIR, ctx)

        assert summary.status == "ok"
        assert summary.counts["brand_impersonations_inserted"] == 0
        assert summary.counts["brand_impersonations_updated"] == 0
        assert summary.counts["brand_impersonations_skipped"] == 1

    def test_all_phase_d_keys_present(self, tmp_path: Path) -> None:
        """All seven Phase D count keys must exist in the summary counts dict."""
        ctx = _make_ctx(tmp_path)
        summary = ingest_team_archive(FIXTURE_DIR, ctx)

        phase_d_keys = {
            "financial_damage_claims_inserted",
            "financial_damage_claims_updated",
            "financial_damage_claims_unchanged",
            "financial_damage_claims_skipped",
            "brand_impersonations_inserted",
            "brand_impersonations_updated",
            "brand_impersonations_skipped",
        }
        assert phase_d_keys <= set(summary.counts.keys())
