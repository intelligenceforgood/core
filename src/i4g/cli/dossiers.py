"""Dossier building and processing helpers."""

from __future__ import annotations

import os
import uuid
from decimal import Decimal
from typing import Any

from i4g.cli.utils import SETTINGS, console
from i4g.reports.bundle_builder import BundleCriteria
from i4g.reports.dossier_queue_processor import DossierQueueProcessor
from i4g.services.factories import build_bundle_builder, build_bundle_candidate_provider
from i4g.task_status import TaskStatusReporter


def build_dossiers(args: Any) -> None:
    """Generate dossier plans and optionally enqueue them."""

    provider = build_bundle_candidate_provider()
    candidates = provider.list_candidates(limit=args.limit)
    if not candidates:
        console.print(
            f"[yellow]No accepted cases found for bundling (limit={args.limit}). "
            "Review queue state before rerunning."
        )
        return

    min_loss_value = (
        Decimal(str(args.min_loss)) if args.min_loss is not None else Decimal(str(SETTINGS.report.min_loss_usd))
    )
    criteria = BundleCriteria(
        min_loss_usd=min_loss_value,
        recency_days=args.recency_days or SETTINGS.report.recency_days,
        max_cases_per_dossier=args.max_cases or SETTINGS.report.max_cases_per_dossier,
        jurisdiction_mode=args.jurisdiction_mode,
        require_cross_border=args.cross_border_only or SETTINGS.report.require_cross_border,
    )

    builder = build_bundle_builder()
    if args.dry_run:
        plans = builder.generate_plans(candidates=candidates, criteria=criteria)
        console.print(f"[cyan]ℹ️ Dry run:[/cyan] {len(plans)} dossier plan(s) would be created.")
        preview = min(args.preview, len(plans))
        for plan in plans[:preview]:
            console.print(
                "  - "
                f"{plan.plan_id} | cases={len(plan.cases)} | loss=${plan.total_loss_usd} | "
                f"jurisdiction={plan.jurisdiction_key} | cross_border={plan.cross_border}"
            )
        if len(plans) > preview:
            console.print(f"  ...and {len(plans) - preview} more plan(s).")
        return

    plan_ids = builder.build_and_enqueue(candidates=candidates, criteria=criteria)
    console.print(f"[green]✅ Enqueued {len(plan_ids)} dossier plan(s) for agent processing.")


def process_dossiers(args: Any) -> None:
    """Lease queued dossier plans and render artifacts."""

    processor = DossierQueueProcessor()
    task_id = args.task_id or os.getenv("I4G_TASK_ID")
    endpoint = args.task_status_url or os.getenv("I4G_TASK_STATUS_URL")
    if not task_id and endpoint:
        task_id = f"dossier-cli-{uuid.uuid4()}"

    reporter = TaskStatusReporter(task_id=task_id, endpoint=endpoint)
    if reporter.is_enabled():
        reporter.update(status="started", message="CLI dossier processing started", batch_size=args.batch_size)

    summary = processor.process_batch(
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        reporter=reporter if reporter.is_enabled() else None,
    )
    if summary.processed == 0:
        console.print("[yellow]No pending dossier plans found in the queue.[/yellow]")
        return

    console.print(
        "[green]✅ Processed {processed} plan(s) — completed={completed} failed={failed} dry_run={dry}[/green]".format(
            processed=summary.processed,
            completed=summary.completed,
            failed=summary.failed,
            dry="yes" if summary.dry_run else "no",
        )
    )

    preview = min(args.preview, len(summary.plans))
    for plan in summary.plans[:preview]:
        status = plan.get("status")
        plan_id = plan.get("plan_id")
        artifacts = plan.get("artifacts") or []
        console.print(f"  - {plan_id} [{status}]")
        if artifacts:
            console.print(f"      artifacts: {artifacts}")
        if plan.get("warnings"):
            console.print(f"      warnings: {plan['warnings']}")
        if plan.get("error"):
            console.print(f"      error: {plan['error']}")


__all__ = ["build_dossiers", "process_dossiers"]
