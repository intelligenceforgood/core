"""Golden contract test for the TrustWalletPanel archive adapter.

Assertions are pinned to the trimmed fixture files in
``tests/fixtures/phishdestroy/trustwalletpanel/``.
"""

from __future__ import annotations

import json
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
_INGEST_JOB = "test-ingest-archive"
_NOW = datetime(2026, 4, 27, 15, 30, 0, tzinfo=UTC)


def _make_ctx(tmp_path: Path) -> ArchiveContext:
    """Build an ArchiveContext backed by a shared tmp-path SQLite database."""
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


class TestTrustWalletPanelGoldenCounts:
    """Exact row-count assertions — the primary contract gate."""

    def test_chat_sessions_inserted(self, tmp_path: Path) -> None:
        """3 chat entries in fixture → 3 chat sessions inserted, 0 updated, 0 unchanged."""
        ctx = _make_ctx(tmp_path)
        summary = ingest_team_archive(FIXTURE_DIR, ctx)

        assert summary.status == "ok"
        assert summary.counts["chat_sessions_inserted"] == 3
        assert summary.counts["chat_sessions_updated"] == 0
        assert summary.counts["chat_sessions_unchanged"] == 0

    def test_infrastructure_profiles_inserted(self, tmp_path: Path) -> None:
        """1 panel_url in iocs.json → 1 infrastructure profile inserted, 0 updated, 0 unchanged."""
        ctx = _make_ctx(tmp_path)
        summary = ingest_team_archive(FIXTURE_DIR, ctx)

        assert summary.counts["infrastructure_profiles_inserted"] == 1
        assert summary.counts["infrastructure_profiles_updated"] == 0
        assert summary.counts["infrastructure_profiles_unchanged"] == 0

    def test_financial_damage_claims_zero(self, tmp_path: Path) -> None:
        """Phase B does not write financial_damage_claims rows."""
        ctx = _make_ctx(tmp_path)
        ingest_team_archive(FIXTURE_DIR, ctx)

        # Retrieve campaign_id via list_campaigns.
        campaigns = ctx.campaign_store.list_campaigns(limit=10)
        assert len(campaigns) == 1
        campaign_id = campaigns[0]["campaign_id"]

        claims = ctx.financial_damage_store.list_by_campaign(campaign_id)
        assert len(claims) == 0, "Phase B must not write financial_damage_claims rows"

    def test_brand_impersonations_zero(self, tmp_path: Path) -> None:
        """Phase B does not write brand_impersonation rows."""
        ctx = _make_ctx(tmp_path)
        ingest_team_archive(FIXTURE_DIR, ctx)

        # Verify via list_by_brand for the known brand name.
        impersonations = ctx.brand_impersonation_store.list_by_brand("TrustWalletPanel")
        assert len(impersonations) == 0, "Phase B must not write brand_impersonation rows"


class TestTrustWalletPanelIdempotency:
    """Running the adapter a second time must not double-insert rows."""

    def test_second_run_increments_unchanged_not_inserted(self, tmp_path: Path) -> None:
        """Second ingestion run: 0 inserted, 0 updated, 3 unchanged for chats."""
        ctx = _make_ctx(tmp_path)

        # First run.
        ingest_team_archive(FIXTURE_DIR, ctx)

        # Second run.
        summary2 = ingest_team_archive(FIXTURE_DIR, ctx)

        assert summary2.status == "ok"
        assert summary2.counts["chat_sessions_inserted"] == 0
        assert summary2.counts["chat_sessions_unchanged"] == 3
        # Infrastructure profile must be seen as updated (upsert refreshed it).
        assert summary2.counts["infrastructure_profiles_inserted"] == 0
        assert (
            summary2.counts["infrastructure_profiles_updated"] == 1
            or summary2.counts["infrastructure_profiles_unchanged"] == 1
        ), "Infra row must be counted as updated or unchanged on second run, not re-inserted"

    def test_campaign_not_duplicated_on_second_run(self, tmp_path: Path) -> None:
        """Only one ThreatCampaign row must exist after two ingestion runs."""
        ctx = _make_ctx(tmp_path)

        ingest_team_archive(FIXTURE_DIR, ctx)
        ingest_team_archive(FIXTURE_DIR, ctx)

        campaigns = ctx.campaign_store.list_campaigns(limit=10)
        assert len(campaigns) == 1, "Idempotent run must not create duplicate campaign rows"


class TestTrustWalletPanelProvenance:
    """Source provenance fields must match the §Provenance contract."""

    def test_chat_session_provenance_fields(self, tmp_path: Path) -> None:
        """Every chat session must carry the correct provenance fields."""
        ctx = _make_ctx(tmp_path)
        ingest_team_archive(FIXTURE_DIR, ctx)

        campaigns = ctx.campaign_store.list_campaigns(limit=10)
        campaign_id = campaigns[0]["campaign_id"]
        sessions = ctx.chat_session_store.list_by_campaign(campaign_id, limit=100)

        assert len(sessions) == 3
        for sess in sessions:
            prov = sess.get("source_provenance")
            if isinstance(prov, str):
                prov = json.loads(prov)
            assert isinstance(prov, dict), "source_provenance must be a dict"
            assert prov.get("source") == "phishdestroy.archive.chat"
            assert prov.get("team") == "TrustWalletPanel"
            assert prov.get("commit_sha") == _PINNED_SHA
            assert prov.get("ingest_job") == _INGEST_JOB
            record_id: str = prov.get("record_id", "")
            assert record_id.startswith("TrustWalletPanel/chats_translated.json#")

    def test_infrastructure_profile_provenance_fields(self, tmp_path: Path) -> None:
        """Infrastructure profile must carry the correct provenance fields."""
        ctx = _make_ctx(tmp_path)
        ingest_team_archive(FIXTURE_DIR, ctx)

        campaigns = ctx.campaign_store.list_campaigns(limit=10)
        campaign_id = campaigns[0]["campaign_id"]
        profiles = ctx.infrastructure_profile_store.get_by_campaign(campaign_id)

        assert len(profiles) == 1
        prov = profiles[0].get("source_provenance")
        if isinstance(prov, str):
            prov = json.loads(prov)
        assert isinstance(prov, dict)
        assert prov.get("source") == "phishdestroy.archive.infrastructure"
        assert prov.get("team") == "TrustWalletPanel"
        assert prov.get("commit_sha") == _PINNED_SHA
        assert prov.get("record_id") == "TrustWalletPanel/iocs.json#/panel_url"


class TestTrustWalletPanelDepositDemandHeuristic:
    """Deposit-demand flag must be set correctly per entry."""

    def _get_sessions_by_record_suffix(self, sessions: list[dict], suffix: str) -> list[dict]:
        """Filter sessions whose provenance record_id ends with *suffix*."""
        result = []
        for sess in sessions:
            prov = sess.get("source_provenance")
            if isinstance(prov, str):
                try:
                    prov = json.loads(prov)
                except json.JSONDecodeError:
                    continue
            if isinstance(prov, dict) and prov.get("record_id", "").endswith(suffix):
                result.append(sess)
        return result

    def test_entry_7_deposit_demand_true(self, tmp_path: Path) -> None:
        """Entry id=7 has 'deposit' in admin message → deposit_demand=True."""
        ctx = _make_ctx(tmp_path)
        ingest_team_archive(FIXTURE_DIR, ctx)

        campaigns = ctx.campaign_store.list_campaigns(limit=10)
        sessions = ctx.chat_session_store.list_by_campaign(campaigns[0]["campaign_id"], limit=100)
        matching = self._get_sessions_by_record_suffix(sessions, "#7")
        assert len(matching) == 1, "Entry 7 must produce exactly one chat session"
        assert matching[0].get("deposit_demand") is True

    def test_entry_92_deposit_demand_true(self, tmp_path: Path) -> None:
        """Entry id=92 has 'OFAC' and 'replacement' in admin messages → deposit_demand=True."""
        ctx = _make_ctx(tmp_path)
        ingest_team_archive(FIXTURE_DIR, ctx)

        campaigns = ctx.campaign_store.list_campaigns(limit=10)
        sessions = ctx.chat_session_store.list_by_campaign(campaigns[0]["campaign_id"], limit=100)
        matching = self._get_sessions_by_record_suffix(sessions, "#92")
        assert len(matching) == 1, "Entry 92 must produce exactly one chat session"
        assert matching[0].get("deposit_demand") is True

    def test_entry_446_deposit_demand_false(self, tmp_path: Path) -> None:
        """Entry id=446 has no fraud keywords in admin messages → deposit_demand=False."""
        ctx = _make_ctx(tmp_path)
        ingest_team_archive(FIXTURE_DIR, ctx)

        campaigns = ctx.campaign_store.list_campaigns(limit=10)
        sessions = ctx.chat_session_store.list_by_campaign(campaigns[0]["campaign_id"], limit=100)
        matching = self._get_sessions_by_record_suffix(sessions, "#446")
        assert len(matching) == 1, "Entry 446 must produce exactly one chat session"
        assert matching[0].get("deposit_demand") is False


class TestTrustWalletPanelInfrastructureDetails:
    """Infrastructure profile field values must match iocs.json fixture."""

    def test_panel_url_and_source_maps_exposed(self, tmp_path: Path) -> None:
        """panel_url=tttadmin.com, source_maps_exposed=True (fixture iocs.json)."""
        ctx = _make_ctx(tmp_path)
        ingest_team_archive(FIXTURE_DIR, ctx)

        campaigns = ctx.campaign_store.list_campaigns(limit=10)
        campaign_id = campaigns[0]["campaign_id"]
        profiles = ctx.infrastructure_profile_store.get_by_campaign(campaign_id)

        assert len(profiles) == 1
        profile = profiles[0]
        assert profile["primary_domain"] == "tttadmin.com"
        assert profile["source_maps_exposed"] is True


class TestTrustWalletPanelReportFile:
    """Report file written by the runner must match the contract."""

    def test_report_file_written_with_correct_counts(self, tmp_path: Path) -> None:
        """Report JSON must exist and contain the golden counts."""
        ctx = _make_ctx(tmp_path)
        report_dir = tmp_path / "reports"

        summary = ingest_team_archive(FIXTURE_DIR, ctx, report_dir=report_dir)

        assert summary.status == "ok"
        report_path = report_dir / "TrustWalletPanel.json"
        assert report_path.exists(), "Runner must write TrustWalletPanel.json"

        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["status"] == "ok"
        assert report["counts"]["chat_sessions_inserted"] == 3
        assert report["counts"]["infrastructure_profiles_inserted"] == 1
        assert report["commit_sha"] == _PINNED_SHA
