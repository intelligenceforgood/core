"""Database administration CLI: migrations, permissions, and status checks for Cloud SQL."""

from __future__ import annotations

import shutil
import signal
import subprocess
import sys
import time
from enum import StrEnum
from typing import Annotated

import typer
from rich.console import Console

from i4g.settings import get_settings

console = Console()
db_app = typer.Typer(help="Cloud SQL database administration (migrations, permissions, status).")

# ---------------------------------------------------------------------------
# Environment definitions
# ---------------------------------------------------------------------------

_ENV_CONFIG = {
    "dev": {
        "app": {
            "project": "i4g-dev",
            "instance_connection": "i4g-dev:us-central1:i4g-dev-db",
            "database": "i4g_db",
            "port": 5432,
            "password_field": "dev_password",
            "service_accounts": [
                "sa-app@i4g-dev.iam",
                "sa-ingest@i4g-dev.iam",
                "sa-report@i4g-dev.iam",
                "sa-ssi@i4g-dev.iam",
            ],
            "admin_users": [
                "gcp-i4g-admin@intelligenceforgood.org",
                "jerry@intelligenceforgood.org",
            ],
            "alembic_config": "alembic.ini",
        },
    },
    "prod": {
        "app": {
            "project": "i4g-prod",
            "instance_connection": "i4g-prod:us-central1:i4g-prod-db",
            "database": "i4g_db",
            "port": 5434,
            "password_field": "prod_password",
            "service_accounts": [
                "sa-app@i4g-prod.iam",
                "sa-ingest@i4g-prod.iam",
                "sa-report@i4g-prod.iam",
                "sa-ssi@i4g-prod.iam",
            ],
            "admin_users": [
                "gcp-i4g-admin@intelligenceforgood.org",
                "jerry@intelligenceforgood.org",
            ],
            "alembic_config": "alembic.ini",
        },
    },
}


class Env(StrEnum):
    dev = "dev"
    prod = "prod"


def _get_db_config(env: Env) -> dict:
    """Return the database configuration dict for the given env."""
    return _ENV_CONFIG[env.value]["app"]


def _get_password(cfg: dict) -> str:
    """Resolve the postgres admin password from settings."""
    settings = get_settings()
    password = getattr(settings.db_admin, cfg["password_field"], None)
    if not password:
        console.print(
            f"[red]Error:[/red] Password not configured. "
            f"Set [bold]{cfg['password_field']}[/bold] in "
            f"[cyan]config/settings.local.toml[/cyan] under [db_admin], "
            f"or via env var [cyan]I4G_DB_ADMIN__{cfg['password_field'].upper()}[/cyan]."
        )
        raise typer.Exit(1)
    return password


def _build_database_url(cfg: dict, password: str) -> str:
    """Build a PostgreSQL connection URL for the cloud-sql-proxy local port."""
    from urllib.parse import quote_plus

    return f"postgresql+psycopg2://postgres:{quote_plus(password)}@127.0.0.1:{cfg['port']}/{cfg['database']}"


def _start_proxy(cfg: dict) -> subprocess.Popen:
    """Start cloud-sql-proxy as a background process and wait for it to be ready."""
    proxy_bin = shutil.which("cloud-sql-proxy") or shutil.which("cloud_sql_proxy")
    if not proxy_bin:
        console.print("[red]Error:[/red] cloud-sql-proxy not found on PATH. Install it first.")
        raise typer.Exit(1)

    proxy_arg = f"{cfg['instance_connection']}?port={cfg['port']}"
    console.print(f"[dim]Starting cloud-sql-proxy: {proxy_arg}[/dim]")

    proc = subprocess.Popen(
        [proxy_bin, proxy_arg],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for the proxy to be ready (listen on port)
    import socket

    for _attempt in range(30):
        time.sleep(1)
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            console.print(f"[red]cloud-sql-proxy exited unexpectedly:[/red]\n{stderr}")
            raise typer.Exit(1)
        try:
            with socket.create_connection(("127.0.0.1", cfg["port"]), timeout=1):
                break
        except OSError:
            continue
    else:
        proc.terminate()
        console.print(f"[red]Timeout waiting for cloud-sql-proxy on port {cfg['port']}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]cloud-sql-proxy ready on port {cfg['port']}[/green]")
    return proc


def _stop_proxy(proc: subprocess.Popen) -> None:
    """Gracefully stop the cloud-sql-proxy process."""
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    console.print("[dim]cloud-sql-proxy stopped[/dim]")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@db_app.command()
def migrate(
    env: Annotated[Env, typer.Argument(help="Target environment: dev or prod.")],
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print the command that would be executed without running it."
    ),
) -> None:
    """Run Alembic migrations against a Cloud SQL database via cloud-sql-proxy."""

    cfg = _get_db_config(env)
    password = _get_password(cfg)
    db_url = _build_database_url(cfg, password)
    target_label = f"app ({cfg['database']}@{cfg['project']})"

    alembic_cmd = [
        sys.executable,
        "-m",
        "alembic",
        "-c",
        cfg["alembic_config"],
        "upgrade",
        "head",
    ]

    if dry_run:
        console.print(f"[yellow]Dry run[/yellow] — would execute against {target_label}:")
        console.print(
            f"  ALEMBIC_DATABASE_URL=postgresql+psycopg2://postgres:****@127.0.0.1:{cfg['port']}/{cfg['database']}"
        )
        console.print(f"  {' '.join(alembic_cmd)}")
        return

    console.print(f"\n[bold]Migrating {target_label}[/bold]")

    proxy = _start_proxy(cfg)
    try:
        env_copy = {**__import__("os").environ, "ALEMBIC_DATABASE_URL": db_url}
        result = subprocess.run(alembic_cmd, env=env_copy, cwd=str(get_settings().project_root))
        if result.returncode != 0:
            console.print(f"[red]Alembic migration failed (exit {result.returncode})[/red]")
            raise typer.Exit(result.returncode)
        console.print(f"[green]Migration complete for {target_label}[/green]")
    finally:
        _stop_proxy(proxy)


@db_app.command("grant-permissions")
def grant_permissions(
    env: Annotated[Env, typer.Argument(help="Target environment: dev or prod.")],
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the SQL that would be executed without running it."),
) -> None:
    """Grant table/sequence/default permissions to service accounts and admin users."""

    cfg = _get_db_config(env)
    password = _get_password(cfg)
    target_label = f"app ({cfg['database']}@{cfg['project']})"

    all_principals = cfg["service_accounts"] + cfg["admin_users"]

    statements: list[str] = []
    for principal in all_principals:
        quoted = f'"{principal}"'
        statements.extend(
            [
                f"GRANT USAGE ON SCHEMA public TO {quoted};",
                f"GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO {quoted};",
                f"GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO {quoted};",
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {quoted};",
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO {quoted};",
            ]
        )

    full_sql = "\n".join(statements)

    if dry_run:
        console.print(f"[yellow]Dry run[/yellow] — SQL for {target_label}:\n")
        console.print(full_sql)
        return

    console.print(f"\n[bold]Granting permissions on {target_label}[/bold]")

    proxy = _start_proxy(cfg)
    try:
        import psycopg2

        conn = psycopg2.connect(
            host="127.0.0.1",
            port=cfg["port"],
            user="postgres",
            password=password,
            dbname=cfg["database"],
        )
        conn.autocommit = True
        cursor = conn.cursor()

        skipped: list[str] = []
        for principal in all_principals:
            quoted = f'"{principal}"'
            principal_stmts = [
                f"GRANT USAGE ON SCHEMA public TO {quoted};",
                f"GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO {quoted};",
                f"GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO {quoted};",
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {quoted};",
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO {quoted};",
            ]
            try:
                for stmt in principal_stmts:
                    console.print(f"  [dim]{stmt}[/dim]")
                    cursor.execute(stmt)
            except psycopg2.errors.UndefinedObject:
                console.print(f"  [yellow]⚠ Skipped {principal} — role does not exist on this instance[/yellow]")
                skipped.append(principal)

        cursor.close()
        conn.close()
        if skipped:
            console.print(
                f"[green]Permissions granted on {target_label}[/green] "
                f"([yellow]{len(skipped)} principal(s) skipped[/yellow])"
            )
        else:
            console.print(f"[green]Permissions granted on {target_label}[/green]")
    except ImportError:
        console.print("[red]Error:[/red] psycopg2 not installed. Run: pip install psycopg2-binary")
        raise typer.Exit(1) from None
    finally:
        _stop_proxy(proxy)


@db_app.command()
def status(
    env: Annotated[Env, typer.Argument(help="Target environment: dev or prod.")],
) -> None:
    """Show the current Alembic revision for a Cloud SQL database."""

    cfg = _get_db_config(env)
    password = _get_password(cfg)
    db_url = _build_database_url(cfg, password)
    target_label = f"app ({cfg['database']}@{cfg['project']})"

    console.print(f"\n[bold]Checking migration status for {target_label}[/bold]")

    alembic_cmd = [
        sys.executable,
        "-m",
        "alembic",
        "-c",
        cfg["alembic_config"],
        "current",
    ]

    proxy = _start_proxy(cfg)
    try:
        env_copy = {**__import__("os").environ, "ALEMBIC_DATABASE_URL": db_url}
        result = subprocess.run(alembic_cmd, env=env_copy, cwd=str(get_settings().project_root))
        if result.returncode != 0:
            console.print(f"[red]Failed to check status (exit {result.returncode})[/red]")
            raise typer.Exit(result.returncode)
    finally:
        _stop_proxy(proxy)
