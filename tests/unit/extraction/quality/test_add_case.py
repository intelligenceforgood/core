"""Tests for bundle add-case functionality."""

from __future__ import annotations

from pathlib import Path

from i4g.extraction.quality.bundle import (
    Bundle,
    BundleCase,
    add_case_to_bundle,
    load_bundle,
    save_bundle,
)


def _setup_bundle(tmp_path: Path) -> None:
    """Create a minimal bundle in tmp_path."""
    bundle = Bundle(
        name="test-bundle",
        description="Test",
        created="2026-04-10T00:00:00+00:00",
        cases=[BundleCase(id="case-1", category="test", text="Some scam text.")],
        labels={},
    )
    save_bundle(bundle, bundles_dir=tmp_path)


class TestAddCaseToBundle:
    def test_add_case_without_label(self, tmp_path: Path) -> None:
        _setup_bundle(tmp_path)
        case = add_case_to_bundle(
            bundle_name="test-bundle",
            text="New case text",
            category="manual",
            bundles_dir=tmp_path,
        )
        assert case.text == "New case text"
        assert case.category == "manual"

        # Verify persisted.
        reloaded = load_bundle("test-bundle", bundles_dir=tmp_path)
        assert len(reloaded.cases) == 2
        assert reloaded.cases[1].text == "New case text"

    def test_add_case_with_label(self, tmp_path: Path) -> None:
        _setup_bundle(tmp_path)
        case = add_case_to_bundle(
            bundle_name="test-bundle",
            text="John Doe sent money",
            expected={"person": ["John Doe"]},
            case_id="custom-id",
            bundles_dir=tmp_path,
        )
        assert case.id == "custom-id"

        reloaded = load_bundle("test-bundle", bundles_dir=tmp_path)
        assert "custom-id" in reloaded.labels
        assert reloaded.labels["custom-id"].expected == {"person": ["John Doe"]}

    def test_add_case_generates_id(self, tmp_path: Path) -> None:
        _setup_bundle(tmp_path)
        case = add_case_to_bundle(
            bundle_name="test-bundle",
            text="Auto-id test",
            bundles_dir=tmp_path,
        )
        assert case.id.startswith("manual-")

    def test_add_to_nonexistent_bundle_raises(self, tmp_path: Path) -> None:
        import pytest

        with pytest.raises(FileNotFoundError):
            add_case_to_bundle(
                bundle_name="nonexistent",
                text="Some text",
                bundles_dir=tmp_path,
            )
