"""Unit tests for scheduled reports cadence computation (S5-31 supplement)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session

from i4g.store.sql import scheduled_reports
from i4g.worker.jobs import scheduled_reports as scheduled_reports_job
from i4g.worker.jobs.scheduled_reports import _compute_next_run, _process_due_schedules, _trigger_report


def test_weekly_cadence() -> None:
    """Weekly cadence advances by 7 days."""
    now = datetime(2025, 1, 1, tzinfo=UTC)
    result = _compute_next_run(now, "weekly")
    assert result == now + timedelta(weeks=1)


def test_monthly_cadence() -> None:
    """Monthly cadence advances by ~30 days."""
    now = datetime(2025, 1, 15, tzinfo=UTC)
    result = _compute_next_run(now, "monthly")
    assert result == now + timedelta(days=30)


def test_daily_cadence() -> None:
    """Daily cadence advances by 1 day."""
    now = datetime(2025, 6, 15, tzinfo=UTC)
    result = _compute_next_run(now, "daily")
    assert result == now + timedelta(days=1)


def test_unknown_cadence_defaults_weekly() -> None:
    """Unknown cadence defaults to weekly interval."""
    now = datetime(2025, 3, 1, tzinfo=UTC)
    result = _compute_next_run(now, "quarterly")
    assert result == now + timedelta(weeks=1)


def test_once_cadence_returns_current() -> None:
    """Once cadence should not schedule a future recurring run."""
    now = datetime(2025, 3, 1, tzinfo=UTC)
    result = _compute_next_run(now, "once")
    assert result == now


def test_process_due_schedules_deactivates_once_schedule(monkeypatch) -> None:
    """One-time schedules deactivate after first execution."""
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    scheduled_reports.create(engine)

    now = datetime.now(UTC)
    with Session(engine) as session:
        session.execute(
            scheduled_reports.insert().values(
                schedule_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                template="executive_summary",
                cadence="once",
                scope={"date_range": "last_30_days"},
                options={},
                recipients=["analyst@example.com"],
                created_by="tester",
                is_active=True,
                next_run_at=now - timedelta(minutes=1),
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

        monkeypatch.setattr(
            scheduled_reports_job,
            "_trigger_report",
            lambda **_: None,
        )

        triggered = _process_due_schedules(session)
        assert triggered == 1

        row = session.execute(sa.select(scheduled_reports)).fetchone()
        assert row is not None
        assert row.is_active is False
        assert row.next_run_at is None


def test_trigger_report_skips_email_when_no_artifact(monkeypatch) -> None:
    """Email delivery is skipped when report generation fails."""
    send_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        "i4g.worker.tasks.generate_report_for_case",
        lambda review_id: "error:not_found",
    )
    monkeypatch.setattr(
        "i4g.services.email_service.send_report_email",
        lambda **kwargs: send_calls.append(kwargs),
    )

    _trigger_report(
        template="executive_summary",
        scope={"review_id": "review-123"},
        options={"tlp": "TLP:AMBER"},
        recipients=["analyst@example.com"],
    )

    assert send_calls == []


def test_trigger_report_sends_email_with_generated_artifact(tmp_path, monkeypatch) -> None:
    """Email delivery includes attachment only after successful generation."""
    artifact = tmp_path / "scheduled-report.md"
    artifact.write_text("report body")

    send_calls: list[dict[str, object]] = []

    class _StubGenerator:
        def generate_report(self, case_id=None, text_query=None):
            assert case_id is None
            assert text_query == "last_30_days"
            return {"report_path": str(artifact)}

    monkeypatch.setattr("i4g.reports.generator.ReportGenerator", _StubGenerator)
    monkeypatch.setattr(
        "i4g.services.email_service.send_report_email",
        lambda **kwargs: send_calls.append(kwargs),
    )

    _trigger_report(
        template="executive_summary",
        scope={"date_range": "last_30_days"},
        options={"tlp": "TLP:AMBER"},
        recipients=["analyst@example.com"],
    )

    assert len(send_calls) == 1
    assert send_calls[0]["attachment_path"] == Path(artifact)
