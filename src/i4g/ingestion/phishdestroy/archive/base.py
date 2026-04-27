"""Shared base types and helpers for PhishDestroy archive adapters.

All adapters receive an ``ArchiveContext`` and return a ``counts`` dict.
Provenance builders live here so every adapter uses the same structure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from i4g.storage.evidence import EvidenceStorage
from i4g.store.brand_impersonation_store import BrandImpersonationStore
from i4g.store.chat_session_store import ChatSessionStore
from i4g.store.financial_damage_store import FinancialDamageStore
from i4g.store.infrastructure_profile_store import InfrastructureProfileStore
from i4g.store.threat_campaign_store import ThreatCampaignStore


@dataclass
class ArchiveContext:
    """Runtime dependencies injected into every team adapter."""

    commit_sha: str
    """Pinned ScamIntelLogs SHA from settings (provenance §4)."""

    ingest_job: str
    """Job identifier string, e.g. ``"i4g-jobs-ingest-archive"``."""

    ingest_job_run_id: str | None
    """Cloud Run execution ID, or None when running locally."""

    now: datetime
    """UTC timestamp for this ingestion run."""

    campaign_store: ThreatCampaignStore
    chat_session_store: ChatSessionStore
    infrastructure_profile_store: InfrastructureProfileStore
    financial_damage_store: FinancialDamageStore
    brand_impersonation_store: BrandImpersonationStore

    evidence_storage: EvidenceStorage | None = None
    """Phase C evidence-blob backend, or ``None`` to preserve Phase B behaviour."""


def build_chat_provenance(
    team: str,
    record_id: str,
    ctx: ArchiveContext,
) -> dict[str, Any]:
    """Return a source_provenance dict for a chat session row.

    Args:
        team: Team directory name (e.g. ``"TrustWalletPanel"``).
        record_id: Per-provenance §2: ``<team>/<filename>#<message_index>``.
        ctx: Shared ingestion context.

    Returns:
        Provenance dict ready to be stored in ``source_provenance``.
    """
    prov: dict[str, Any] = {
        "source": "phishdestroy.archive.chat",
        "team": team,
        "commit_sha": ctx.commit_sha,
        "record_id": record_id,
        "ingested_at": ctx.now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ingest_job": ctx.ingest_job,
    }
    if ctx.ingest_job_run_id is not None:
        prov["ingest_job_run_id"] = ctx.ingest_job_run_id
    return prov


def build_infra_provenance(
    team: str,
    record_id: str,
    ctx: ArchiveContext,
) -> dict[str, Any]:
    """Return a source_provenance dict for an infrastructure profile row.

    Args:
        team: Team directory name (e.g. ``"TrustWalletPanel"``).
        record_id: Per-provenance §2: ``<team>/iocs.json#<jsonpointer>``.
        ctx: Shared ingestion context.

    Returns:
        Provenance dict ready to be stored in ``source_provenance``.
    """
    prov: dict[str, Any] = {
        "source": "phishdestroy.archive.infrastructure",
        "team": team,
        "commit_sha": ctx.commit_sha,
        "record_id": record_id,
        "ingested_at": ctx.now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ingest_job": ctx.ingest_job,
    }
    if ctx.ingest_job_run_id is not None:
        prov["ingest_job_run_id"] = ctx.ingest_job_run_id
    return prov


@runtime_checkable
class TeamAdapter(Protocol):
    """Protocol that every concrete team adapter must satisfy."""

    team_name: str
    """The team directory name this adapter handles, e.g. ``"TrustWalletPanel"``."""

    def ingest(self, team_dir: Path, ctx: ArchiveContext) -> dict[str, dict[str, int]]:  # noqa: F821
        """Ingest one team directory and return per-table count dicts.

        Args:
            team_dir: Absolute path to the team directory.
            ctx: Shared archive ingestion context.

        Returns:
            A ``counts`` dict matching the parse-failure report schema, e.g.::

                {
                    "chat_sessions_inserted": 3,
                    "chat_sessions_updated": 0,
                    "chat_sessions_unchanged": 0,
                    "infrastructure_profiles_inserted": 1,
                    "infrastructure_profiles_updated": 0,
                    "infrastructure_profiles_unchanged": 0,
                }
        """
        ...
