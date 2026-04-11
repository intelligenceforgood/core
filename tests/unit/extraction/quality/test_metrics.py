"""Tests for extraction quality metrics computation."""

from __future__ import annotations

from i4g.extraction.quality.metrics import ExtractionMetrics, compute_metrics, save_metrics
from i4g.extraction.types import ExtractionResult, ModuleReport, ModuleStatus, ScoredEntity


def _make_result(
    entities: list[tuple[str, str, float, str]],
    reports: list[tuple[str, ModuleStatus, float]] | None = None,
) -> ExtractionResult:
    """Build a synthetic ExtractionResult.

    Args:
        entities: List of (entity_type, value, confidence, source_module).
        reports: List of (module_name, status, elapsed_seconds).
    """
    return ExtractionResult(
        entities=[
            ScoredEntity(
                entity_type=etype,
                value=val,
                canonical_value=val,
                confidence=conf,
                source_module=src,
            )
            for etype, val, conf, src in entities
        ],
        module_reports=[
            ModuleReport(module_name=mod, status=status, elapsed_seconds=elapsed)
            for mod, status, elapsed in (reports or [])
        ],
    )


class TestComputeMetrics:
    def test_empty_results(self) -> None:
        metrics = compute_metrics([])
        assert metrics.case_count == 0
        assert metrics.total_entities == 0
        assert metrics.entities_per_type == {}

    def test_entity_counts_per_type(self) -> None:
        results = [
            _make_result(
                [
                    ("person", "John", 0.9, "llm"),
                    ("email_address", "j@x.com", 0.95, "regex"),
                ]
            ),
            _make_result(
                [
                    ("person", "Jane", 0.8, "llm"),
                ]
            ),
        ]
        metrics = compute_metrics(results)
        assert metrics.case_count == 2
        assert metrics.total_entities == 3
        assert metrics.entities_per_type["person"] == 2
        assert metrics.entities_per_type["email_address"] == 1

    def test_module_contributions(self) -> None:
        results = [
            _make_result(
                [
                    ("person", "John", 0.9, "llm"),
                    ("email_address", "j@x.com", 0.95, "regex"),
                    ("phone_number", "555-1234", 0.85, "regex"),
                ]
            ),
        ]
        metrics = compute_metrics(results)
        assert metrics.module_contributions["llm"] == 1
        assert metrics.module_contributions["regex"] == 2

    def test_confidence_histogram(self) -> None:
        results = [
            _make_result(
                [
                    ("person", "A", 0.2, "llm"),
                    ("person", "B", 0.6, "llm"),
                    ("person", "C", 0.95, "llm"),
                ]
            ),
        ]
        metrics = compute_metrics(results)
        hist = metrics.confidence_histogram["person"]
        assert hist["0.0-0.3"] == 1  # 0.2
        assert hist["0.5-0.7"] == 1  # 0.6
        assert hist["0.9-1.0"] == 1  # 0.95

    def test_module_latency_and_failures(self) -> None:
        results = [
            _make_result(
                [("person", "John", 0.9, "llm")],
                reports=[
                    ("regex", ModuleStatus.SUCCESS, 0.01),
                    ("llm", ModuleStatus.FAILED, 1.5),
                ],
            ),
            _make_result(
                [],
                reports=[
                    ("regex", ModuleStatus.SUCCESS, 0.02),
                    ("llm", ModuleStatus.SUCCESS, 0.8),
                ],
            ),
        ]
        metrics = compute_metrics(results)
        assert round(metrics.module_latency["regex"], 4) == 0.03
        assert round(metrics.module_latency["llm"], 4) == 2.3
        assert metrics.module_failures["llm"] == 1
        assert "regex" not in metrics.module_failures


class TestSaveMetrics:
    def test_saves_json_file(self, tmp_path) -> None:
        metrics = ExtractionMetrics(
            case_count=5,
            total_entities=10,
            entities_per_type={"person": 5, "email_address": 5},
        )
        filepath = save_metrics(metrics, metrics_dir=tmp_path)
        assert filepath.exists()
        assert filepath.suffix == ".json"

        import json

        data = json.loads(filepath.read_text())
        assert data["case_count"] == 5
        assert data["total_entities"] == 10
        assert data["entities_per_type"]["person"] == 5
