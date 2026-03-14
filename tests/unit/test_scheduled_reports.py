"""Unit tests for scheduled reports cadence computation (S5-31 supplement)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

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


# ---------------------------------------------------------------------------
# Failure handling tests (S6-H11)
# ---------------------------------------------------------------------------


def _create_schedule_row(engine, *, schedule_id: str, cadence: str = "weekly", consecutive_failures: int = 0, **kw):
    """Insert a test schedule with failure tracking columns."""
    now = datetime.now(UTC)
    defaults = {
        "schedule_id": schedule_id,
        "template": "executive_summary",
        "cadence": cadence,
        "scope": {"date_range": "last_30_days"},
        "options": {},
        "recipients": ["analyst@example.com"],
        "created_by": "tester",
        "is_active": True,
        "next_run_at": now - timedelta(minutes=1),
        "consecutive_failures": consecutive_failures,
        "last_error": None,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(kw)
    with Session(engine) as session:
        session.execute(scheduled_reports.insert().values(**defaults))
        session.commit()


def test_failure_advances_last_run_at(monkeypatch) -> None:
    """On failure, last_run_at is still updated so the schedule is not retried every pass."""
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    scheduled_reports.create(engine)

    sid = "fail-0001-0001-0001-000000000001"
    _create_schedule_row(engine, schedule_id=sid)

    def _failing_trigger(**_):
        raise RuntimeError("Simulated failure")

    monkeypatch.setattr(scheduled_reports_job, "_trigger_report", _failing_trigger)

    # Mock get_settings to provide max_consecutive_failures
    class _MockAnalytics:
        scheduled_report_max_consecutive_failures = 3

    class _MockSettings:
        analytics = _MockAnalytics()

    with patch("i4g.settings.get_settings", return_value=_MockSettings()), Session(engine) as session:
        triggered = _process_due_schedules(session)

    assert triggered == 0

    with Session(engine) as session:
        row = session.execute(sa.select(scheduled_reports)).fetchone()
        assert row.last_run_at is not None
        assert row.consecutive_failures == 1
        assert row.last_error is not None
        assert "Simulated failure" in row.last_error
        assert row.is_active is True  # Still active after 1 failure


def test_deactivation_after_max_consecutive_failures(monkeypatch) -> None:
    """Schedule deactivates after reaching max consecutive failures."""
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    scheduled_reports.create(engine)

    sid = "fail-0002-0002-0002-000000000002"
    _create_schedule_row(engine, schedule_id=sid, consecutive_failures=2)

    def _failing_trigger(**_):
        raise RuntimeError("Third consecutive failure")

    monkeypatch.setattr(scheduled_reports_job, "_trigger_report", _failing_trigger)

    class _MockAnalytics:
        scheduled_report_max_consecutive_failures = 3

    class _MockSettings:
        analytics = _MockAnalytics()

    with patch("i4g.settings.get_settings", return_value=_MockSettings()), Session(engine) as session:
        triggered = _process_due_schedules(session)

    assert triggered == 0

    with Session(engine) as session:
        row = session.execute(sa.select(scheduled_reports)).fetchone()
        assert row.consecutive_failures == 3
        assert row.is_active is False  # Deactivated after 3 failures


def test_success_resets_consecutive_failures(monkeypatch) -> None:
    """A successful run resets consecutive_failures to 0."""
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    scheduled_reports.create(engine)

    sid = "succ-0003-0003-0003-000000000003"
    _create_schedule_row(engine, schedule_id=sid, consecutive_failures=2)

    monkeypatch.setattr(scheduled_reports_job, "_trigger_report", lambda **_: None)

    with Session(engine) as session:
        triggered = _process_due_schedules(session)

    assert triggered == 1

    with Session(engine) as session:
        row = session.execute(sa.select(scheduled_reports)).fetchone()
        assert row.consecutive_failures == 0
        assert row.last_error is None
        assert row.is_active is True
