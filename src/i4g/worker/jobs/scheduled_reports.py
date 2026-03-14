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
from pathlib import Path
from typing import Any

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

            updates: dict[str, Any] = {
                "last_run_at": now,
                "updated_at": now,
                "consecutive_failures": 0,
                "last_error": None,
            }
            if cadence == "once":
                updates["is_active"] = False
                updates["next_run_at"] = None
            else:
                updates["next_run_at"] = _compute_next_run(now, cadence)

            session.execute(
                scheduled_reports.update().where(scheduled_reports.c.schedule_id == schedule_id).values(**updates)
            )

        except Exception as exc:
            logger.exception("Failed to generate scheduled report %s", schedule_id)

            prev_failures = int(row.consecutive_failures or 0)
            new_failures = prev_failures + 1

            from i4g.settings import get_settings

            max_failures = get_settings().analytics.scheduled_report_max_consecutive_failures

            fail_updates: dict[str, Any] = {
                "last_run_at": now,
                "updated_at": now,
                "consecutive_failures": new_failures,
                "last_error": str(exc)[:500],
            }
            # Advance next_run_at so the schedule is not retried every pass
            if cadence != "once":
                fail_updates["next_run_at"] = _compute_next_run(now, cadence)
            else:
                fail_updates["is_active"] = False
                fail_updates["next_run_at"] = None

            if new_failures >= max_failures:
                logger.warning(
                    "Deactivating schedule %s after %d consecutive failures",
                    schedule_id,
                    new_failures,
                )
                fail_updates["is_active"] = False

            session.execute(
                scheduled_reports.update().where(scheduled_reports.c.schedule_id == schedule_id).values(**fail_updates)
            )

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
    from i4g.reports.generator import ReportGenerator
    from i4g.worker.tasks import generate_report_for_case

    report_path: Path | None = None
    review_id = scope.get("review_id")
    if review_id:
        task_result = generate_report_for_case(review_id=str(review_id))
        if not task_result.startswith("error:"):
            candidate = Path(task_result)
            if candidate.exists():
                report_path = candidate
    else:
        # Backward compatibility: ``range`` was used by UI before ``date_range``.
        text_query = scope.get("text_query") or scope.get("date_range") or scope.get("range")
        case_id = scope.get("case_id")
        report_result = ReportGenerator().generate_report(
            case_id=str(case_id) if case_id else None,
            text_query=str(text_query) if text_query else None,
        )
        raw_path = report_result.get("report_path")
        if raw_path:
            candidate = Path(raw_path)
            if candidate.exists():
                report_path = candidate

    if report_path is None:
        logger.warning(
            "Skipping email delivery; no generated report artifact found for template=%s scope=%s",
            template,
            scope,
        )
        return

    # Deliver only after generation confirms a local artifact.
    if recipients:
        from i4g.services.email_service import send_report_email

        send_report_email(
            recipients=recipients,
            subject=f"Scheduled Report: {template}",
            body=(f"Your scheduled {template} report has been generated.\n\n" f"Scope: {scope}\nOptions: {options}"),
            attachment_path=report_path,
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
    if cadence == "once":
        return current
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
            consecutive_failures=0,
            last_error=None,
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
