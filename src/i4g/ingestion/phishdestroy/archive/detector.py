"""Format detector for PhishDestroy ScamIntelLogs team directories.

Inspects a team directory and returns a TeamFormat enum value.
The detector MUST NOT guess — if iocs.json is missing or unparseable,
it returns TeamFormat.UNKNOWN rather than attempting heuristic detection.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path


class TeamFormat(StrEnum):
    """Recognized format variants for PhishDestroy ScamIntelLogs team directories."""

    SCAMINTELLOGS_V1 = "scamintellogs_v1"
    """iocs.json present at directory root, parses as valid JSON with a top-level 'team' key."""

    FLAT_FILES = "flat_files"
    """iocs.json is missing, but domains.txt or scammers_login.txt or chat/ is present."""

    UNKNOWN = "unknown"
    """iocs.json is missing, unparseable, or lacks the required 'team' key."""


class UnknownFormatError(Exception):
    """Raised when a team directory cannot be classified into a known format.

    Attributes:
        team_dir: The path that was inspected.
    """

    def __init__(self, team_dir: Path) -> None:
        self.team_dir = team_dir
        super().__init__(f"Unknown format for team directory: {team_dir}")


def detect_team_format(team_dir: Path) -> TeamFormat:
    """Inspect *team_dir* and return the detected TeamFormat.

    Reads only ``iocs.json`` at the directory root.  Does not open any other
    files and does not raise on missing / unparseable JSON — callers that need
    an exception should check for ``TeamFormat.UNKNOWN`` and raise
    ``UnknownFormatError`` themselves (the runner does this automatically).

    Args:
        team_dir: Path to a single team directory, e.g.
            ``/path/to/ScamIntelLogs/TrustWalletPanel``.

    Returns:
        ``TeamFormat.SCAMINTELLOGS_V1`` when ``iocs.json`` is present, parses
        as valid JSON, and contains a top-level ``"team"`` key.
        ``TeamFormat.UNKNOWN`` otherwise.
    """
    iocs_path = team_dir / "iocs.json"
    if not iocs_path.exists():
        if (
            (team_dir / "domains.txt").exists()
            or (team_dir / "scammers_login.txt").exists()
            or (team_dir / "chat").is_dir()
        ):
            return TeamFormat.FLAT_FILES
        return TeamFormat.UNKNOWN

    try:
        with iocs_path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return TeamFormat.UNKNOWN

    if not isinstance(data, dict) or "team" not in data:
        return TeamFormat.UNKNOWN

    return TeamFormat.SCAMINTELLOGS_V1
