"""Human-readable and JSON quality reports for entity extraction.

Combines scoring, comparison, and summary statistics into terminal or
JSON output suitable for CI integration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from i4g.extraction.quality.scorer import BundleScore, TypeMetrics

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ModuleComparison:
    """Side-by-side results of running each module independently."""

    module_name: str
    per_type: dict[str, TypeMetrics] = field(default_factory=dict)


@dataclass(slots=True)
class ComparisonReport:
    """Orchestrator score vs. individual module scores."""

    orchestrator_score: BundleScore
    module_scores: list[ModuleComparison] = field(default_factory=list)


def format_score_table(score: BundleScore, *, previous: dict | None = None) -> str:
    """Format a BundleScore as a human-readable table.

    Args:
        score: The computed bundle score.
        previous: Optional previous score report dict for regression detection.

    Returns:
        Formatted string with per-type metrics and overall F1.
    """
    lines: list[str] = []
    lines.append(f"Bundle: {score.bundle_name}")
    lines.append(f"Cases:  {len(score.case_scores)}")
    lines.append("")

    header = f"{'Type':<25} {'Prec':>7} {'Rec':>7} {'F1':>7} {'TP':>5} {'FP':>5} {'FN':>5}"
    lines.append(header)
    lines.append("-" * len(header))

    prev_per_type = previous.get("per_type", {}) if previous else {}

    for etype, m in sorted(score.aggregate_type_metrics.items()):
        delta = ""
        if etype in prev_per_type:
            old_f1 = prev_per_type[etype].get("f1", 0.0)
            diff = m.f1 - old_f1
            if abs(diff) > 0.001:
                sign = "+" if diff > 0 else ""
                delta = f"  ({sign}{diff:.3f})"
        lines.append(
            f"{etype:<25} {m.precision:>7.3f} {m.recall:>7.3f} {m.f1:>7.3f}"
            f" {m.true_positives:>5} {m.false_positives:>5} {m.false_negatives:>5}{delta}"
        )

    lines.append("-" * len(header))
    overall_delta = ""
    if previous:
        old_overall = previous.get("overall_f1", 0.0)
        diff = score.overall_f1 - old_overall
        if abs(diff) > 0.001:
            sign = "+" if diff > 0 else ""
            overall_delta = f"  ({sign}{diff:.3f})"
    lines.append(f"{'OVERALL (micro)':<25} {'':>7} {'':>7} {score.overall_f1:>7.3f}{overall_delta}")

    return "\n".join(lines)


def format_case_details(score: BundleScore) -> str:
    """Format per-case details showing misses and extras.

    Args:
        score: The computed bundle score.

    Returns:
        Formatted string with per-case entity details.
    """
    lines: list[str] = []

    for cs in score.case_scores:
        has_issues = cs.missing_values or cs.extra_entities
        if not has_issues:
            continue

        lines.append(f"\n--- Case: {cs.case_id} ---")

        if cs.missing_values:
            lines.append("  MISSED:")
            for etype, vals in sorted(cs.missing_values.items()):
                for v in vals:
                    lines.append(f"    [{etype}] {v}")

        if cs.extra_entities:
            lines.append("  EXTRA:")
            for e in cs.extra_entities:
                lines.append(f"    [{e.entity_type}] {e.canonical_value} (conf={e.confidence:.2f})")

    if not lines:
        lines.append("All cases matched golden labels exactly.")

    return "\n".join(lines)


def format_module_breakdown(
    case_id: str,
    entities_by_module: dict[str, list],
    final_entities: list,
    dropped: list | None = None,
) -> str:
    """Format a per-case module breakdown showing what each module found.

    Args:
        case_id: The test case ID.
        entities_by_module: Module name → entities list.
        final_entities: Final merged entities.
        dropped: Entities that were dropped during merge.

    Returns:
        Formatted string.
    """
    lines = [f"Case: {case_id}"]

    for mod_name, entities in sorted(entities_by_module.items()):
        lines.append(f"  [{mod_name}] ({len(entities)} entities)")
        for e in entities:
            lines.append(f"    {e.entity_type}: {e.canonical_value} (conf={e.confidence:.2f})")

    lines.append(f"  [FINAL] ({len(final_entities)} entities)")
    for e in final_entities:
        lines.append(f"    {e.entity_type}: {e.canonical_value} (conf={e.confidence:.2f})")

    if dropped:
        lines.append(f"  [DROPPED] ({len(dropped)} entities)")
        for e in dropped:
            lines.append(f"    {e.entity_type}: {e.canonical_value}")

    return "\n".join(lines)


def format_comparison_table(comparison: ComparisonReport) -> str:
    """Format a side-by-side comparison of modules vs orchestrator.

    Args:
        comparison: The comparison report.

    Returns:
        Formatted string.
    """
    lines: list[str] = []
    lines.append("Module Comparison Report")
    lines.append(f"Bundle: {comparison.orchestrator_score.bundle_name}")
    lines.append("")

    # Collect all entity types.
    all_types: set[str] = set(comparison.orchestrator_score.aggregate_type_metrics.keys())
    for ms in comparison.module_scores:
        all_types.update(ms.per_type.keys())

    mod_names = ["orchestr."] + [ms.module_name for ms in comparison.module_scores]
    header = f"{'Type':<20}" + "".join(f" {n:>12}" for n in mod_names)
    lines.append(header)
    lines.append("-" * len(header))

    for etype in sorted(all_types):
        row = f"{etype:<20}"
        # Orchestrator F1.
        orch_m = comparison.orchestrator_score.aggregate_type_metrics.get(etype)
        row += f" {orch_m.f1:>12.3f}" if orch_m else f" {'n/a':>12}"
        # Module F1s.
        for ms in comparison.module_scores:
            m = ms.per_type.get(etype)
            row += f" {m.f1:>12.3f}" if m else f" {'n/a':>12}"
        lines.append(row)

    lines.append("-" * len(header))

    orch_f1 = comparison.orchestrator_score.overall_f1
    lines.append(f"{'OVERALL':<20} {orch_f1:>12.3f}")

    return "\n".join(lines)


def to_json_report(score: BundleScore) -> dict:
    """Convert a BundleScore to a JSON-serializable dict.

    Args:
        score: The computed bundle score.

    Returns:
        Dict suitable for ``json.dumps()``.
    """
    return {
        "bundle_name": score.bundle_name,
        "timestamp": score.timestamp,
        "overall_f1": round(score.overall_f1, 4),
        "case_count": len(score.case_scores),
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
        "cases": [
            {
                "case_id": cs.case_id,
                "missing": cs.missing_values,
                "extra_count": len(cs.extra_entities),
            }
            for cs in score.case_scores
            if cs.missing_values or cs.extra_entities
        ],
    }
