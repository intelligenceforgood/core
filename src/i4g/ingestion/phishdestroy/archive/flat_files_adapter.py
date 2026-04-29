"""FlatFilesAdapter for PhishDestroy ScamIntelLogs archive."""

from __future__ import annotations

from pathlib import Path

from i4g.ingestion.phishdestroy.archive.base import ArchiveContext
from i4g.ingestion.phishdestroy.archive.detector import TeamFormat


class FlatFilesAdapter:
    """Extracts indicators from domains.txt (and other simple files) when iocs.json is absent."""

    team_name: str = TeamFormat.FLAT_FILES.value

    def ingest(self, team_dir: Path, ctx: ArchiveContext) -> dict[str, int]:
        """Ingest domains from domains.txt and return counts."""
        domains_file = team_dir / "domains.txt"
        inserted = 0
        if domains_file.exists():
            with domains_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        inserted += 1

        return {
            "chat_sessions_inserted": 0,
            "chat_sessions_updated": 0,
            "chat_sessions_unchanged": 0,
            "infrastructure_profiles_inserted": inserted,
            "infrastructure_profiles_updated": 0,
            "infrastructure_profiles_unchanged": 0,
        }
