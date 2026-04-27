"""PhishDestroy ScamIntelLogs archive ingestion package (Sprint 2 §2.3)."""

from __future__ import annotations

from i4g.ingestion.phishdestroy.archive.base import ArchiveContext, TeamAdapter
from i4g.ingestion.phishdestroy.archive.detector import TeamFormat, UnknownFormatError, detect_team_format
from i4g.ingestion.phishdestroy.archive.evidence import (
    BlobKind,
    EvidenceBlobRef,
    persist_chat_export,
    persist_team_blobs,
    predict_storage_uri,
)
from i4g.ingestion.phishdestroy.archive.runner import IngestArchiveSummary, ingest_team_archive
from i4g.ingestion.phishdestroy.archive.trustwalletpanel import TrustWalletPanelAdapter

# Default registry exposed for use by the worker and CLI.
ARCHIVE_ADAPTER_REGISTRY: dict[str, type[TeamAdapter]] = {
    TrustWalletPanelAdapter.team_name: TrustWalletPanelAdapter,
}

__all__ = [
    "ArchiveContext",
    "ARCHIVE_ADAPTER_REGISTRY",
    "IngestArchiveSummary",
    "TeamAdapter",
    "TeamFormat",
    "TrustWalletPanelAdapter",
    "UnknownFormatError",
    "detect_team_format",
    "ingest_team_archive",
    "BlobKind",
    "EvidenceBlobRef",
    "persist_chat_export",
    "persist_team_blobs",
    "predict_storage_uri",
]
