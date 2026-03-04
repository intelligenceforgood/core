"""Lightweight helpers for emitting task-status updates across services.

The ``TaskStatusReporter`` writes to an in-memory dict today.  F52 adds
structured progress events (via ``Observability``) so that Cloud Logging
captures a queryable timeline of every task's lifecycle — this is the
stepping stone toward a Redis-backed store.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import requests

from i4g.observability import Observability, get_observability
from i4g.task_status_store import TASK_STATUS

LOGGER = logging.getLogger(__name__)


@dataclass
class TaskStatusReporter:
    """Reports task state changes to the API in-memory store or an HTTP endpoint."""

    task_id: str | None = None
    endpoint: str | None = None
    sink: Callable[[str, dict[str, Any]], None] | None = field(default=None, repr=False)
    _observability: Observability | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.task_id is None:
            self.task_id = os.getenv("I4G_TASK_ID")
        if self.endpoint is None:
            self.endpoint = os.getenv("I4G_TASK_STATUS_URL")
        if self._observability is None:
            try:
                self._observability = get_observability(component="task_status")
            except Exception:  # pragma: no cover - observability failures are non-fatal
                self._observability = None

    def is_enabled(self) -> bool:
        """Return ``True`` when a task identifier is available for updates."""

        return bool(self.task_id)

    def update(self, *, status: str, message: str, **payload: Any) -> None:
        """Publish a task-status update.

        Args:
            status: Short status string (e.g., ``processing``).
            message: Human-readable description of the update.
            **payload: Additional JSON-serializable fields.
        """

        if not self.task_id:
            LOGGER.debug("TaskStatusReporter skipped update (task_id missing): %s - %s", status, message)
            return

        body: dict[str, Any] = {"status": status, "message": message}
        body.update(payload)

        # F52: emit structured progress event for Cloud Logging queryability
        self._emit_progress_event(status=status, message=message, **payload)

        if self.sink:
            self.sink(self.task_id, body)
            return

        if self.endpoint:
            self._post_update(body)
            return

        if not self._update_local_store(body):
            LOGGER.debug("TaskStatusReporter could not locate a task store; dropping update: %s", json.dumps(body))

    def _emit_progress_event(self, *, status: str, message: str, **extra: Any) -> None:
        """Emit a structured log event for task progress (F52).

        These events are queryable in Cloud Logging and form the audit trail
        for background task lifecycle.  When Redis replaces the in-memory
        ``TASK_STATUS`` dict the same events will serve as the write-through
        cache-miss source.
        """
        if not self._observability:
            return
        try:
            self._observability.emit_event(
                "task.progress",
                task_id=self.task_id,
                status=status,
                message=message,
                **{k: v for k, v in extra.items() if v is not None},
            )
            self._observability.increment(
                "task.status.update",
                tags={"status": status, "task_id": self.task_id or "unknown"},
            )
        except Exception:  # pragma: no cover - observability is best-effort
            LOGGER.debug("Failed to emit task progress event", exc_info=True)

    def _post_update(self, body: dict[str, Any]) -> None:
        url = f"{self.endpoint.rstrip('/')}/{self.task_id}/update"
        try:
            response = requests.post(url, json=body, timeout=5)
            response.raise_for_status()
        except Exception as exc:  # pragma: no cover - network/HTTP errors
            LOGGER.warning("Task status POST failed (%s): %s", url, exc)

    def _update_local_store(self, body: dict[str, Any]) -> bool:
        TASK_STATUS[self.task_id] = body
        return True


__all__ = ["TaskStatusReporter"]
