"""Dossier building and processing helpers."""

from __future__ import annotations

import os
import uuid
from decimal import Decimal

from i4g.cli.utils import SETTINGS, console
from i4g.reports.bundle_builder import BundleCriteria
from i4g.reports.dossier_queue_processor import DossierQueueProcessor
from i4g.services.factories import build_bundle_builder, build_bundle_candidate_provider
from i4g.task_status import TaskStatusReporter


def build_dossiers(
    *,
    limit: int = 100,
    min_loss: float | None = None,
    recency_days: int | None = None,
    max_cases: int | None = None,
    jurisdiction_mode: str = "auto",
    cross_border_only: bool = False,
    dry_run: bool = False,
    preview: int = 5,
) -> None:
    """Generate dossier plans and optionally enqueue them."""

    provider = build_bundle_candidate_provider()
    candidates = provider.list_candidates(limit=limit)
    if not candidates:
        console.print(
            f"[yellow]No accepted cases found for bundling (limit={limit}). " "Review queue state before rerunning."
        )
        return

    min_loss_value = Decimal(str(min_loss)) if min_loss is not None else Decimal(str(SETTINGS.report.min_loss_usd))
    criteria = BundleCriteria(
        min_loss_usd=min_loss_value,
        recency_days=recency_days or SETTINGS.report.recency_days,
        max_cases_per_dossier=max_cases or SETTINGS.report.max_cases_per_dossier,
        jurisdiction_mode=jurisdiction_mode,
        require_cross_border=cross_border_only or SETTINGS.report.require_cross_border,
    )

    builder = build_bundle_builder()
    if dry_run:
        plans = builder.generate_plans(candidates=candidates, criteria=criteria)
        console.print(f"[cyan]\u2139\ufe0f Dry run:[/cyan] {len(plans)} dossier plan(s) would be created.")
        preview_count = min(preview, len(plans))
        for plan in plans[:preview_count]:
            console.print(
                "  - "
                f"{plan.plan_id} | cases={len(plan.cases)} | loss=${plan.total_loss_usd} | "
                f"jurisdiction={plan.jurisdiction_key} | cross_border={plan.cross_border}"
            )
        if len(plans) > preview_count:
            console.print(f"  ...and {len(plans) - preview_count} more plan(s).")
        return

    plan_ids = builder.build_and_enqueue(candidates=candidates, criteria=criteria)
    console.print(f"[green]\u2705 Enqueued {len(plan_ids)} dossier plan(s) for agent processing.")


def process_dossiers(
    *,
    task_id: str | None = None,
    task_status_url: str | None = None,
    batch_size: int = 10,
    dry_run: bool = False,
    preview: int = 5,
) -> None:
    """Lease queued dossier plans and render artifacts."""

    processor = DossierQueueProcessor()
    resolved_task_id = task_id or os.getenv("I4G_TASK_ID")
    endpoint = task_status_url or os.getenv("I4G_TASK_STATUS_URL")
    if not resolved_task_id and endpoint:
        resolved_task_id = f"dossier-cli-{uuid.uuid4()}"

    reporter = TaskStatusReporter(task_id=resolved_task_id, endpoint=endpoint)
    if reporter.is_enabled():
        reporter.update(status="started", message="CLI dossier processing started", batch_size=batch_size)

    summary = processor.process_batch(
        batch_size=batch_size,
        dry_run=dry_run,
        reporter=reporter if reporter.is_enabled() else None,
    )
    if summary.processed == 0:
        console.print("[yellow]No pending dossier plans found in the queue.[/yellow]")
        return

    console.print(
        "[green]\u2705 Processed {processed} plan(s) \u2014 completed={completed} failed={failed} dry_run={dry}[/green]".format(  # noqa: E501
            processed=summary.processed,
            completed=summary.completed,
            failed=summary.failed,
            dry="yes" if summary.dry_run else "no",
        )
    )

    preview_count = min(preview, len(summary.plans))
    for plan in summary.plans[:preview_count]:
        plan_status = plan.get("status")
        plan_id = plan.get("plan_id")
        artifacts = plan.get("artifacts") or []
        console.print(f"  - {plan_id} [{plan_status}]")
        if artifacts:
            console.print(f"      artifacts: {artifacts}")
        if plan.get("warnings"):
            console.print(f"      warnings: {plan['warnings']}")
        if plan.get("error"):
            console.print(f"      error: {plan['error']}")


__all__ = ["build_dossiers", "process_dossiers"]
