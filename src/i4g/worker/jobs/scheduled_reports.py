"""Scheduled reports job — generates recurring reports automatically.

Checks ``scheduled_reports`` for active schedules whose ``next_run_at``
has passed, triggers report generation via the existing report pipeline,
and advances the next run timestamp.

Run manually::

    i4g jobs scheduled-reports

Configure via ``I4G_ANALYTICS__SCHEDULED_REPORT_CHECK_INTERVAL_MINUTES``.
"""

from __future__ import annotations

import logging
import sys
import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from i4g.store.sql import scheduled_reports
from i4g.store.sql import session_factory as build_sql_session_factory
from i4g.worker.logging import configure_job_logging

logger = logging.getLogger(__name__)


def run_scheduled_reports() -> int:
    """Execute one pass of the scheduled report runner.

    Finds all active schedules past their ``next_run_at`` and triggers
    report generation for each.

    Returns:
        Number of reports triggered.
    """
    sf = build_sql_session_factory()
    session: Session = sf()
    try:
        return _process_due_schedules(session)
    finally:
        session.close()


def _process_due_schedules(session: Session) -> int:
    """Process all due report schedules.

    Args:
        session: Active database session.

    Returns:
        Number of reports triggered.
    """
    now = datetime.now(UTC)

    # Find active schedules that are due
    stmt = sa.select(scheduled_reports).where(
        scheduled_reports.c.is_active.is_(True),
        scheduled_reports.c.next_run_at <= now,
    )
    rows = session.execute(stmt).fetchall()

    if not rows:
        logger.info("No scheduled reports are due")
        return 0

    triggered = 0

    for row in rows:
        schedule_id = row.schedule_id
        template = row.template
        cadence = row.cadence
        scope = row.scope or {}
        options = row.options or {}
        recipients = row.recipients or []

        logger.info(
            "Triggering scheduled report: schedule=%s template=%s cadence=%s",
            schedule_id,
            template,
            cadence,
        )

        try:
            _trigger_report(
                template=template,
                scope=scope,
                options=options,
                recipients=recipients,
            )
            triggered += 1

            # Advance next_run_at based on cadence
            next_run = _compute_next_run(now, cadence)
            session.execute(
                scheduled_reports.update()
                .where(scheduled_reports.c.schedule_id == schedule_id)
                .values(last_run_at=now, next_run_at=next_run, updated_at=now)
            )

        except Exception:
            logger.exception("Failed to generate scheduled report %s", schedule_id)

    session.commit()
    logger.info("Scheduled reports: %d triggered", triggered)
    return triggered


def _trigger_report(
    *,
    template: str,
    scope: dict,
    options: dict,
    recipients: list[str],
) -> None:
    """Trigger report generation via the existing pipeline.

    Args:
        template: Report template name.
        scope: Scope configuration (e.g. campaign IDs, date range).
        options: Report generation options.
        recipients: Email addresses for delivery.
    """
    from i4g.worker.tasks import generate_report_for_case

    # Translate scope to the format expected by the report generator
    case_id = scope.get("case_id")
    if case_id:
        generate_report_for_case(case_id=case_id, template_name=template)
        logger.info("Queued report for case %s (template: %s)", case_id, template)
    else:
        logger.info(
            "Scheduled report template=%s scope=%s — "
            "auto-generation for non-case scopes will be added in a future sprint",
            template,
            scope,
        )


def _compute_next_run(current: datetime, cadence: str) -> datetime:
    """Compute the next run time based on cadence.

    Args:
        current: Current timestamp.
        cadence: Recurrence cadence (``weekly`` or ``monthly``).

    Returns:
        Next scheduled run timestamp.
    """
    if cadence == "weekly":
        return current + timedelta(weeks=1)
    if cadence == "monthly":
        # Advance by ~30 days; for month-exact logic use dateutil in the future
        return current + timedelta(days=30)
    if cadence == "daily":
        return current + timedelta(days=1)
    # Default: weekly
    logger.warning("Unknown cadence '%s' — defaulting to weekly", cadence)
    return current + timedelta(weeks=1)


# ---------------------------------------------------------------------------
# Scheduled report CRUD helpers (used by API)
# ---------------------------------------------------------------------------


def create_schedule(
    session: Session,
    *,
    template: str,
    cadence: str,
    scope: dict | None = None,
    options: dict | None = None,
    recipients: list[str] | None = None,
    created_by: str = "system",
) -> str:
    """Create a new report schedule.

    Args:
        session: Database session.
        template: Report template name.
        cadence: Recurrence cadence.
        scope: Report scope config.
        options: Report options.
        recipients: Email recipients.
        created_by: User who created the schedule.

    Returns:
        New schedule ID.
    """
    schedule_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    next_run = _compute_next_run(now, cadence)

    session.execute(
        scheduled_reports.insert().values(
            schedule_id=schedule_id,
            template=template,
            cadence=cadence,
            scope=scope,
            options=options,
            recipients=recipients,
            created_by=created_by,
            is_active=True,
            next_run_at=next_run,
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()
    return schedule_id


def list_schedules(session: Session, *, active_only: bool = True) -> list[dict]:
    """List report schedules.

    Args:
        session: Database session.
        active_only: If ``True``, only return active schedules.

    Returns:
        List of schedule dicts.
    """
    stmt = sa.select(scheduled_reports)
    if active_only:
        stmt = stmt.where(scheduled_reports.c.is_active.is_(True))
    stmt = stmt.order_by(scheduled_reports.c.next_run_at)

    rows = session.execute(stmt).fetchall()
    return [dict(row._mapping) for row in rows]


def deactivate_schedule(session: Session, schedule_id: str) -> bool:
    """Deactivate a report schedule.

    Args:
        session: Database session.
        schedule_id: Schedule to deactivate.

    Returns:
        ``True`` if the schedule was found and deactivated.
    """
    result = session.execute(
        scheduled_reports.update()
        .where(scheduled_reports.c.schedule_id == schedule_id)
        .values(is_active=False, updated_at=datetime.now(UTC))
    )
    session.commit()
    return result.rowcount > 0


def main() -> int:
    """Entry point for the scheduled reports job."""
    configure_job_logging()
    logger.info("Starting scheduled reports check")
    try:
        count = run_scheduled_reports()
        logger.info("Scheduled reports finished — %d triggered", count)
        return 0
    except Exception:
        logger.exception("Scheduled reports job failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
