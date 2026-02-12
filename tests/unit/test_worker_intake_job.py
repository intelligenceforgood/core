"""Unit tests for the intake Cloud Run job entrypoint."""

from __future__ import annotations

from types import SimpleNamespace

from i4g.worker.jobs import intake as intake_job


def _reset_env(monkeypatch):
    for key in ["I4G_INTAKE__ID", "I4G_INTAKE__JOB_ID", "I4G_INTAKE__API_BASE", "I4G_INTAKE__API_KEY", "I4G_API__KEY"]:
        monkeypatch.delenv(key, raising=False)


def _mock_settings(
    intake_id=None, job_id=None, api_base=None, api_key=None, api_global_key="dev-analyst-token",
) -> SimpleNamespace:
    return SimpleNamespace(
        env="local",
        runtime=SimpleNamespace(log_level="INFO"),
        api=SimpleNamespace(key=api_global_key),
        intake=SimpleNamespace(
            id=intake_id,
            job_id=job_id,
            api_base=api_base,
            api_key=api_key,
        ),
    )


def test_main_uses_api_when_configured(monkeypatch):
    _reset_env(monkeypatch)

    settings = _mock_settings(
        intake_id="intake-123",
        job_id="job-123",
        api_base="https://example.test/api/intakes",
        api_key="secret",
    )
    monkeypatch.setattr(intake_job, "get_settings", lambda: settings)

    calls = SimpleNamespace(called=False, args=None)

    def fake_process(intake_id, job_id, api_base, api_key):
        calls.called = True
        calls.args = (intake_id, job_id, api_base, api_key)
        return 0

    monkeypatch.setattr(intake_job, "_process_via_api", fake_process)

    assert intake_job.main() == 0
    assert calls.called is True
    assert calls.args == ("intake-123", "job-123", "https://example.test/api/intakes", "secret")


def test_main_processes_locally_without_api(monkeypatch):
    _reset_env(monkeypatch)

    settings = _mock_settings(intake_id="intake-456", job_id="job-456")
    monkeypatch.setattr(intake_job, "get_settings", lambda: settings)

    processed = SimpleNamespace(called=False, args=None)

    class DummyService:
        def process_job(self, intake_id, job_id):
            processed.called = True
            processed.args = (intake_id, job_id)

    monkeypatch.setattr(intake_job, "IntakeService", lambda: DummyService())

    assert intake_job.main() == 0
    assert processed.called is True
    assert processed.args == ("intake-456", "job-456")
