"""Shared logging configuration for Cloud Run worker jobs.

All worker job entry points should call :func:`configure_job_logging` at
startup rather than defining their own ``_configure_logging`` helper.
"""

from __future__ import annotations

import logging

from i4g.settings import Settings, get_settings


def configure_job_logging(settings: Settings | None = None) -> None:
    """Configure root logging using the ``runtime.log_level`` setting.

    Args:
        settings: Resolved settings instance.  When ``None`` the global
            :func:`~i4g.settings.get_settings` value is used.
    """
    resolved = settings or get_settings()
    level_name = resolved.runtime.log_level.upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
