"""Tests for the dossier queue worker job."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from i4g.reports.dossier_queue_processor import QueueProcessSummary
from i4g.worker.jobs import dossier_queue


def _make_settings(batch_size: int = 5, dry_run: bool = False) -> SimpleNamespace:
    runtime = SimpleNamespace(log_level="CRITICAL")
    dossier_job = SimpleNamespace(batch_size=batch_size, dry_run=dry_run)
    return SimpleNamespace(runtime=runtime, dossier_job=dossier_job)


@dataclass
class _StubProcessor:
    processed: int
    completed: int
    failed: int

    def process_batch(self, *, batch_size: int, dry_run: bool, reporter=None):  # noqa: D401 - stub helper
        assert batch_size == self.processed
        _ = reporter
        summary = QueueProcessSummary(
            processed=self.processed,
            completed=self.completed,
            failed=self.failed,
            dry_run=dry_run,
            plans=[],
        )
        return summary


def test_run_job_delegates_to_processor() -> None:
    stub = _StubProcessor(processed=2, completed=2, failed=0)

    summary = dossier_queue.run_job(batch_size=2, dry_run=False, processor=stub)

    assert summary.completed == 2
    assert summary.failed == 0


def test_main_returns_error_code_when_failures(monkeypatch) -> None:
    stub = _StubProcessor(processed=1, completed=0, failed=1)

    monkeypatch.setattr(dossier_queue, "get_settings", lambda: _make_settings(batch_size=1, dry_run=False))
    monkeypatch.setattr(
        dossier_queue,
        "run_job",
        lambda batch_size, dry_run, reporter=None: stub.process_batch(
            batch_size=batch_size, dry_run=dry_run, reporter=reporter
        ),
    )

    exit_code = dossier_queue.main()

    assert exit_code == 1


def test_main_success(monkeypatch) -> None:
    stub = _StubProcessor(processed=1, completed=1, failed=0)

    monkeypatch.setattr(dossier_queue, "get_settings", lambda: _make_settings(batch_size=1, dry_run=True))
    monkeypatch.setattr(
        dossier_queue,
        "run_job",
        lambda batch_size, dry_run, reporter=None: stub.process_batch(
            batch_size=batch_size, dry_run=dry_run, reporter=reporter
        ),
    )

    exit_code = dossier_queue.main()

    assert exit_code == 0
