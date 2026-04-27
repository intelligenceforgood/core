"""Dossier-signing round-trip test for the Phase C evidence-blob pipeline (Sprint 2 §2.4).

Demonstrates that every blob persisted by the TrustWalletPanel adapter is hashable by
``generate_signature_manifest`` and that the recorded SHA-256 round-trips against the
on-disk artifact. This is the §2.4 "verify dossier signing picks up new evidence types"
contract gate.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from i4g.ingestion.phishdestroy.archive.base import ArchiveContext
from i4g.ingestion.phishdestroy.archive.runner import ingest_team_archive
from i4g.reports.dossier_signatures import generate_signature_manifest
from i4g.storage.evidence import EvidenceStorage
from i4g.store.brand_impersonation_store import BrandImpersonationStore
from i4g.store.chat_session_store import ChatSessionStore
from i4g.store.financial_damage_store import FinancialDamageStore
from i4g.store.infrastructure_profile_store import InfrastructureProfileStore
from i4g.store.threat_campaign_store import ThreatCampaignStore

FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "phishdestroy" / "trustwalletpanel"

_PINNED_SHA = "83d0307420fcc865fcb8a34b8c454acbc6d56f1f"
_NOW = datetime(2026, 4, 27, 15, 30, 0, tzinfo=UTC)


def _normalise(raw):
    if isinstance(raw, str):
        return json.loads(raw)
    return raw or {}


def test_dossier_signing_round_trip(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    storage = EvidenceStorage(local_dir=tmp_path / "evidence")
    ctx = ArchiveContext(
        commit_sha=_PINNED_SHA,
        ingest_job="test-ingest-archive",
        ingest_job_run_id=None,
        now=_NOW,
        campaign_store=ThreatCampaignStore(db_path=str(db)),
        chat_session_store=ChatSessionStore(db_path=str(db)),
        infrastructure_profile_store=InfrastructureProfileStore(db_path=str(db)),
        financial_damage_store=FinancialDamageStore(db_path=str(db)),
        brand_impersonation_store=BrandImpersonationStore(db_path=str(db)),
        evidence_storage=storage,
    )

    ingest_team_archive(FIXTURE_DIR, ctx)

    campaigns = ctx.campaign_store.list_campaigns(limit=10)
    sessions = ctx.chat_session_store.list_by_campaign(campaigns[0]["campaign_id"], limit=100)
    profiles = ctx.infrastructure_profile_store.get_by_campaign(campaigns[0]["campaign_id"])
    assert sessions and profiles

    chat_sha = sessions[0]["evidence_blob_sha256"]
    assert chat_sha is not None

    # Build (label, Path) entries from the persisted blobs.
    entries: list[tuple[str, Path]] = []
    expected_shas: dict[str, str] = {}

    chat_export_path = tmp_path / "evidence" / "phishdestroy-archive" / "TrustWalletPanel" / "chats_translated.json"
    assert chat_export_path.is_file()
    chat_label = "chat_export:chats_translated.json"
    entries.append((chat_label, chat_export_path))
    expected_shas[chat_label] = chat_sha

    infra_blobs = _normalise(profiles[0]["metadata_json"])["evidence_blobs"]
    for blob in infra_blobs:
        path = Path(blob["storage_uri"])
        assert path.is_file(), f"Persisted blob missing on disk: {path}"
        label = f"{blob['kind']}:{blob['file_name']}"
        entries.append((label, path))
        expected_shas[label] = blob["sha256"]

    manifest = generate_signature_manifest(entries, algorithm="sha256")

    assert list(manifest.warnings) == [], "Every persisted blob must be hashable on disk"
    assert len(manifest.artifacts) == len(entries)

    for artifact in manifest.artifacts:
        assert artifact.hash_value == expected_shas[artifact.label], (
            f"Hash mismatch for {artifact.label}: manifest={artifact.hash_value} "
            f"recorded={expected_shas[artifact.label]}"
        )
