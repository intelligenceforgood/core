"""Tests for entity extraction QA bundle management."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from i4g.extraction.quality.bundle import (
    Bundle,
    BundleCase,
    BundleLabel,
    create_bundle_from_files,
    create_bundle_from_golden_set,
    list_bundles,
    load_bundle,
    save_bundle,
)


@pytest.fixture()
def bundles_dir(tmp_path: Path) -> Path:
    """Create a temporary bundles directory."""
    return tmp_path / "bundles"


@pytest.fixture()
def sample_bundle() -> Bundle:
    """Create a sample bundle in memory."""
    return Bundle(
        name="test-bundle",
        description="A test bundle",
        created="2026-04-10T00:00:00+00:00",
        cases=[
            BundleCase(id="case_01", category="test", text="Send BTC to bc1qtest123"),
            BundleCase(id="case_02", category="test", text="Email: test@example.com"),
        ],
        labels={
            "case_01": BundleLabel(
                id="case_01",
                expected={"wallet_address": ["bc1qtest123"]},
            ),
            "case_02": BundleLabel(
                id="case_02",
                expected={"email_address": ["test@example.com"]},
            ),
        },
    )


class TestBundleSaveLoad:
    """Test saving and loading bundles."""

    def test_save_creates_directory_structure(self, sample_bundle: Bundle, bundles_dir: Path) -> None:
        path = save_bundle(sample_bundle, bundles_dir=bundles_dir)
        assert (path / "manifest.json").exists()
        assert (path / "cases" / "case_01.json").exists()
        assert (path / "cases" / "case_02.json").exists()
        assert (path / "labels" / "case_01.json").exists()
        assert (path / "labels" / "case_02.json").exists()

    def test_roundtrip(self, sample_bundle: Bundle, bundles_dir: Path) -> None:
        save_bundle(sample_bundle, bundles_dir=bundles_dir)
        loaded = load_bundle("test-bundle", bundles_dir=bundles_dir)
        assert loaded.name == sample_bundle.name
        assert loaded.description == sample_bundle.description
        assert len(loaded.cases) == 2
        assert loaded.cases[0].id == "case_01"
        assert loaded.cases[0].text == "Send BTC to bc1qtest123"
        assert loaded.has_labels
        assert loaded.labeled_count == 2
        assert "case_01" in loaded.labels
        assert loaded.labels["case_01"].expected == {"wallet_address": ["bc1qtest123"]}

    def test_load_nonexistent_raises(self, bundles_dir: Path) -> None:
        bundles_dir.mkdir(parents=True, exist_ok=True)
        with pytest.raises(FileNotFoundError):
            load_bundle("nonexistent", bundles_dir=bundles_dir)


class TestBundleListing:
    """Test bundle listing."""

    def test_list_empty(self, bundles_dir: Path) -> None:
        assert list_bundles(bundles_dir=bundles_dir) == []

    def test_list_with_bundles(self, sample_bundle: Bundle, bundles_dir: Path) -> None:
        save_bundle(sample_bundle, bundles_dir=bundles_dir)
        result = list_bundles(bundles_dir=bundles_dir)
        assert len(result) == 1
        assert result[0]["name"] == "test-bundle"
        assert result[0]["case_count"] == 2
        assert result[0]["label_count"] == 2


class TestBundleCreation:
    """Test bundle creation from various sources."""

    def test_create_from_golden_set(self, bundles_dir: Path, tmp_path: Path) -> None:
        golden_data = [
            {
                "id": "case_01",
                "category": "crypto",
                "text": "Send BTC to bc1qtest",
                "expected": {"wallet_address": ["bc1qtest"]},
            },
            {
                "id": "case_02",
                "category": "phishing",
                "text": "Visit https://evil.com",
                "expected": {"url": ["https://evil.com"]},
            },
        ]
        golden_path = tmp_path / "golden.json"
        golden_path.write_text(json.dumps(golden_data))

        bundle = create_bundle_from_golden_set(
            golden_path=golden_path,
            bundle_name="golden-test",
            bundles_dir=bundles_dir,
        )

        assert bundle.name == "golden-test"
        assert len(bundle.cases) == 2
        assert bundle.has_labels
        assert bundle.labels["case_01"].expected == {"wallet_address": ["bc1qtest"]}

    def test_create_from_files(self, bundles_dir: Path, tmp_path: Path) -> None:
        txt_dir = tmp_path / "texts"
        txt_dir.mkdir()
        (txt_dir / "sample1.txt").write_text("Hello world")
        (txt_dir / "sample2.txt").write_text("Test email test@example.com")

        bundle = create_bundle_from_files(
            input_dir=txt_dir,
            bundle_name="from-files",
            bundles_dir=bundles_dir,
        )

        assert bundle.name == "from-files"
        assert len(bundle.cases) == 2
        assert not bundle.has_labels
        assert bundle.cases[0].id == "sample1"
        assert bundle.cases[0].text == "Hello world"


class TestBundleProperties:
    """Test Bundle dataclass properties."""

    def test_has_labels_true(self, sample_bundle: Bundle) -> None:
        assert sample_bundle.has_labels is True

    def test_has_labels_false(self) -> None:
        bundle = Bundle(name="no-labels", description="", created="")
        assert bundle.has_labels is False

    def test_labeled_count(self, sample_bundle: Bundle) -> None:
        assert sample_bundle.labeled_count == 2

    def test_labeled_count_partial(self) -> None:
        bundle = Bundle(
            name="partial",
            description="",
            created="",
            cases=[
                BundleCase(id="a", category="t", text="x"),
                BundleCase(id="b", category="t", text="y"),
            ],
            labels={"a": BundleLabel(id="a", expected={})},
        )
        assert bundle.labeled_count == 1
