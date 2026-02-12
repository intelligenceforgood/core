"""Tests for i4g.cli.bootstrap.bundle_manifest — file hashing and manifest building."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from i4g.cli.bootstrap.bundle_manifest import (
    FileRecord,
    ManifestResult,
    build_manifest,
    count_lines,
    file_sha256,
    summarize_file,
)


class TestFileSha256:
    def test_known_content(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"hello world")
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert file_sha256(f) == expected

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        expected = hashlib.sha256(b"").hexdigest()
        assert file_sha256(f) == expected


class TestCountLines:
    def test_three_lines(self, tmp_path):
        f = tmp_path / "lines.txt"
        f.write_text("line1\nline2\nline3\n")
        assert count_lines(f) == 3

    def test_single_line_no_newline(self, tmp_path):
        f = tmp_path / "single.txt"
        f.write_text("one line")
        assert count_lines(f) == 1

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        assert count_lines(f) == 0


class TestSummarizeFile:
    def test_json_file_has_line_count(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text('{"a": 1}\n{"b": 2}\n')
        record = summarize_file(f, tmp_path)
        assert record.path == "data.json"
        assert record.line_count == 2
        assert record.size_bytes > 0
        assert len(record.sha256) == 64

    def test_binary_file_no_line_count(self, tmp_path):
        f = tmp_path / "image.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        record = summarize_file(f, tmp_path)
        assert record.line_count is None

    def test_nested_path(self, tmp_path):
        sub = tmp_path / "sub" / "dir"
        sub.mkdir(parents=True)
        f = sub / "nested.yaml"
        f.write_text("key: value\n")
        record = summarize_file(f, tmp_path)
        assert record.path == "sub/dir/nested.yaml"


class TestBuildManifest:
    def test_basic_manifest(self, tmp_path):
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        (bundle_dir / "cases.jsonl").write_text('{"case_id": "c1"}\n')
        (bundle_dir / "readme.txt").write_text("Sample bundle\n")

        output = tmp_path / "manifest.json"
        result = build_manifest(
            bundle_dir=bundle_dir,
            bundle_id="test-bundle-001",
            provenance="unit test",
            license_name="MIT",
            tags=["test", "synthetic"],
            pii=False,
            output_path=output,
        )

        assert isinstance(result, ManifestResult)
        assert output.exists()
        manifest = json.loads(output.read_text())

        assert manifest["bundle_id"] == "test-bundle-001"
        assert manifest["provenance"] == "unit test"
        assert manifest["license"] == "MIT"
        assert manifest["pii"] is False
        assert manifest["tags"] == ["test", "synthetic"]
        assert manifest["totals"]["files"] == 2
        assert manifest["totals"]["bytes"] > 0

    def test_manifest_excludes_itself(self, tmp_path):
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        (bundle_dir / "data.json").write_text("{}\n")
        output = bundle_dir / "manifest.json"

        result = build_manifest(
            bundle_dir=bundle_dir,
            bundle_id="self-test",
            provenance=None,
            license_name=None,
            tags=[],
            pii=True,
            output_path=output,
        )

        file_paths = [f["path"] for f in result.manifest["files"]]
        assert "manifest.json" not in file_paths

    def test_empty_bundle(self, tmp_path):
        bundle_dir = tmp_path / "empty"
        bundle_dir.mkdir()
        output = tmp_path / "manifest.json"

        result = build_manifest(
            bundle_dir=bundle_dir,
            bundle_id="empty",
            provenance=None,
            license_name=None,
            tags=[],
            pii=False,
            output_path=output,
        )

        assert result.manifest["totals"]["files"] == 0
        assert result.manifest["totals"]["bytes"] == 0
