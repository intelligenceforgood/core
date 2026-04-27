"""Unit tests for ``i4g.ingestion.phishdestroy.archive.evidence`` (Sprint 2 §2.4 / Phase C)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from i4g.ingestion.phishdestroy.archive.evidence import (
    BlobKind,
    EvidenceBlobRef,
    persist_chat_export,
    persist_team_blobs,
)
from i4g.storage.evidence import EvidenceStorage

_TEAM = "TrustWalletPanel"


def _make_storage(tmp_path: Path) -> EvidenceStorage:
    return EvidenceStorage(local_dir=tmp_path / "evidence")


class TestPersistChatExport:
    def test_returns_sha_and_uri_and_round_trips(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path)
        export = tmp_path / "chats_translated.json"
        payload = b'[{"id": 1, "messages": []}]'
        export.write_bytes(payload)

        result = persist_chat_export(storage, _TEAM, export)

        assert result is not None
        sha, uri = result
        assert sha == hashlib.sha256(payload).hexdigest()
        retrieved = storage.retrieve(uri)
        assert retrieved is not None
        assert retrieved.data == payload
        assert retrieved.checksum_sha256 == sha

    def test_idempotent_when_called_twice(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path)
        export = tmp_path / "chats_translated.json"
        export.write_bytes(b'[{"id": 1}]')

        first = persist_chat_export(storage, _TEAM, export)
        second = persist_chat_export(storage, _TEAM, export)

        assert first == second
        # Exactly one on-disk file under the per-team intake directory.
        intake_dir = tmp_path / "evidence" / "phishdestroy-archive" / _TEAM
        files = sorted(p.name for p in intake_dir.iterdir() if p.is_file())
        assert files == ["chats_translated.json"]

    def test_returns_none_when_storage_is_none(self, tmp_path: Path) -> None:
        export = tmp_path / "chats_translated.json"
        export.write_bytes(b"[]")
        assert persist_chat_export(None, _TEAM, export) is None


class TestPersistTeamBlobs:
    def _write(self, dir_path: Path, name: str, content: bytes = b"x") -> Path:
        p = dir_path / name
        p.write_bytes(content)
        return p

    def test_detects_photos_panels_and_source_maps(self, tmp_path: Path) -> None:
        team_dir = tmp_path / "team"
        team_dir.mkdir()
        # Uppercase suffix to verify case-insensitive matching.
        self._write(team_dir, "TrustWalletPanel.PNG", b"\x89PNG_stub")
        self._write(team_dir, "chats.html", b"<html></html>")
        self._write(team_dir, "notes.txt", b"unrelated")
        self._write(team_dir, "bundle.js.MAP", b"{}")

        storage = _make_storage(tmp_path)
        refs = persist_team_blobs(storage, _TEAM, team_dir)

        names = [r.file_name for r in refs]
        assert "notes.txt" not in names
        assert len(refs) == 3
        kinds = [r.kind for r in refs]
        assert kinds == sorted(kinds, key=lambda k: k.value)
        # Deterministic sort: (kind, file_name)
        assert refs == sorted(refs, key=lambda r: (r.kind.value, r.file_name))

    def test_skips_chats_translated_json(self, tmp_path: Path) -> None:
        team_dir = tmp_path / "team"
        team_dir.mkdir()
        self._write(team_dir, "chats_translated.json", b"[]")

        storage = _make_storage(tmp_path)
        refs = persist_team_blobs(storage, _TEAM, team_dir)

        assert refs == []

    def test_returns_empty_when_storage_is_none(self, tmp_path: Path) -> None:
        team_dir = tmp_path / "team"
        team_dir.mkdir()
        self._write(team_dir, "x.png", b"\x89PNG")
        assert persist_team_blobs(None, _TEAM, team_dir) == []


class TestEvidenceBlobRefMetadataDict:
    def test_shape_matches_contract(self) -> None:
        ref = EvidenceBlobRef(
            kind=BlobKind.PHOTO,
            file_name="x.png",
            sha256="deadbeef",
            size_bytes=42,
            storage_uri="/tmp/x.png",
            content_type="image/png",
        )
        assert ref.to_metadata_dict() == {
            "kind": "photo",
            "file_name": "x.png",
            "sha256": "deadbeef",
            "size_bytes": 42,
            "storage_uri": "/tmp/x.png",
            "content_type": "image/png",
        }
        assert list(ref.to_metadata_dict().keys()) == [
            "kind",
            "file_name",
            "sha256",
            "size_bytes",
            "storage_uri",
            "content_type",
        ]
