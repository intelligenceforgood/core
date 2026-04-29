"""PhishDestroy ScamIntelLogs archive ingestion package (Sprint 2 §2.3)."""

from __future__ import annotations

from i4g.ingestion.phishdestroy.archive.base import (
    ArchiveContext,
    TeamAdapter,
    build_financial_damage_provenance,
)
from i4g.ingestion.phishdestroy.archive.brands import lookup_indicators_for_domain
from i4g.ingestion.phishdestroy.archive.damage import DamageRecord, parse_deposit_messages
from i4g.ingestion.phishdestroy.archive.detector import TeamFormat, UnknownFormatError, detect_team_format
from i4g.ingestion.phishdestroy.archive.evidence import (
    BlobKind,
    EvidenceBlobRef,
    persist_chat_export,
    persist_team_blobs,
    predict_storage_uri,
)
from i4g.ingestion.phishdestroy.archive.flat_files_adapter import FlatFilesAdapter
from i4g.ingestion.phishdestroy.archive.runner import IngestArchiveSummary, ingest_team_archive
from i4g.ingestion.phishdestroy.archive.team_config import (
    DEFAULT_TEAM_BLOB_CONFIG,
    TEAM_CONFIG_REGISTRY,
    TeamBlobConfig,
    TeamConfig,
    get_team_config,
)
from i4g.ingestion.phishdestroy.archive.trustwalletpanel import TrustWalletPanelAdapter

# Default registry exposed for use by the worker and CLI.
ARCHIVE_ADAPTER_REGISTRY: dict[str, type[TeamAdapter]] = {
    TrustWalletPanelAdapter.team_name: TrustWalletPanelAdapter,
    "SyntheticThefts": TrustWalletPanelAdapter,
    TeamFormat.FLAT_FILES: FlatFilesAdapter,
}

__all__ = [
    "ArchiveContext",
    "ARCHIVE_ADAPTER_REGISTRY",
    "IngestArchiveSummary",
    "TeamAdapter",
    "TeamFormat",
    "TrustWalletPanelAdapter",
    "FlatFilesAdapter",
    "UnknownFormatError",
    "build_financial_damage_provenance",
    "detect_team_format",
    "ingest_team_archive",
    "BlobKind",
    "EvidenceBlobRef",
    "persist_chat_export",
    "persist_team_blobs",
    "predict_storage_uri",
    "TeamBlobConfig",
    "TeamConfig",
    "DEFAULT_TEAM_BLOB_CONFIG",
    "TEAM_CONFIG_REGISTRY",
    "get_team_config",
    "DamageRecord",
    "parse_deposit_messages",
    "lookup_indicators_for_domain",
]
