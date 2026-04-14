"""CLI commands for the backfill framework.

Usage::

    i4g backfill status                    # Show pending work per task
    i4g backfill run classify              # Run a single task
    i4g backfill run all                   # Run all tasks once
    i4g backfill daemon                    # Continuous loop (local dev)
    i4g backfill daemon --tasks classify --tasks ssi --cycle 120
"""

from __future__ import annotations

import typer

backfill_app = typer.Typer(help="Backfill framework — manage and run reentrant batch processing tasks.")


@backfill_app.command("status", help="Show pending work counts for each backfill task.")
def backfill_status() -> None:
    from i4g.backfill.coordinator import get_status
    from i4g.backfill.status import get_active_locks

    rows = get_status()
    locks = get_active_locks()
    lock_index = {lock["task_name"] for lock in locks}

    typer.echo(f"{'Task':<20} {'Pending':>10}  {'Lock':>12}  Description")
    typer.echo("-" * 80)
    for row in rows:
        name = row["name"]
        pending = row["pending"]
        pending_str = str(pending) if pending >= 0 else "error"
        lock_str = "LOCKED" if name in lock_index else "-"
        typer.echo(f"{name:<20} {pending_str:>10}  {lock_str:>12}  {row['description']}")

    if locks:
        typer.echo("")
        typer.echo("Active locks:")
        for lock in locks:
            typer.echo(
                f"  {lock['task_name']}: holder={lock['holder_id']} "
                f"acquired={lock['acquired_at']} expires={lock['expires_at']}"
            )


@backfill_app.command("run", help="Run one or all backfill tasks.")
def backfill_run(
    task: str = typer.Argument(help="Task name or 'all' to run every registered task."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Pass dry_run to tasks that support it."),
    skip_lock: bool = typer.Option(False, "--skip-lock", help="Skip advisory lock (debug only)."),
    limit: int | None = typer.Option(None, "--limit", help="Limit for tasks that support it."),
) -> None:
    from i4g.backfill.coordinator import run_task
    from i4g.backfill.registry import all_tasks

    extra = {}
    if limit is not None:
        extra["limit"] = limit

    if task == "all":
        tasks = all_tasks()
        failures = 0
        for name in tasks:
            code = run_task(name, dry_run=dry_run, skip_lock=skip_lock, extra_kwargs=extra)
            if code not in (0, -1):
                failures += 1
        if failures:
            raise typer.Exit(1)
    else:
        code = run_task(task, dry_run=dry_run, skip_lock=skip_lock, extra_kwargs=extra)
        if code not in (0, -1):
            raise typer.Exit(code)


@backfill_app.command("daemon", help="Run backfill tasks in a continuous loop (launch-and-forget).")
def backfill_daemon(
    tasks: list[str] | None = typer.Option(None, "--tasks", help="Subset of task names (default: all)."),
    cycle: int = typer.Option(300, "--cycle", help="Seconds between cycles."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Pass dry_run to tasks that support it."),
) -> None:
    from i4g.backfill.coordinator import daemon

    daemon(tasks=tasks, cycle_interval=cycle, dry_run=dry_run)


@backfill_app.command("unlock", help="Force-release a stuck lock (admin).")
def backfill_unlock(
    task: str = typer.Argument(help="Task name to unlock."),
) -> None:
    import sqlalchemy as sa

    from i4g.store import sql as sql_schema
    from i4g.store.sql import session_factory as build_sql_session_factory

    sf = build_sql_session_factory()
    with sf() as session:
        result = session.execute(
            sa.delete(sql_schema.backfill_locks).where(sql_schema.backfill_locks.c.task_name == task)
        )
        session.commit()
        if result.rowcount:
            typer.echo(f"Lock '{task}' released.")
        else:
            typer.echo(f"No lock found for '{task}'.")
