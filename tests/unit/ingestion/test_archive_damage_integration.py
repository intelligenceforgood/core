"""End-to-end integration test for financial damage ingestion (Sprint 2 Phase D).

Defines an inline ``SyntheticTheftsAdapter`` that exercises:
  - ``parse_deposit_messages`` (damage parser)
  - ``FinancialDamageStore.upsert_by_provenance`` (store write)
  - Idempotency: second run yields unchanged counts, not re-inserts

Uses the synthetic fixture at ``tests/fixtures/phishdestroy/synthetic_thefts/``.
``SyntheticTheftsAdapter`` is NOT registered in the production ``ARCHIVE_ADAPTER_REGISTRY``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from i4g.ingestion.phishdestroy.archive.base import ArchiveContext, build_financial_damage_provenance
from i4g.ingestion.phishdestroy.archive.damage import parse_deposit_messages
from i4g.ingestion.phishdestroy.archive.runner import ingest_team_archive
from i4g.store.brand_impersonation_store import BrandImpersonationStore
from i4g.store.chat_session_store import ChatSessionStore
from i4g.store.financial_damage_store import FinancialDamageStore
from i4g.store.infrastructure_profile_store import InfrastructureProfileStore
from i4g.store.threat_campaign_store import ThreatCampaignStore

FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "phishdestroy" / "synthetic_thefts"
_PINNED_SHA = "0000000000000000000000000000000000000000"
_INGEST_JOB = "test-integration-damage"
_NOW = datetime(2026, 4, 27, 16, 30, 0, tzinfo=UTC)

_DAMAGE_SOURCE = "phishdestroy.archive.financial_damage"


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


_SYNTHETIC_TEAM = "SyntheticThefts"


class SyntheticTheftsAdapter:
    """Minimal inline adapter for integration tests — NOT in production registry."""

    team_name = _SYNTHETIC_TEAM

    def ingest(self, team_dir: Path, ctx: ArchiveContext) -> dict[str, int]:
        """Ingest only the successful_thefts/result.json for damage claim testing."""
        # Create campaign keyed on phishdestroy_team metadata.
        all_campaigns = ctx.campaign_store.list_campaigns(limit=500)
        campaign_id: str | None = None
        for camp in all_campaigns:
            meta = camp.get("metadata") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except json.JSONDecodeError:
                    meta = {}
            if meta.get("phishdestroy_team") == _SYNTHETIC_TEAM:
                campaign_id = camp["campaign_id"]
                break
        if campaign_id is None:
            campaign_id = ctx.campaign_store.create_campaign(
                name=_SYNTHETIC_TEAM,
                origin="phishdestroy.archive",
                status="emerging",
                metadata={"phishdestroy_team": _SYNTHETIC_TEAM},
            )

        result_path = team_dir / "successful_thefts" / "result.json"
        if not result_path.exists():
            return {
                "chat_sessions_inserted": 0,
                "chat_sessions_updated": 0,
                "chat_sessions_unchanged": 0,
                "infrastructure_profiles_inserted": 0,
                "infrastructure_profiles_updated": 0,
                "infrastructure_profiles_unchanged": 0,
                "financial_damage_claims_inserted": 0,
                "financial_damage_claims_updated": 0,
                "financial_damage_claims_unchanged": 0,
                "financial_damage_claims_skipped": 0,
                "brand_impersonations_inserted": 0,
                "brand_impersonations_updated": 0,
                "brand_impersonations_skipped": 0,
            }

        with result_path.open(encoding="utf-8") as fh:
            raw = json.load(fh)

        messages = raw.get("messages", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
        records, skipped = parse_deposit_messages(messages)

        # Pre-query existing record IDs for idempotency tracking.
        existing_claims = ctx.financial_damage_store.list_by_campaign(campaign_id, limit=10000)
        existing_record_ids: set[str] = set()
        for claim in existing_claims:
            prov = claim.get("source_provenance")
            if isinstance(prov, str):
                try:
                    prov = json.loads(prov)
                except json.JSONDecodeError:
                    prov = {}
            if isinstance(prov, dict) and prov.get("source") == _DAMAGE_SOURCE:
                rid = prov.get("record_id")
                if rid:
                    existing_record_ids.add(rid)

        inserted = 0
        updated = 0
        unchanged = 0

        for record in records:
            record_id = f"{_SYNTHETIC_TEAM}/successful_thefts/result.json#{record.message_id}"
            provenance = build_financial_damage_provenance(team=_SYNTHETIC_TEAM, record_id=record_id, ctx=ctx)
            metadata: dict[str, Any] = {"raw_text": record.raw_text}
            if record.project is not None:
                metadata["project"] = record.project
            if record.amount_usd_credited is not None:
                metadata["amount_usd_credited"] = str(record.amount_usd_credited)
            if record.operator_share_percent is not None:
                metadata["operator_share_percent"] = str(record.operator_share_percent)

            ctx.financial_damage_store.upsert_by_provenance(
                source_provenance=provenance,
                currency="USD",
                amount_claimed=record.amount_usd_claimed,
                campaign_id=campaign_id,
                chain=record.chain,
                metadata_json=metadata,
            )

            if record_id in existing_record_ids:
                unchanged += 1
            else:
                inserted += 1

        return {
            "chat_sessions_inserted": 0,
            "chat_sessions_updated": 0,
            "chat_sessions_unchanged": 0,
            "infrastructure_profiles_inserted": 0,
            "infrastructure_profiles_updated": 0,
            "infrastructure_profiles_unchanged": 0,
            "financial_damage_claims_inserted": inserted,
            "financial_damage_claims_updated": updated,
            "financial_damage_claims_unchanged": unchanged,
            "financial_damage_claims_skipped": skipped,
            "brand_impersonations_inserted": 0,
            "brand_impersonations_updated": 0,
            "brand_impersonations_skipped": 0,
        }


def _campaign_meta(c: dict) -> dict:
    """Return parsed metadata dict from a campaign row (handles JSON string or dict)."""
    meta = c.get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except json.JSONDecodeError:
            meta = {}
    return meta


_SYNTHETIC_REGISTRY: dict[str, type] = {_SYNTHETIC_TEAM: SyntheticTheftsAdapter}


class TestSyntheticTheftsDamageIntegration:
    """End-to-end tests using the synthetic fixture + SyntheticTheftsAdapter."""

    def test_first_run_inserts_three_damage_claims(self, tmp_path: Path) -> None:
        """Fixture has 3 parseable deposit messages → 3 inserted on first run."""
        ctx = _make_ctx(tmp_path)
        summary = ingest_team_archive(FIXTURE_DIR, ctx, registry=_SYNTHETIC_REGISTRY)

        assert summary.status == "ok"
        assert summary.counts["financial_damage_claims_inserted"] == 3
        assert summary.counts["financial_damage_claims_unchanged"] == 0
        # 1 service message + 1 no-header message = 2 skipped
        assert summary.counts["financial_damage_claims_skipped"] == 2

    def test_second_run_idempotent(self, tmp_path: Path) -> None:
        """Second run with same fixture must not re-insert: all 3 go to unchanged."""
        ctx = _make_ctx(tmp_path)
        ingest_team_archive(FIXTURE_DIR, ctx, registry=_SYNTHETIC_REGISTRY)
        ctx2 = _make_ctx.__wrapped__(tmp_path) if hasattr(_make_ctx, "__wrapped__") else _make_ctx(tmp_path)
        # Reuse same DB: reinitialise context pointing at same db file.
        db = tmp_path / "test.db"
        ctx2 = ArchiveContext(
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
        summary2 = ingest_team_archive(FIXTURE_DIR, ctx2, registry=_SYNTHETIC_REGISTRY)

        assert summary2.status == "ok"
        assert summary2.counts["financial_damage_claims_inserted"] == 0
        assert summary2.counts["financial_damage_claims_unchanged"] == 3

    def test_damage_claims_stored_in_db(self, tmp_path: Path) -> None:
        """After first run, DB must contain exactly 3 financial_damage_claims rows."""
        ctx = _make_ctx(tmp_path)
        ingest_team_archive(FIXTURE_DIR, ctx, registry=_SYNTHETIC_REGISTRY)

        # Retrieve campaign_id via the campaign store.
        campaigns = ctx.campaign_store.list_campaigns(limit=500)
        camp = next(
            (c for c in campaigns if _campaign_meta(c).get("phishdestroy_team") == _SYNTHETIC_TEAM),
            None,
        )
        assert camp is not None, "Campaign not created"
        campaign_id = camp["campaign_id"]

        claims = ctx.financial_damage_store.list_by_campaign(campaign_id, limit=100)
        assert len(claims) == 3

    def test_amount_usd_values_correct(self, tmp_path: Path) -> None:
        """Parsed amounts from the fixture must match expected Decimal values."""

        ctx = _make_ctx(tmp_path)
        ingest_team_archive(FIXTURE_DIR, ctx, registry=_SYNTHETIC_REGISTRY)

        campaigns = ctx.campaign_store.list_campaigns(limit=500)
        camp = next(
            (c for c in campaigns if _campaign_meta(c).get("phishdestroy_team") == _SYNTHETIC_TEAM),
            None,
        )
        assert camp is not None
        claims = ctx.financial_damage_store.list_by_campaign(camp["campaign_id"], limit=100)
        amounts = sorted(float(c["amount_claimed"]) for c in claims)
        assert amounts == sorted([500.0, 1200.50, 750.0])
