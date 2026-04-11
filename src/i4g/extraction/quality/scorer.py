"""Precision / recall / F1 scoring for entity extraction.

Compares extraction results against golden labels at the
``(entity_type, canonical_value)`` level.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from i4g.extraction.quality.bundle import Bundle, BundleLabel
from i4g.extraction.types import ExtractionResult, ScoredEntity

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TypeMetrics:
    """Precision / recall / F1 for a single entity type."""

    entity_type: str
    true_positives: int
    false_positives: int
    false_negatives: int

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass(slots=True)
class CaseScore:
    """Detailed score for a single test case."""

    case_id: str
    type_metrics: dict[str, TypeMetrics] = field(default_factory=dict)
    extra_entities: list[ScoredEntity] = field(default_factory=list)
    """Entities extracted but not in golden labels."""
    missing_values: dict[str, list[str]] = field(default_factory=dict)
    """Values in golden labels but not extracted, by type."""


@dataclass(slots=True)
class BundleScore:
    """Aggregated score for a full bundle run."""

    bundle_name: str
    timestamp: str = ""
    case_scores: list[CaseScore] = field(default_factory=list)
    aggregate_type_metrics: dict[str, TypeMetrics] = field(default_factory=dict)

    @property
    def overall_f1(self) -> float:
        """Micro-averaged F1 across all types."""
        tp = sum(m.true_positives for m in self.aggregate_type_metrics.values())
        fp = sum(m.false_positives for m in self.aggregate_type_metrics.values())
        fn = sum(m.false_negatives for m in self.aggregate_type_metrics.values())
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        return 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0


def _normalize_value(value: str) -> str:
    """Lowercase and strip for comparison."""
    return value.strip().lower()


def score_case(
    case_id: str,
    result: ExtractionResult,
    label: BundleLabel,
) -> CaseScore:
    """Score a single case's extraction result against golden labels.

    Args:
        case_id: Test case identifier.
        result: Extraction result from the orchestrator.
        label: Golden expected entities.

    Returns:
        A ``CaseScore`` with per-type metrics.
    """
    # Build sets of (type, normalized_value) for extracted and expected.
    extracted_by_type: dict[str, set[str]] = {}
    for entity in result.entities:
        extracted_by_type.setdefault(entity.entity_type, set()).add(_normalize_value(entity.canonical_value))

    expected_by_type: dict[str, set[str]] = {}
    for etype, values in label.expected.items():
        expected_by_type[etype] = {_normalize_value(v) for v in values}

    all_types = set(extracted_by_type.keys()) | set(expected_by_type.keys())

    type_metrics: dict[str, TypeMetrics] = {}
    missing_values: dict[str, list[str]] = {}

    for etype in sorted(all_types):
        ext = extracted_by_type.get(etype, set())
        exp = expected_by_type.get(etype, set())
        tp = len(ext & exp)
        fp = len(ext - exp)
        fn = len(exp - ext)
        type_metrics[etype] = TypeMetrics(
            entity_type=etype,
            true_positives=tp,
            false_positives=fp,
            false_negatives=fn,
        )
        missed = exp - ext
        if missed:
            missing_values[etype] = sorted(missed)

    # Extra entities: types not in golden labels at all.
    extra = [e for e in result.entities if e.entity_type not in expected_by_type]

    return CaseScore(
        case_id=case_id,
        type_metrics=type_metrics,
        extra_entities=extra,
        missing_values=missing_values,
    )


def score_bundle(
    bundle: Bundle,
    results: dict[str, ExtractionResult],
) -> BundleScore:
    """Score all cases in a bundle.

    Args:
        bundle: The test bundle with golden labels.
        results: Mapping of case_id → ExtractionResult.

    Returns:
        ``BundleScore`` with per-case and aggregate metrics.
    """
    if not bundle.has_labels:
        raise ValueError(f"Bundle '{bundle.name}' has no golden labels")

    bundle_score = BundleScore(
        bundle_name=bundle.name,
        timestamp=datetime.now(tz=UTC).isoformat(),
    )

    # Per-type accumulators.
    agg_tp: dict[str, int] = {}
    agg_fp: dict[str, int] = {}
    agg_fn: dict[str, int] = {}

    for case in bundle.cases:
        if case.id not in bundle.labels:
            continue
        label = bundle.labels[case.id]
        result = results.get(case.id, ExtractionResult())
        case_score = score_case(case.id, result, label)
        bundle_score.case_scores.append(case_score)

        for etype, metrics in case_score.type_metrics.items():
            agg_tp[etype] = agg_tp.get(etype, 0) + metrics.true_positives
            agg_fp[etype] = agg_fp.get(etype, 0) + metrics.false_positives
            agg_fn[etype] = agg_fn.get(etype, 0) + metrics.false_negatives

    # Build aggregate.
    for etype in sorted(set(agg_tp) | set(agg_fp) | set(agg_fn)):
        bundle_score.aggregate_type_metrics[etype] = TypeMetrics(
            entity_type=etype,
            true_positives=agg_tp.get(etype, 0),
            false_positives=agg_fp.get(etype, 0),
            false_negatives=agg_fn.get(etype, 0),
        )

    return bundle_score


def save_score_report(
    score: BundleScore,
    reports_dir: Path | None = None,
) -> Path:
    """Persist a score report to JSON.

    Args:
        score: The computed bundle score.
        reports_dir: Override reports directory.

    Returns:
        Path to the saved report file.
    """
    if reports_dir is None:
        from i4g.settings import get_settings

        settings = get_settings()
        reports_dir = Path(settings.app.project_root) / "data" / "entity-qa" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"{score.bundle_name}_{ts}.json"
    report_path = reports_dir / filename

    data = {
        "bundle_name": score.bundle_name,
        "timestamp": score.timestamp,
        "overall_f1": round(score.overall_f1, 4),
        "per_type": {
            etype: {
                "precision": round(m.precision, 4),
                "recall": round(m.recall, 4),
                "f1": round(m.f1, 4),
                "tp": m.true_positives,
                "fp": m.false_positives,
                "fn": m.false_negatives,
            }
            for etype, m in score.aggregate_type_metrics.items()
        },
        "case_count": len(score.case_scores),
    }

    report_path.write_text(json.dumps(data, indent=2) + "\n")
    logger.info("Score report saved to %s", report_path)
    return report_path


def load_previous_score(
    bundle_name: str,
    reports_dir: Path | None = None,
) -> dict | None:
    """Load the most recent score report for a bundle.

    Returns:
        Parsed JSON dict, or ``None`` if no previous report exists.
    """
    if reports_dir is None:
        from i4g.settings import get_settings

        settings = get_settings()
        reports_dir = Path(settings.app.project_root) / "data" / "entity-qa" / "reports"

    if not reports_dir.exists():
        return None

    matches = sorted(reports_dir.glob(f"{bundle_name}_*.json"))
    if not matches:
        return None

    return json.loads(matches[-1].read_text())
