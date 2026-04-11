"""Quality metrics emission for extraction pipeline observability.

After each batch extraction run, emits structured metrics:
- Entity count per type
- Confidence distribution per type (histogram buckets)
- Module contribution percentages
- Extraction latency per module

Metrics are persisted to ``data/entity-qa/metrics/`` as JSON files
and logged for Cloud Monitoring pickup.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from i4g.extraction.types import ExtractionResult, ModuleStatus

logger = logging.getLogger(__name__)

# Histogram bucket boundaries for confidence scores.
_CONFIDENCE_BUCKETS = [0.0, 0.3, 0.5, 0.7, 0.8, 0.9, 1.0]


@dataclass(slots=True)
class ExtractionMetrics:
    """Aggregated metrics from a batch extraction run."""

    timestamp: str = ""
    case_count: int = 0
    total_entities: int = 0
    entities_per_type: dict[str, int] = field(default_factory=dict)
    confidence_histogram: dict[str, dict[str, int]] = field(default_factory=dict)
    """entity_type → {bucket_label: count}."""
    module_contributions: dict[str, int] = field(default_factory=dict)
    """module_name → entity count."""
    module_latency: dict[str, float] = field(default_factory=dict)
    """module_name → total elapsed seconds."""
    module_failures: dict[str, int] = field(default_factory=dict)
    """module_name → failure count."""


def _bucket_label(lo: float, hi: float) -> str:
    """Format a histogram bucket label."""
    return f"{lo:.1f}-{hi:.1f}"


def compute_metrics(results: list[ExtractionResult]) -> ExtractionMetrics:
    """Compute aggregated metrics from a list of extraction results.

    Args:
        results: Extraction results from a batch run.

    Returns:
        Aggregated ``ExtractionMetrics``.
    """
    metrics = ExtractionMetrics(
        timestamp=datetime.now(tz=UTC).isoformat(),
        case_count=len(results),
    )

    for result in results:
        for entity in result.entities:
            metrics.total_entities += 1
            metrics.entities_per_type[entity.entity_type] = metrics.entities_per_type.get(entity.entity_type, 0) + 1

            # Confidence histogram.
            etype_hist = metrics.confidence_histogram.setdefault(entity.entity_type, {})
            for i in range(len(_CONFIDENCE_BUCKETS) - 1):
                lo, hi = _CONFIDENCE_BUCKETS[i], _CONFIDENCE_BUCKETS[i + 1]
                label = _bucket_label(lo, hi)
                if label not in etype_hist:
                    etype_hist[label] = 0
                if lo <= entity.confidence < hi or (i == len(_CONFIDENCE_BUCKETS) - 2 and entity.confidence == hi):
                    etype_hist[label] += 1

            # Module contribution.
            metrics.module_contributions[entity.source_module] = (
                metrics.module_contributions.get(entity.source_module, 0) + 1
            )

        for report in result.module_reports:
            metrics.module_latency[report.module_name] = (
                metrics.module_latency.get(report.module_name, 0.0) + report.elapsed_seconds
            )
            if report.status == ModuleStatus.FAILED:
                metrics.module_failures[report.module_name] = metrics.module_failures.get(report.module_name, 0) + 1

    return metrics


def save_metrics(metrics: ExtractionMetrics, metrics_dir: Path | None = None) -> Path:
    """Persist metrics to a JSON file.

    Args:
        metrics: The computed metrics.
        metrics_dir: Override directory. Defaults to ``data/entity-qa/metrics/``.

    Returns:
        Path to the saved file.
    """
    if metrics_dir is None:
        from i4g.settings import get_settings

        settings = get_settings()
        metrics_dir = Path(settings.app.project_root) / "data" / "entity-qa" / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    filepath = metrics_dir / f"metrics_{ts}.json"

    data = {
        "timestamp": metrics.timestamp,
        "case_count": metrics.case_count,
        "total_entities": metrics.total_entities,
        "entities_per_type": metrics.entities_per_type,
        "confidence_histogram": metrics.confidence_histogram,
        "module_contributions": metrics.module_contributions,
        "module_latency": {k: round(v, 4) for k, v in metrics.module_latency.items()},
        "module_failures": metrics.module_failures,
    }

    filepath.write_text(json.dumps(data, indent=2) + "\n")
    logger.info("Extraction metrics saved to %s", filepath)
    return filepath


def log_metrics(metrics: ExtractionMetrics) -> None:
    """Log metrics as structured JSON for Cloud Monitoring pickup.

    Args:
        metrics: The computed metrics.
    """
    # Entity counts per type.
    for etype, count in sorted(metrics.entities_per_type.items()):
        logger.info(
            "extraction.entity_count entity_type=%s count=%d",
            etype,
            count,
        )

    # Module contributions.
    total = metrics.total_entities or 1
    for mod, count in sorted(metrics.module_contributions.items()):
        pct = round(count / total * 100, 1)
        logger.info(
            "extraction.module_contribution module=%s count=%d pct=%.1f",
            mod,
            count,
            pct,
        )

    # Module latency.
    for mod, elapsed in sorted(metrics.module_latency.items()):
        logger.info(
            "extraction.module_latency module=%s total_seconds=%.4f",
            mod,
            elapsed,
        )

    # Module failures.
    for mod, failures in sorted(metrics.module_failures.items()):
        logger.warning(
            "extraction.module_failures module=%s count=%d",
            mod,
            failures,
        )
