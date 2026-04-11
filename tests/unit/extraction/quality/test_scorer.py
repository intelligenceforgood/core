"""Tests for entity extraction QA scorer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from i4g.extraction.quality.bundle import Bundle, BundleCase, BundleLabel
from i4g.extraction.quality.scorer import (
    BundleScore,
    TypeMetrics,
    save_score_report,
    score_bundle,
    score_case,
)
from i4g.extraction.types import ExtractionResult, ScoredEntity


def _entity(etype: str, value: str, conf: float = 0.9) -> ScoredEntity:
    """Helper to create a ScoredEntity."""
    return ScoredEntity(
        entity_type=etype,
        value=value,
        canonical_value=value.lower(),
        confidence=conf,
        source_module="test",
    )


class TestTypeMetrics:
    """Test TypeMetrics properties."""

    def test_perfect_precision_recall(self) -> None:
        m = TypeMetrics(entity_type="email", true_positives=5, false_positives=0, false_negatives=0)
        assert m.precision == 1.0
        assert m.recall == 1.0
        assert m.f1 == 1.0

    def test_zero_precision(self) -> None:
        m = TypeMetrics(entity_type="email", true_positives=0, false_positives=5, false_negatives=0)
        assert m.precision == 0.0
        assert m.f1 == 0.0

    def test_zero_recall(self) -> None:
        m = TypeMetrics(entity_type="email", true_positives=0, false_positives=0, false_negatives=5)
        assert m.recall == 0.0
        assert m.f1 == 0.0

    def test_empty(self) -> None:
        m = TypeMetrics(entity_type="email", true_positives=0, false_positives=0, false_negatives=0)
        assert m.precision == 0.0
        assert m.recall == 0.0
        assert m.f1 == 0.0

    def test_partial_precision_recall(self) -> None:
        m = TypeMetrics(entity_type="email", true_positives=3, false_positives=1, false_negatives=2)
        assert m.precision == pytest.approx(0.75)
        assert m.recall == pytest.approx(0.6)
        expected_f1 = 2 * 0.75 * 0.6 / (0.75 + 0.6)
        assert m.f1 == pytest.approx(expected_f1)


class TestScoreCase:
    """Test per-case scoring."""

    def test_perfect_match(self) -> None:
        result = ExtractionResult(
            entities=[
                _entity("email_address", "test@example.com"),
                _entity("phone_number", "5551234567"),
            ]
        )
        label = BundleLabel(
            id="case_01",
            expected={
                "email_address": ["test@example.com"],
                "phone_number": ["5551234567"],
            },
        )
        cs = score_case("case_01", result, label)
        assert cs.type_metrics["email_address"].true_positives == 1
        assert cs.type_metrics["email_address"].false_positives == 0
        assert cs.type_metrics["email_address"].false_negatives == 0
        assert not cs.missing_values
        assert not cs.extra_entities

    def test_missed_entities(self) -> None:
        result = ExtractionResult(entities=[_entity("email_address", "test@example.com")])
        label = BundleLabel(
            id="case_01",
            expected={
                "email_address": ["test@example.com"],
                "phone_number": ["5551234567"],
            },
        )
        cs = score_case("case_01", result, label)
        assert cs.type_metrics["phone_number"].false_negatives == 1
        assert "phone_number" in cs.missing_values
        assert "5551234567" in cs.missing_values["phone_number"]

    def test_extra_entities(self) -> None:
        result = ExtractionResult(
            entities=[
                _entity("email_address", "test@example.com"),
                _entity("person", "Wells Fargo"),
            ]
        )
        label = BundleLabel(
            id="case_01",
            expected={"email_address": ["test@example.com"]},
        )
        cs = score_case("case_01", result, label)
        assert len(cs.extra_entities) == 1
        assert cs.extra_entities[0].entity_type == "person"

    def test_empty_expected(self) -> None:
        result = ExtractionResult(entities=[_entity("person", "John Doe")])
        label = BundleLabel(id="case_01", expected={})
        cs = score_case("case_01", result, label)
        assert len(cs.extra_entities) == 1

    def test_empty_result(self) -> None:
        result = ExtractionResult()
        label = BundleLabel(
            id="case_01",
            expected={"email_address": ["test@example.com"]},
        )
        cs = score_case("case_01", result, label)
        assert cs.type_metrics["email_address"].false_negatives == 1
        assert cs.type_metrics["email_address"].true_positives == 0

    def test_case_insensitive_matching(self) -> None:
        result = ExtractionResult(entities=[_entity("wallet_address", "0xABCDEF")])
        label = BundleLabel(
            id="case_01",
            expected={"wallet_address": ["0xabcdef"]},
        )
        cs = score_case("case_01", result, label)
        assert cs.type_metrics["wallet_address"].true_positives == 1


class TestScoreBundle:
    """Test bundle-level scoring."""

    def test_aggregate_metrics(self) -> None:
        bundle = Bundle(
            name="test",
            description="",
            created="",
            cases=[
                BundleCase(id="c1", category="t", text="..."),
                BundleCase(id="c2", category="t", text="..."),
            ],
            labels={
                "c1": BundleLabel(id="c1", expected={"email_address": ["a@b.com"]}),
                "c2": BundleLabel(id="c2", expected={"email_address": ["c@d.com", "e@f.com"]}),
            },
        )
        results = {
            "c1": ExtractionResult(entities=[_entity("email_address", "a@b.com")]),
            "c2": ExtractionResult(entities=[_entity("email_address", "c@d.com")]),
        }
        bs = score_bundle(bundle, results)
        # c1: 1 TP, c2: 1 TP + 1 FN
        assert bs.aggregate_type_metrics["email_address"].true_positives == 2
        assert bs.aggregate_type_metrics["email_address"].false_negatives == 1
        assert len(bs.case_scores) == 2

    def test_overall_f1(self) -> None:
        bundle = Bundle(
            name="test",
            description="",
            created="",
            cases=[BundleCase(id="c1", category="t", text="...")],
            labels={
                "c1": BundleLabel(
                    id="c1",
                    expected={"email_address": ["a@b.com"], "phone_number": ["123"]},
                ),
            },
        )
        results = {
            "c1": ExtractionResult(
                entities=[
                    _entity("email_address", "a@b.com"),
                    _entity("phone_number", "123"),
                ]
            ),
        }
        bs = score_bundle(bundle, results)
        assert bs.overall_f1 == pytest.approx(1.0)

    def test_no_labels_raises(self) -> None:
        bundle = Bundle(name="test", description="", created="")
        with pytest.raises(ValueError, match="no golden labels"):
            score_bundle(bundle, {})


class TestSaveScoreReport:
    """Test score report persistence."""

    def test_saves_json(self, tmp_path: Path) -> None:
        bs = BundleScore(
            bundle_name="test",
            timestamp="2026-04-10T00:00:00Z",
        )
        bs.aggregate_type_metrics["email_address"] = TypeMetrics(
            entity_type="email_address",
            true_positives=5,
            false_positives=1,
            false_negatives=2,
        )
        path = save_score_report(bs, reports_dir=tmp_path)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["bundle_name"] == "test"
        assert "email_address" in data["per_type"]
        assert data["per_type"]["email_address"]["tp"] == 5
