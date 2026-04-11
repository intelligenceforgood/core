"""Tests for entity extraction QA reports."""

from __future__ import annotations

import pytest

from i4g.extraction.quality.report import (
    ComparisonReport,
    ModuleComparison,
    format_case_details,
    format_comparison_table,
    format_score_table,
    to_json_report,
)
from i4g.extraction.quality.scorer import BundleScore, CaseScore, TypeMetrics
from i4g.extraction.types import ScoredEntity


def _metrics(etype: str, tp: int, fp: int, fn: int) -> TypeMetrics:
    return TypeMetrics(entity_type=etype, true_positives=tp, false_positives=fp, false_negatives=fn)


@pytest.fixture()
def sample_score() -> BundleScore:
    """A sample BundleScore for testing."""
    bs = BundleScore(
        bundle_name="test-bundle",
        timestamp="2026-04-10T00:00:00Z",
    )
    bs.aggregate_type_metrics = {
        "email_address": _metrics("email_address", 5, 1, 2),
        "phone_number": _metrics("phone_number", 3, 0, 1),
    }
    bs.case_scores = [
        CaseScore(
            case_id="case_01",
            type_metrics={"email_address": _metrics("email_address", 1, 0, 0)},
        ),
        CaseScore(
            case_id="case_02",
            type_metrics={"email_address": _metrics("email_address", 1, 1, 0)},
            missing_values={"phone_number": ["5551234567"]},
            extra_entities=[
                ScoredEntity(
                    entity_type="person",
                    value="Wells Fargo",
                    canonical_value="wells fargo",
                    confidence=0.5,
                    source_module="heuristic",
                )
            ],
        ),
    ]
    return bs


class TestFormatScoreTable:
    """Test score table formatting."""

    def test_contains_bundle_name(self, sample_score: BundleScore) -> None:
        output = format_score_table(sample_score)
        assert "test-bundle" in output

    def test_contains_type_rows(self, sample_score: BundleScore) -> None:
        output = format_score_table(sample_score)
        assert "email_address" in output
        assert "phone_number" in output

    def test_contains_overall(self, sample_score: BundleScore) -> None:
        output = format_score_table(sample_score)
        assert "OVERALL" in output

    def test_regression_delta(self, sample_score: BundleScore) -> None:
        previous = {
            "overall_f1": 0.5,
            "per_type": {
                "email_address": {"f1": 0.5},
            },
        }
        output = format_score_table(sample_score, previous=previous)
        assert "+" in output  # should show positive delta


class TestFormatCaseDetails:
    """Test case detail formatting."""

    def test_shows_missed(self, sample_score: BundleScore) -> None:
        output = format_case_details(sample_score)
        assert "case_02" in output
        assert "MISSED" in output
        assert "5551234567" in output

    def test_shows_extra(self, sample_score: BundleScore) -> None:
        output = format_case_details(sample_score)
        assert "EXTRA" in output
        assert "wells fargo" in output

    def test_all_perfect(self) -> None:
        bs = BundleScore(
            bundle_name="perfect",
            case_scores=[
                CaseScore(
                    case_id="c1",
                    type_metrics={"email_address": _metrics("email_address", 1, 0, 0)},
                ),
            ],
        )
        output = format_case_details(bs)
        assert "All cases matched" in output


class TestComparisonTable:
    """Test comparison table formatting."""

    def test_format(self, sample_score: BundleScore) -> None:
        comparison = ComparisonReport(
            orchestrator_score=sample_score,
            module_scores=[
                ModuleComparison(
                    module_name="regex",
                    per_type={"email_address": _metrics("email_address", 4, 0, 4)},
                ),
            ],
        )
        output = format_comparison_table(comparison)
        assert "regex" in output
        assert "orchestr." in output
        assert "email_address" in output


class TestJsonReport:
    """Test JSON report generation."""

    def test_fields(self, sample_score: BundleScore) -> None:
        data = to_json_report(sample_score)
        assert data["bundle_name"] == "test-bundle"
        assert "overall_f1" in data
        assert "per_type" in data
        assert "email_address" in data["per_type"]
        assert data["per_type"]["email_address"]["tp"] == 5
        # case_02 has issues
        assert len(data["cases"]) >= 1
        assert data["cases"][0]["case_id"] == "case_02"
