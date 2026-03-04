"""Pilot-case seeding and dossier scheduling helpers."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

from i4g.cli.utils import SETTINGS, console
from i4g.reports.bundle_builder import BundleCriteria
from i4g.reports.dossier_pilot import (
    DEFAULT_PILOT_CASES_PATH,
    load_pilot_case_specs,
    schedule_pilot_plans,
    seed_pilot_cases,
)


def schedule_pilot_dossiers(
    *,
    cases_file: str = str(DEFAULT_PILOT_CASES_PATH),
    cases: list[str] | None = None,
    case_count: int | None = None,
    seed_only: bool = False,
    min_loss: float | None = None,
    recency_days: int | None = None,
    max_cases: int | None = None,
    jurisdiction_mode: str = "auto",
    cross_border_only: bool = False,
    dry_run: bool = False,
) -> None:
    """Seed curated pilot cases and optionally enqueue dossier plans."""

    cases_path = Path(cases_file).expanduser()
    try:
        specs = list(load_pilot_case_specs(cases_path))
    except Exception as exc:  # pragma: no cover - file IO errors surface here
        console.print(f"[red]\u274c Failed to load pilot cases:[/red] {exc}")
        sys.exit(1)

    requested_ids = set()
    if cases:
        for raw in cases:
            for part in str(raw).split(","):
                value = part.strip()
                if value:
                    requested_ids.add(value)
    missing_from_config: list[str] = []
    if requested_ids:
        specs = [spec for spec in specs if spec.case_id in requested_ids]
        missing_from_config = sorted(requested_ids - {spec.case_id for spec in specs})

    if case_count:
        specs = specs[:case_count]

    if not specs:
        console.print("[red]\u274c No pilot cases matched the provided filters.")
        sys.exit(1)

    seed_summary = seed_pilot_cases(specs)
    console.print(
        f"[green]\u2705 Seeded {len(seed_summary.case_ids)} pilot case(s) into structured + review stores.[/green]"
    )

    if missing_from_config:
        console.print(
            "[yellow]\u26a0\ufe0f The following case_id(s) were not present in the pilot config:[/yellow] "
            + ", ".join(missing_from_config)
        )

    if seed_only:
        console.print("[cyan]\u2139\ufe0f Seed-only mode enabled; skipping dossier plan generation.")
        return

    resolved_min_loss = Decimal(str(min_loss)) if min_loss is not None else Decimal(str(SETTINGS.report.min_loss_usd))
    criteria = BundleCriteria(
        min_loss_usd=resolved_min_loss,
        recency_days=recency_days or SETTINGS.report.recency_days,
        max_cases_per_dossier=max_cases or SETTINGS.report.max_cases_per_dossier,
        jurisdiction_mode=jurisdiction_mode,
        require_cross_border=cross_border_only or SETTINGS.report.require_cross_border,
    )

    schedule_summary = schedule_pilot_plans(specs, criteria=criteria, dry_run=dry_run)

    if schedule_summary.missing_cases:
        console.print(
            "[yellow]\u26a0\ufe0f Candidate provider missing case_id(s):[/yellow] "
            + ", ".join(schedule_summary.missing_cases)
        )

    if not schedule_summary.plan_ids:
        console.print("[yellow]No dossier plans matched the pilot selection after filtering.")
        return

    if schedule_summary.dry_run:
        console.print(
            f"[cyan]\u2139\ufe0f Dry run: {len(schedule_summary.plan_ids)} plan(s) would be generated: "
            + ", ".join(schedule_summary.plan_ids)
        )
    else:
        console.print(
            f"[green]\u2705 Enqueued {len(schedule_summary.plan_ids)} pilot plan(s): "
            + ", ".join(schedule_summary.plan_ids)
        )


__all__ = ["schedule_pilot_dossiers", "DEFAULT_PILOT_CASES_PATH"]
