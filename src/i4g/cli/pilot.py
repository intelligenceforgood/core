"""Pilot-case seeding and dossier scheduling helpers."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from i4g.cli.utils import SETTINGS, console
from i4g.reports.bundle_builder import BundleCriteria
from i4g.reports.dossier_pilot import (
    DEFAULT_PILOT_CASES_PATH,
    load_pilot_case_specs,
    schedule_pilot_plans,
    seed_pilot_cases,
)


def schedule_pilot_dossiers(args: Any) -> None:
    """Seed curated pilot cases and optionally enqueue dossier plans."""

    cases_path = Path(args.cases_file).expanduser()
    try:
        specs = list(load_pilot_case_specs(cases_path))
    except Exception as exc:  # pragma: no cover - file IO errors surface here
        console.print(f"[red]❌ Failed to load pilot cases:[/red] {exc}")
        sys.exit(1)

    requested_ids = set()
    if args.cases:
        for raw in args.cases:
            for part in str(raw).split(","):
                value = part.strip()
                if value:
                    requested_ids.add(value)
    missing_from_config: list[str] = []
    if requested_ids:
        specs = [spec for spec in specs if spec.case_id in requested_ids]
        missing_from_config = sorted(requested_ids - {spec.case_id for spec in specs})

    if args.case_count:
        specs = specs[: args.case_count]

    if not specs:
        console.print("[red]❌ No pilot cases matched the provided filters.")
        sys.exit(1)

    seed_summary = seed_pilot_cases(specs)
    console.print(
        f"[green]✅ Seeded {len(seed_summary.case_ids)} pilot case(s) into structured + review stores.[/green]"
    )

    if missing_from_config:
        console.print(
            "[yellow]⚠️ The following case_id(s) were not present in the pilot config:[/yellow] "
            + ", ".join(missing_from_config)
        )

    if args.seed_only:
        console.print("[cyan]ℹ️ Seed-only mode enabled; skipping dossier plan generation.")
        return

    min_loss = Decimal(str(args.min_loss)) if args.min_loss is not None else Decimal(str(SETTINGS.report.min_loss_usd))
    criteria = BundleCriteria(
        min_loss_usd=min_loss,
        recency_days=args.recency_days or SETTINGS.report.recency_days,
        max_cases_per_dossier=args.max_cases or SETTINGS.report.max_cases_per_dossier,
        jurisdiction_mode=args.jurisdiction_mode,
        require_cross_border=args.cross_border_only or SETTINGS.report.require_cross_border,
    )

    schedule_summary = schedule_pilot_plans(specs, criteria=criteria, dry_run=args.dry_run)

    if schedule_summary.missing_cases:
        console.print(
            "[yellow]⚠️ Candidate provider missing case_id(s):[/yellow] " + ", ".join(schedule_summary.missing_cases)
        )

    if not schedule_summary.plan_ids:
        console.print("[yellow]No dossier plans matched the pilot selection after filtering.")
        return

    if schedule_summary.dry_run:
        console.print(
            f"[cyan]ℹ️ Dry run: {len(schedule_summary.plan_ids)} plan(s) would be generated: "
            + ", ".join(schedule_summary.plan_ids)
        )
    else:
        console.print(
            f"[green]✅ Enqueued {len(schedule_summary.plan_ids)} pilot plan(s): "
            + ", ".join(schedule_summary.plan_ids)
        )


__all__ = ["schedule_pilot_dossiers", "DEFAULT_PILOT_CASES_PATH"]
