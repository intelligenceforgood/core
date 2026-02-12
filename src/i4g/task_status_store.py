"""Shared in-memory task status store used by API and worker helpers."""

from __future__ import annotations

TASK_STATUS: dict[str, dict[str, str]] = {}

__all__ = ["TASK_STATUS"]
