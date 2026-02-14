"""Unit tests for TaskStatusReporter progress event emission (F52)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from i4g.task_status import TaskStatusReporter


class StubObservability:
    """Captures events and metrics for test assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []
        self.increments: list[tuple[str, float, dict]] = []

    def emit_event(self, event: str, **fields) -> None:
        self.events.append((event, fields))

    def increment(self, metric: str, *, value: float = 1.0, tags: dict | None = None) -> None:
        self.increments.append((metric, value, tags or {}))


@pytest.fixture()
def stub_obs() -> StubObservability:
    return StubObservability()


@pytest.fixture()
def reporter(stub_obs: StubObservability) -> TaskStatusReporter:
    sink = MagicMock()
    r = TaskStatusReporter(task_id="test-task-1", sink=sink, _observability=stub_obs)
    return r


class TestTaskStatusProgressEvents:
    def test_update_emits_progress_event(self, reporter: TaskStatusReporter, stub_obs: StubObservability):
        """Each update() should emit a task.progress event."""
        reporter.update(status="started", message="Processing 5 reviews", total=5)

        progress_events = [e for e in stub_obs.events if e[0] == "task.progress"]
        assert len(progress_events) == 1
        payload = progress_events[0][1]
        assert payload["task_id"] == "test-task-1"
        assert payload["status"] == "started"
        assert payload["message"] == "Processing 5 reviews"
        assert payload["total"] == 5

    def test_update_emits_counter_metric(self, reporter: TaskStatusReporter, stub_obs: StubObservability):
        """Each update() should emit a task.status.update counter."""
        reporter.update(status="processing", message="Step 2")

        counter_metrics = [m for m in stub_obs.increments if m[0] == "task.status.update"]
        assert len(counter_metrics) == 1
        assert counter_metrics[0][2]["status"] == "processing"

    def test_multiple_updates_emit_multiple_events(self, reporter: TaskStatusReporter, stub_obs: StubObservability):
        """Sequential updates should each produce their own event."""
        reporter.update(status="started", message="Begin")
        reporter.update(status="processing", message="Step 1", progress=1, total=3)
        reporter.update(status="finished", message="Done", processed=3)

        progress_events = [e for e in stub_obs.events if e[0] == "task.progress"]
        assert len(progress_events) == 3
        statuses = [e[1]["status"] for e in progress_events]
        assert statuses == ["started", "processing", "finished"]

    def test_none_values_excluded_from_event(self, reporter: TaskStatusReporter, stub_obs: StubObservability):
        """None extra payload values should be filtered out."""
        reporter.update(status="started", message="Init", total=None)

        progress_events = [e for e in stub_obs.events if e[0] == "task.progress"]
        assert "total" not in progress_events[0][1]

    def test_no_task_id_skips_update(self, stub_obs: StubObservability):
        """Reporter without task_id should skip updates entirely."""
        r = TaskStatusReporter(task_id=None, _observability=stub_obs)
        r.update(status="started", message="Should not emit")

        assert len(stub_obs.events) == 0

    def test_update_still_writes_to_sink(self, reporter: TaskStatusReporter):
        """Sink should still receive the update alongside the event."""
        reporter.update(status="processing", message="Progress")
        assert reporter.sink.call_count == 1
        call_args = reporter.sink.call_args
        assert call_args[0][0] == "test-task-1"
        assert call_args[0][1]["status"] == "processing"
