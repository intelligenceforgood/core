"""Entity extraction QA command group.

Provides ``i4g entity-qa`` subcommands for managing test bundles,
running extraction quality tests, scoring, comparing modules, and
generating reports.

Subcommands
-----------
- ``bundle list|download|create`` — manage test bundles
- ``test module|orchestrator|deployed`` — run extraction tests
- ``compare`` — side-by-side module comparison
- ``score`` — compute precision/recall/F1 against golden labels
- ``report`` — combined score + compare + statistics
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import typer

logger = logging.getLogger(__name__)

entity_qa_app = typer.Typer(help="Entity extraction quality assurance tools.")

# ---------------------------------------------------------------------------
# bundle subcommand group
# ---------------------------------------------------------------------------

bundle_app = typer.Typer(help="Manage test bundles.")
entity_qa_app.add_typer(bundle_app, name="bundle")


@bundle_app.command("list")
def bundle_list(
    bundles_dir: Path | None = typer.Option(None, "--dir", help="Override bundles directory."),
) -> None:
    """List locally available test bundles."""
    from i4g.extraction.quality.bundle import list_bundles

    bundles = list_bundles(bundles_dir=bundles_dir)
    if not bundles:
        typer.echo("No bundles found.")
        raise typer.Exit()

    for b in bundles:
        typer.echo(
            f"  {b['name']:<25} cases={b['case_count']:<5} " f"labels={b['label_count']:<5} created={b['created']}"
        )
        if b["description"]:
            typer.echo(f"    {b['description']}")


@bundle_app.command("download")
def bundle_download(
    name: str = typer.Argument(..., help="Bundle name to download."),
    bucket_prefix: str = typer.Option(
        "gs://i4g-dev-data-bundles/entity-qa",
        "--bucket",
        help="GCS bucket prefix.",
    ),
    bundles_dir: Path | None = typer.Option(None, "--dir", help="Override bundles directory."),
) -> None:
    """Download a bundle from GCS."""
    from i4g.extraction.quality.bundle import download_bundle

    try:
        path = download_bundle(name, bucket_prefix=bucket_prefix, bundles_dir=bundles_dir)
        typer.echo(f"Downloaded bundle '{name}' to {path}")
    except RuntimeError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None


@bundle_app.command("create")
def bundle_create(
    name: str = typer.Argument(..., help="Bundle name."),
    from_golden: Path | None = typer.Option(None, "--from-golden", help="Golden test set JSON file."),
    from_files: Path | None = typer.Option(None, "--from-files", help="Directory of .txt files."),
    description: str = typer.Option("", "--description", "-d", help="Bundle description."),
    bundles_dir: Path | None = typer.Option(None, "--dir", help="Override bundles directory."),
) -> None:
    """Create a new test bundle from golden set or raw text files."""
    from i4g.extraction.quality.bundle import create_bundle_from_files, create_bundle_from_golden_set

    if from_golden:
        bundle = create_bundle_from_golden_set(
            golden_path=from_golden,
            bundle_name=name,
            description=description,
            bundles_dir=bundles_dir,
        )
    elif from_files:
        bundle = create_bundle_from_files(
            input_dir=from_files,
            bundle_name=name,
            description=description,
            bundles_dir=bundles_dir,
        )
    else:
        typer.echo("Error: provide --from-golden or --from-files", err=True)
        raise typer.Exit(1)

    typer.echo(f"Created bundle '{bundle.name}' with {len(bundle.cases)} cases, " f"{bundle.labeled_count} labels.")


@bundle_app.command("add-case")
def bundle_add_case(
    bundle_name: str = typer.Option("regression-v1", "--bundle", "-b", help="Target bundle name."),
    text: str = typer.Option(..., "--text", "-t", help="Case text."),
    label: str = typer.Option(
        "",
        "--label",
        "-l",
        help='Golden label JSON, e.g. \'{"person": ["John Doe"], "email_address": ["j@x.com"]}\'.',
    ),
    case_id: str = typer.Option("", "--id", help="Case ID (auto-generated if omitted)."),
    category: str = typer.Option("manual", "--category", "-c", help="Case category tag."),
    bundles_dir: Path | None = typer.Option(None, "--dir", help="Override bundles directory."),
) -> None:
    """Add a single case (with optional golden label) to an existing bundle."""
    from i4g.extraction.quality.bundle import add_case_to_bundle

    parsed_label: dict[str, list[str]] | None = None
    if label:
        try:
            parsed_label = json.loads(label)
        except json.JSONDecodeError as exc:
            typer.echo(f"Error: invalid JSON in --label: {exc}", err=True)
            raise typer.Exit(1) from None

    case = add_case_to_bundle(
        bundle_name=bundle_name,
        text=text,
        expected=parsed_label,
        case_id=case_id or None,
        category=category,
        bundles_dir=bundles_dir,
    )
    typer.echo(f"Added case '{case.id}' to bundle '{bundle_name}'.")


# ---------------------------------------------------------------------------
# test subcommand group
# ---------------------------------------------------------------------------

test_app = typer.Typer(help="Run extraction tests on bundles.")
entity_qa_app.add_typer(test_app, name="test")


@test_app.command("module")
def test_module(
    module_name: str = typer.Argument(..., help="Module name (regex, heuristic, llm, ml_ner)."),
    bundle: str = typer.Option("regression-v1", "--bundle", "-b", help="Bundle name."),
    output_format: str = typer.Option("text", "--format", "-f", help="Output format: text or json."),
    bundles_dir: Path | None = typer.Option(None, "--dir", help="Override bundles directory."),
) -> None:
    """Run a single extraction module on a bundle."""
    from i4g.extraction.orchestrator import extract_entities
    from i4g.extraction.quality.bundle import load_bundle
    from i4g.extraction.quality.scorer import score_case

    b = load_bundle(bundle, bundles_dir=bundles_dir)
    results = []

    for case in b.cases:
        result = extract_entities(case.text, modules=[module_name])

        case_data: dict = {
            "case_id": case.id,
            "entities": [
                {
                    "type": e.entity_type,
                    "value": e.canonical_value,
                    "confidence": round(e.confidence, 3),
                }
                for e in result.entities
            ],
        }

        # If labels available, highlight misses.
        if case.id in b.labels:
            cs = score_case(case.id, result, b.labels[case.id])
            case_data["missing"] = cs.missing_values
            case_data["extra_count"] = len(cs.extra_entities)

        results.append(case_data)

    if output_format == "json":
        typer.echo(json.dumps(results, indent=2))
    else:
        for r in results:
            typer.echo(f"\n--- {r['case_id']} ---")
            for e in r["entities"]:
                typer.echo(f"  [{e['type']}] {e['value']} (conf={e['confidence']})")
            if "missing" in r and r["missing"]:
                typer.echo("  MISSED:")
                for etype, vals in r["missing"].items():
                    for v in vals:
                        typer.echo(f"    [{etype}] {v}")


@test_app.command("orchestrator")
def test_orchestrator(
    bundle: str = typer.Option("regression-v1", "--bundle", "-b", help="Bundle name."),
    modules: str | None = typer.Option(None, "--modules", "-m", help="Comma-separated module names."),
    output_format: str = typer.Option("text", "--format", "-f", help="Output format: text or json."),
    bundles_dir: Path | None = typer.Option(None, "--dir", help="Override bundles directory."),
) -> None:
    """Run the full orchestrator on a bundle."""
    from i4g.extraction.orchestrator import extract_entities
    from i4g.extraction.quality.bundle import load_bundle
    from i4g.extraction.quality.report import format_module_breakdown

    module_list = modules.split(",") if modules else None
    b = load_bundle(bundle, bundles_dir=bundles_dir)

    all_results = []

    for case in b.cases:
        result = extract_entities(
            case.text,
            modules=module_list,
            include_merge_log=True,
        )

        # Group entities by source module.
        by_module: dict[str, list] = {}
        for e in result.entities:
            by_module.setdefault(e.source_module, []).append(e)

        # Dropped entities from merge log.
        from i4g.extraction.types import MergeAction

        dropped = [d for d in result.merge_log if d.action == MergeAction.DROPPED]

        if output_format == "json":
            all_results.append(
                {
                    "case_id": case.id,
                    "entities": [
                        {
                            "type": e.entity_type,
                            "value": e.canonical_value,
                            "confidence": round(e.confidence, 3),
                            "source": e.source_module,
                        }
                        for e in result.entities
                    ],
                    "dropped": [{"type": d.entity_type, "value": d.value, "reason": d.reason} for d in dropped],
                    "modules": {
                        r.module_name: {
                            "status": r.status.value,
                            "entity_count": r.entity_count,
                            "elapsed_seconds": r.elapsed_seconds,
                        }
                        for r in result.module_reports
                    },
                }
            )
        else:
            typer.echo(
                format_module_breakdown(
                    case.id,
                    by_module,
                    result.entities,
                    [
                        type("DroppedEntity", (), {"entity_type": d.entity_type, "canonical_value": d.value})()
                        for d in dropped
                    ],
                )
            )

    if output_format == "json":
        typer.echo(json.dumps(all_results, indent=2))


@test_app.command("deployed")
def test_deployed(
    bundle: str = typer.Option("regression-v1", "--bundle", "-b", help="Bundle name."),
    env: str = typer.Option("dev", "--env", help="Target environment: dev or prod."),
    bundles_dir: Path | None = typer.Option(None, "--dir", help="Override bundles directory."),
) -> None:
    """Run extraction via deployed Cloud Run QA job and compare with local.

    This command uploads test cases to GCS, triggers the QA job, polls for
    completion, and compares results with local orchestrator output.

    Note: Requires ``gcloud`` auth and appropriate permissions.
    """
    typer.echo(
        "Error: 'test deployed' is not yet implemented. " "This will trigger a Cloud Run QA job and compare results.",
        err=True,
    )
    raise typer.Exit(1)


# ---------------------------------------------------------------------------
# compare command
# ---------------------------------------------------------------------------


@entity_qa_app.command("compare")
def compare(
    bundle: str = typer.Option("regression-v1", "--bundle", "-b", help="Bundle name."),
    modules: str = typer.Option(
        "regex,heuristic",
        "--modules",
        "-m",
        help="Comma-separated module names to compare individually.",
    ),
    bundles_dir: Path | None = typer.Option(None, "--dir", help="Override bundles directory."),
) -> None:
    """Compare individual modules vs. orchestrator on the same bundle."""
    from i4g.extraction.orchestrator import extract_entities
    from i4g.extraction.quality.bundle import load_bundle
    from i4g.extraction.quality.report import ComparisonReport, ModuleComparison, format_comparison_table
    from i4g.extraction.quality.scorer import score_bundle

    b = load_bundle(bundle, bundles_dir=bundles_dir)
    if not b.has_labels:
        typer.echo(f"Error: bundle '{bundle}' has no golden labels", err=True)
        raise typer.Exit(1)

    # Run orchestrator on all cases.
    orch_results: dict[str, object] = {}
    for case in b.cases:
        orch_results[case.id] = extract_entities(case.text)

    orch_score = score_bundle(b, orch_results)

    # Run each module independently.
    module_list = [m.strip() for m in modules.split(",") if m.strip()]
    module_comparisons: list[ModuleComparison] = []

    for mod_name in module_list:
        mod_results = {}
        for case in b.cases:
            mod_results[case.id] = extract_entities(case.text, modules=[mod_name])

        mod_score = score_bundle(b, mod_results)
        module_comparisons.append(
            ModuleComparison(
                module_name=mod_name,
                per_type=mod_score.aggregate_type_metrics,
            )
        )

    comparison = ComparisonReport(
        orchestrator_score=orch_score,
        module_scores=module_comparisons,
    )
    typer.echo(format_comparison_table(comparison))


# ---------------------------------------------------------------------------
# score command
# ---------------------------------------------------------------------------


@entity_qa_app.command("score")
def score(
    bundle: str = typer.Option("regression-v1", "--bundle", "-b", help="Bundle name."),
    threshold: float = typer.Option(0.0, "--threshold", "-t", help="Fail if overall F1 < threshold."),
    save: bool = typer.Option(True, "--save/--no-save", help="Save report to data/entity-qa/reports/."),
    output_format: str = typer.Option("text", "--format", "-f", help="Output format: text or json."),
    bundles_dir: Path | None = typer.Option(None, "--dir", help="Override bundles directory."),
) -> None:
    """Score extraction against golden labels. Optionally fail below threshold."""
    from i4g.extraction.orchestrator import extract_entities
    from i4g.extraction.quality.bundle import load_bundle
    from i4g.extraction.quality.report import format_case_details, format_score_table, to_json_report
    from i4g.extraction.quality.scorer import load_previous_score, save_score_report, score_bundle

    b = load_bundle(bundle, bundles_dir=bundles_dir)
    if not b.has_labels:
        typer.echo(f"Error: bundle '{bundle}' has no golden labels", err=True)
        raise typer.Exit(1)

    # Run orchestrator on all cases.
    results = {}
    for case in b.cases:
        results[case.id] = extract_entities(case.text)

    bundle_score = score_bundle(b, results)

    # Load previous for regression detection.
    previous = load_previous_score(bundle)

    if output_format == "json":
        typer.echo(json.dumps(to_json_report(bundle_score), indent=2))
    else:
        typer.echo(format_score_table(bundle_score, previous=previous))
        typer.echo(format_case_details(bundle_score))

    if save:
        report_path = save_score_report(bundle_score)
        typer.echo(f"\nReport saved to {report_path}")

    # Check threshold.
    if threshold > 0 and bundle_score.overall_f1 < threshold:
        typer.echo(
            f"\nFAILED: Overall F1 {bundle_score.overall_f1:.3f} < threshold {threshold:.3f}",
            err=True,
        )
        raise typer.Exit(1)

    # Check for regressions.
    if previous:
        old_f1 = previous.get("overall_f1", 0.0)
        if bundle_score.overall_f1 < old_f1 - 0.01:
            typer.echo(
                f"\nWARNING: F1 regressed from {old_f1:.3f} to {bundle_score.overall_f1:.3f}",
                err=True,
            )


# ---------------------------------------------------------------------------
# report command
# ---------------------------------------------------------------------------


@entity_qa_app.command("report")
def report(
    bundle: str = typer.Option("regression-v1", "--bundle", "-b", help="Bundle name."),
    output_format: str = typer.Option("text", "--format", "-f", help="Output format: text or json."),
    bundles_dir: Path | None = typer.Option(None, "--dir", help="Override bundles directory."),
) -> None:
    """Generate a combined quality report (score + compare + summary)."""
    from i4g.extraction.orchestrator import extract_entities
    from i4g.extraction.quality.bundle import load_bundle
    from i4g.extraction.quality.report import (
        ComparisonReport,
        ModuleComparison,
        format_case_details,
        format_comparison_table,
        format_score_table,
        to_json_report,
    )
    from i4g.extraction.quality.scorer import load_previous_score, save_score_report, score_bundle

    b = load_bundle(bundle, bundles_dir=bundles_dir)
    if not b.has_labels:
        typer.echo(f"Error: bundle '{bundle}' has no golden labels", err=True)
        raise typer.Exit(1)

    # Run orchestrator.
    orch_results = {}
    for case in b.cases:
        orch_results[case.id] = extract_entities(case.text)

    bundle_score = score_bundle(b, orch_results)
    previous = load_previous_score(bundle)

    # Score table.
    if output_format == "json":
        report_data = to_json_report(bundle_score)
        # Add module comparison.
        module_sections = {}
        for mod_name in ["regex", "heuristic"]:
            mod_results = {}
            for case in b.cases:
                mod_results[case.id] = extract_entities(case.text, modules=[mod_name])
            mod_score = score_bundle(b, mod_results)
            module_sections[mod_name] = {
                etype: {"f1": round(m.f1, 4), "precision": round(m.precision, 4), "recall": round(m.recall, 4)}
                for etype, m in mod_score.aggregate_type_metrics.items()
            }
        report_data["module_comparison"] = module_sections
        typer.echo(json.dumps(report_data, indent=2))
    else:
        typer.echo("=" * 60)
        typer.echo("ENTITY EXTRACTION QUALITY REPORT")
        typer.echo("=" * 60)
        typer.echo("")
        typer.echo(format_score_table(bundle_score, previous=previous))
        typer.echo("")
        typer.echo(format_case_details(bundle_score))

        # Module comparison.
        typer.echo("")
        typer.echo("=" * 60)
        module_comparisons: list[ModuleComparison] = []
        for mod_name in ["regex", "heuristic"]:
            mod_results = {}
            for case in b.cases:
                mod_results[case.id] = extract_entities(case.text, modules=[mod_name])
            mod_score = score_bundle(b, mod_results)
            module_comparisons.append(ModuleComparison(module_name=mod_name, per_type=mod_score.aggregate_type_metrics))

        comparison = ComparisonReport(
            orchestrator_score=bundle_score,
            module_scores=module_comparisons,
        )
        typer.echo(format_comparison_table(comparison))

    # Save report.
    report_path = save_score_report(bundle_score)
    typer.echo(f"\nReport saved to {report_path}")


# ---------------------------------------------------------------------------
# analyze-fps command
# ---------------------------------------------------------------------------


@entity_qa_app.command("analyze-fps")
def analyze_fps(
    bundle: str = typer.Option("regression-v1", "--bundle", "-b", help="Bundle name to analyze."),
    min_occurrences: int = typer.Option(
        2, "--min-occurrences", "-n", help="Minimum occurrences to flag as suspicious."
    ),
    max_confidence: float = typer.Option(0.7, "--max-confidence", help="Flag entities with avg confidence below this."),
    output_format: str = typer.Option("text", "--format", "-f", help="Output format: text or json."),
    bundles_dir: Path | None = typer.Option(None, "--dir", help="Override bundles directory."),
) -> None:
    """Identify probable false positives from extraction results.

    Runs extraction on all cases in a bundle, then surfaces entities that
    appear frequently with low average confidence — likely false positives.
    """
    from collections import defaultdict

    from i4g.extraction.orchestrator import extract_entities
    from i4g.extraction.quality.bundle import load_bundle

    b = load_bundle(bundle, bundles_dir=bundles_dir)

    # Track (type, value) → list of (case_id, confidence).
    entity_occurrences: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)

    for case in b.cases:
        result = extract_entities(case.text)
        for e in result.entities:
            key = (e.entity_type, e.canonical_value.lower())
            entity_occurrences[key].append((case.id, e.confidence))

    # Filter to suspicious entries.
    suspicious: list[dict] = []
    for (etype, value), occurrences in entity_occurrences.items():
        if len(occurrences) < min_occurrences:
            continue
        avg_conf = sum(c for _, c in occurrences) / len(occurrences)
        if avg_conf >= max_confidence:
            continue
        suspicious.append(
            {
                "entity_type": etype,
                "value": value,
                "occurrences": len(occurrences),
                "avg_confidence": round(avg_conf, 3),
                "sample_cases": [cid for cid, _ in occurrences[:5]],
            }
        )

    # Sort by occurrence count descending.
    suspicious.sort(key=lambda x: (-x["occurrences"], x["avg_confidence"]))

    if output_format == "json":
        typer.echo(json.dumps(suspicious, indent=2))
    else:
        if not suspicious:
            typer.echo("No suspicious false positives detected.")
            raise typer.Exit()

        typer.echo(f"Probable false positives (>={min_occurrences} occurrences, avg conf < {max_confidence}):\n")
        for entry in suspicious:
            typer.echo(
                f"  [{entry['entity_type']}] {entry['value']}"
                f"  (count={entry['occurrences']}, avg_conf={entry['avg_confidence']})"
            )
            typer.echo(f"    sample cases: {', '.join(entry['sample_cases'])}")


# ---------------------------------------------------------------------------
# blocklist subcommand group
# ---------------------------------------------------------------------------

blocklist_app = typer.Typer(help="Manage the entity extraction blocklist.")
entity_qa_app.add_typer(blocklist_app, name="blocklist")


@blocklist_app.command("list")
def blocklist_list(
    entity_type: str | None = typer.Option(None, "--type", "-t", help="Filter by entity type."),
) -> None:
    """Show current blocklist entries by type."""
    from i4g.extraction.modules.blocklist import BlocklistModule

    blocklist = BlocklistModule(config_path=_blocklist_config_path())

    for etype, values in sorted(blocklist._blocklist.items()):
        if entity_type and etype != entity_type:
            continue
        typer.echo(f"\n[{etype}] ({len(values)} entries)")
        for v in sorted(values):
            typer.echo(f"  {v}")


@blocklist_app.command("add")
def blocklist_add(
    entity_type: str = typer.Argument(..., help="Entity type (e.g. 'person', 'organization')."),
    value: str = typer.Argument(..., help="Value to add to the blocklist."),
) -> None:
    """Add a new false-positive entry to the blocklist config file."""
    config_path = _blocklist_config_path()

    # Load existing TOML or start fresh.
    entries: dict[str, list[str]] = {}
    if config_path.is_file():
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[no-redef]
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        for etype, section in data.items():
            if isinstance(section, dict) and "values" in section:
                entries[etype] = list(section["values"])

    # Add the new entry.
    if entity_type not in entries:
        entries[entity_type] = []
    if value not in entries[entity_type]:
        entries[entity_type].append(value)

    # Write back.
    _write_blocklist_toml(config_path, entries)
    typer.echo(f"Added '{value}' to [{entity_type}] blocklist in {config_path}")


@blocklist_app.command("test")
def blocklist_test(
    text: str = typer.Argument(..., help="Text to check against the blocklist."),
) -> None:
    """Show which blocklist entries would fire on given text."""
    from i4g.extraction.modules.blocklist import BlocklistModule
    from i4g.extraction.orchestrator import extract_entities

    blocklist = BlocklistModule(config_path=_blocklist_config_path())

    # Run extraction first to get candidate entities.
    result = extract_entities(text, modules=["regex", "heuristic"])

    matched = 0
    for e in result.entities:
        if blocklist.is_blocklisted(e.entity_type, e.canonical_value):
            typer.echo(f"  BLOCKED: [{e.entity_type}] {e.canonical_value}")
            matched += 1
        else:
            typer.echo(f"  PASSED:  [{e.entity_type}] {e.canonical_value}")

    if matched == 0:
        typer.echo("\nNo blocklist matches found.")
    else:
        typer.echo(f"\n{matched} entity/entities would be blocked.")


def _blocklist_config_path() -> Path:
    """Resolve the path to the entity blocklist TOML file."""
    from i4g.settings import get_settings

    settings = get_settings()
    return Path(settings.app.project_root) / "config" / "entity_blocklist.toml"


def _write_blocklist_toml(path: Path, entries: dict[str, list[str]]) -> None:
    """Write blocklist entries to a TOML file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "# Entity extraction blocklist — known false positives.",
        "#",
        "# Edit this file directly or use: i4g entity-qa blocklist add <type> <value>",
        "",
    ]
    for etype in sorted(entries):
        lines.append(f"[{etype}]")
        values = sorted(set(entries[etype]))
        lines.append("values = [")
        for v in values:
            lines.append(f'    "{v}",')
        lines.append("]")
        lines.append("")
    path.write_text("\n".join(lines))
