"""Tests for the PhishDestroy archive format detector."""

from __future__ import annotations

import json
from pathlib import Path

from i4g.ingestion.phishdestroy.archive.detector import TeamFormat, detect_team_format


class TestDetectTeamFormat:
    """Unit tests for detect_team_format()."""

    def test_valid_iocs_json_returns_scamintellogs_v1(self, tmp_path: Path) -> None:
        """iocs.json present with 'team' key → SCAMINTELLOGS_V1."""
        team_dir = tmp_path / "SomeTeam"
        team_dir.mkdir()
        (team_dir / "iocs.json").write_text(
            json.dumps({"team": "SomeTeam", "panel_url": "example.com"}),
            encoding="utf-8",
        )
        assert detect_team_format(team_dir) == TeamFormat.SCAMINTELLOGS_V1

    def test_missing_iocs_json_returns_unknown(self, tmp_path: Path) -> None:
        """Directory with no iocs.json → UNKNOWN."""
        team_dir = tmp_path / "NoIocs"
        team_dir.mkdir()
        assert detect_team_format(team_dir) == TeamFormat.UNKNOWN

    def test_unparseable_iocs_json_returns_unknown(self, tmp_path: Path) -> None:
        """iocs.json that is not valid JSON → UNKNOWN."""
        team_dir = tmp_path / "BadJson"
        team_dir.mkdir()
        (team_dir / "iocs.json").write_text("this is not json {{ }", encoding="utf-8")
        assert detect_team_format(team_dir) == TeamFormat.UNKNOWN

    def test_iocs_json_missing_team_key_returns_unknown(self, tmp_path: Path) -> None:
        """Valid JSON but no top-level 'team' key → UNKNOWN."""
        team_dir = tmp_path / "NoTeamKey"
        team_dir.mkdir()
        (team_dir / "iocs.json").write_text(
            json.dumps({"panel_url": "example.com"}),
            encoding="utf-8",
        )
        assert detect_team_format(team_dir) == TeamFormat.UNKNOWN
