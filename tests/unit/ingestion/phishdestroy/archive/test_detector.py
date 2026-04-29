"""Tests for detector.py."""

from pathlib import Path

from i4g.ingestion.phishdestroy.archive.detector import TeamFormat, detect_team_format


def test_detect_team_format_scamintellogs_v1(tmp_path: Path) -> None:
    """Test format detection for v1."""
    team_dir = tmp_path / "team1"
    team_dir.mkdir()
    iocs_file = team_dir / "iocs.json"
    iocs_file.write_text('{"team": "team1"}')
    assert detect_team_format(team_dir) == TeamFormat.SCAMINTELLOGS_V1


def test_detect_team_format_flat_files_domains(tmp_path: Path) -> None:
    """Test format detection for flat files domains."""
    team_dir = tmp_path / "team2"
    team_dir.mkdir()
    (team_dir / "domains.txt").write_text("example.com")
    assert detect_team_format(team_dir) == TeamFormat.FLAT_FILES


def test_detect_team_format_flat_files_chat(tmp_path: Path) -> None:
    """Test format detection for flat files chat."""
    team_dir = tmp_path / "team3"
    team_dir.mkdir()
    (team_dir / "chat").mkdir()
    assert detect_team_format(team_dir) == TeamFormat.FLAT_FILES


def test_detect_team_format_unknown(tmp_path: Path) -> None:
    """Test format detection for unknown."""
    team_dir = tmp_path / "team4"
    team_dir.mkdir()
    assert detect_team_format(team_dir) == TeamFormat.UNKNOWN
