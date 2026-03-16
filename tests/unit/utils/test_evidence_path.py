"""Unit tests for evidence path sharding utility."""

from __future__ import annotations

from i4g.utils.evidence_path import evidence_path


class TestEvidencePath:
    """Test evidence_path() sharding logic."""

    def test_standard_uuid(self) -> None:
        scan_id = "fd70a83f-91de-4533-9506-ebe3916dbff9"
        result = evidence_path(scan_id)
        assert result == "scans/fd/70/fd70a83f-91de-4533-9506-ebe3916dbff9"

    def test_path_components_are_lowercase_hex(self) -> None:
        scan_id = "AB12CD34-5678-9ABC-DEF0-1234567890AB"
        result = evidence_path(scan_id)
        prefix1 = result.split("/")[1]
        prefix2 = result.split("/")[2]
        assert prefix1 == "ab"
        assert prefix2 == "12"

    def test_ends_with_original_scan_id(self) -> None:
        scan_id = "fd70a83f-91de-4533-9506-ebe3916dbff9"
        result = evidence_path(scan_id)
        assert result.endswith(scan_id)

    def test_starts_with_scans_prefix(self) -> None:
        scan_id = "00000000-0000-0000-0000-000000000000"
        result = evidence_path(scan_id)
        assert result.startswith("scans/")
        assert result == "scans/00/00/00000000-0000-0000-0000-000000000000"

    def test_different_uuids_produce_different_shards(self) -> None:
        path_a = evidence_path("abcdef01-0000-0000-0000-000000000000")
        path_b = evidence_path("12345678-0000-0000-0000-000000000000")
        # Different first 4 hex chars → different shard directories
        assert path_a.split("/")[1:3] != path_b.split("/")[1:3]
