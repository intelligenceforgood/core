"""Backfill coordinator — runs tasks with advisory locking and logging.

The coordinator is the main execution engine.  It:
1. Acquires a database-backed lock for the task
2. Runs the task's ``run_fn``
3. Releases the lock on completion (or crash)
4. Logs structured progress and outcomes

For local development, the *daemon* mode cycles through all registered
tasks in a loop with configurable intervals.
"""

from __future__ import annotations

import logging
import signal
import time
from datetime import UTC, datetime
from typing import Any

from i4g.backfill.lock import task_lock
from i4g.backfill.registry import BackfillTask, all_tasks, get_task
from i4g.settings import get_settings
from i4g.store.sql import session_factory as build_sql_session_factory
from i4g.worker.logging import configure_job_logging

logger = logging.getLogger(__name__)


def _ensure_backfill_table(sf: Any) -> None:
    """Create the backfill_locks table if it does not exist (auto-bootstrap for local)."""
    from i4g.store import sql as sql_schema

    try:
        engine = sf.kw.get("bind") or sf().get_bind()
        sql_schema.backfill_locks.create(engine, checkfirst=True)
    except Exception:
        logger.debug("Could not auto-create backfill_locks table", exc_info=True)


def run_task(
    task_name: str,
    *,
    dry_run: bool = False,
    skip_lock: bool = False,
    extra_kwargs: dict[str, Any] | None = None,
) -> int:
    """Run a single backfill task with optional locking.

    Args:
        task_name: Registered task name (e.g. ``'classify'``, ``'ssi'``).
        dry_run: Passed through to the task's ``run_fn`` if supported.
        skip_lock: Skip advisory lock (useful for local debugging).
        extra_kwargs: Additional keyword arguments merged with defaults.

    Returns:
        0 on success, non-zero on failure, -1 if lock contention.
    """
    settings = get_settings()
    configure_job_logging(settings)

    task = get_task(task_name)
    kwargs = {**task.default_kwargs, **(extra_kwargs or {})}
    if dry_run:
        kwargs["dry_run"] = True

    logger.info(
        "backfill[%s]: starting (dry_run=%s, skip_lock=%s, kwargs=%s)",
        task_name,
        dry_run,
        skip_lock,
        kwargs,
    )

    if skip_lock:
        return _execute_task(task, kwargs)

    sf = build_sql_session_factory()
    _ensure_backfill_table(sf)
    with task_lock(task_name, sf, ttl_seconds=task.lock_ttl_seconds) as holder:
        if holder is None:
            logger.info("backfill[%s]: lock contention — another instance is running", task_name)
            return -1
        return _execute_task(task, kwargs)


def _execute_task(task: BackfillTask, kwargs: dict[str, Any]) -> int:
    """Execute a task and log the outcome."""
    start = time.monotonic()
    try:
        code = task.run_fn(**kwargs) or 0
        elapsed = time.monotonic() - start
        logger.info(
            "backfill[%s]: completed in %.1fs (exit_code=%d)",
            task.name,
            elapsed,
            code,
        )
        return code
    except Exception:
        elapsed = time.monotonic() - start
        logger.exception("backfill[%s]: failed after %.1fs", task.name, elapsed)
        return 1


def get_status(task_names: list[str] | None = None) -> list[dict[str, Any]]:
    """Query the pending-work count for each task.

    Returns a list of dicts with ``name``, ``description``, ``pending``.
    """
    sf = build_sql_session_factory()
    _ensure_backfill_table(sf)
    tasks = all_tasks()
    if task_names:
        tasks = {k: v for k, v in tasks.items() if k in task_names}

    results = []
    with sf() as session:
        for name, task in tasks.items():
            try:
                pending = task.pending_count_fn(session)
            except Exception:
                logger.debug("Failed to query pending count for %s", name, exc_info=True)
                pending = -1
            results.append(
                {
                    "name": name,
                    "description": task.description,
                    "pending": pending,
                }
            )
    return results


def daemon(
    *,
    tasks: list[str] | None = None,
    cycle_interval: int = 300,
    dry_run: bool = False,
) -> None:
    """Run all (or selected) backfill tasks in a continuous loop.

    This is the "launch and forget" mode for local development.
    The daemon cycles through tasks, running each that has pending work.
    Between cycles it sleeps for ``cycle_interval`` seconds.

    Handles SIGINT/SIGTERM for graceful shutdown.

    Args:
        tasks: Subset of task names to run.  ``None`` = all.
        cycle_interval: Seconds between full cycles.
        dry_run: Pass dry_run to tasks that support it.
    """
    settings = get_settings()
    configure_job_logging(settings)

    shutdown = False

    def _handle_signal(signum: int, _frame: Any) -> None:
        nonlocal shutdown
        sig_name = signal.Signals(signum).name
        logger.info("backfill-daemon: received %s — shutting down after current task", sig_name)
        shutdown = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    all_task_names = list(all_tasks().keys())
    run_tasks = tasks or all_task_names
    # Validate
    for name in run_tasks:
        get_task(name)  # raises KeyError if invalid

    logger.info(
        "backfill-daemon: starting (tasks=%s, cycle=%ds, dry_run=%s)",
        run_tasks,
        cycle_interval,
        dry_run,
    )

    cycle = 0
    while not shutdown:
        cycle += 1
        cycle_start = time.monotonic()
        logger.info("backfill-daemon: === cycle %d started at %s ===", cycle, datetime.now(UTC).isoformat())

        # Check what has pending work
        status = get_status(run_tasks)
        tasks_with_work = [s for s in status if s["pending"] > 0]

        if not tasks_with_work:
            logger.info("backfill-daemon: no pending work — sleeping %ds", cycle_interval)
        else:
            logger.info(
                "backfill-daemon: %d tasks with pending work: %s",
                len(tasks_with_work),
                [(s["name"], s["pending"]) for s in tasks_with_work],
            )

            for task_status in tasks_with_work:
                if shutdown:
                    break
                name = task_status["name"]
                logger.info("backfill-daemon: running '%s' (%d pending)", name, task_status["pending"])
                code = run_task(name, dry_run=dry_run)
                if code == -1:
                    logger.info("backfill-daemon: '%s' skipped (lock contention)", name)
                elif code != 0:
                    logger.warning("backfill-daemon: '%s' exited with code %d", name, code)

        cycle_elapsed = time.monotonic() - cycle_start
        logger.info("backfill-daemon: cycle %d completed in %.1fs", cycle, cycle_elapsed)

        if not shutdown:
            logger.info("backfill-daemon: sleeping %ds until next cycle", cycle_interval)
            # Sleep in small increments to allow signal handling
            for _ in range(cycle_interval):
                if shutdown:
                    break
                time.sleep(1)

    logger.info("backfill-daemon: shutdown complete")
