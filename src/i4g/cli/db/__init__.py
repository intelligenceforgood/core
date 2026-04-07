"""Database administration CLI: migrations, permissions, status, wipe, backup, and restore."""

from __future__ import annotations

import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from i4g.settings import get_settings

console = Console()
db_app = typer.Typer(help="Cloud SQL database administration (migrations, permissions, status, wipe, backup, restore).")

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


# ---------------------------------------------------------------------------
# Tables to truncate during wipe (FK-safe dependency order, leaf → root).
# Preserved: accounts, account_actions, alembic_version.
# ---------------------------------------------------------------------------

_WIPE_TABLE_ORDER: list[str] = [
    "watchlist_alerts",
    "watchlist_items",
    "partner_feed_audit",
    "partner_api_keys",
    "chart_share_tokens",
    "scheduled_reports",
    "annotations",
    "campaign_stats",
    "threat_campaign_cases",
    "threat_campaigns",
    "platform_kpis",
    "entity_stats",
    "indicator_stats",
    "infrastructure_edges",
    "ssi_guidance_commands",
    "ssi_events",
    "pii_exposures",
    "agent_sessions",
    "harvested_wallets",
    "case_investigations",
    "site_scans",
    "intake_indicator_links",
    "intake_jobs",
    "intake_attachments",
    "intake_records",
    "review_actions",
    "review_queue",
    "saved_searches",
    "indicator_sources",
    "indicators",
    "entity_mentions",
    "entities",
    "source_documents",
    "dossier_queue",
    "ingestion_retry_queue",
    "scam_records",
    "cases",
    "engagements",
    "campaigns",
    "ingestion_runs",
    "audit_log",
    "backfill_locks",
]


class WipeEnv(StrEnum):
    local = "local"
    dev = "dev"


@db_app.command()
def wipe(
    env: Annotated[WipeEnv, typer.Argument(help="Target environment: local or dev.")],
    confirm: str = typer.Option("", "--confirm", help="Safety flag. For dev, pass 'yes-wipe-dev' to proceed."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print actions without executing them."),
) -> None:
    """Wipe all user-data tables, preserving schema, migrations, and accounts."""

    if env == WipeEnv.local:
        _wipe_local(dry_run=dry_run)
    elif env == WipeEnv.dev:
        if confirm != "yes-wipe-dev":
            console.print(
                "[red]Refusing to wipe dev without safety flag.[/red]\n"
                "Pass [bold]--confirm 'yes-wipe-dev'[/bold] to proceed."
            )
            raise typer.Exit(1)
        _wipe_dev(dry_run=dry_run)


def _wipe_local(*, dry_run: bool) -> None:
    """Delete local SQLite DB, Chroma dir, and generated artifacts."""

    settings = get_settings()
    project_root = settings.project_root
    data_dir = Path(project_root) / "data"
    sqlite_db = data_dir / "i4g_store.db"
    chroma_dir = data_dir / "chroma_store"
    reports_dir = data_dir / "reports"
    manual_demo_dir = data_dir / "manual_demo"

    targets = [
        ("SQLite DB", sqlite_db),
        ("Chroma store", chroma_dir),
        ("Reports", reports_dir),
        ("Manual demo", manual_demo_dir),
    ]

    if dry_run:
        console.print("[yellow]Dry run[/yellow] — would delete:")
        for label, path in targets:
            status = "exists" if path.exists() else "not found"
            console.print(f"  {label}: {path} ({status})")
        return

    for label, path in targets:
        if path.is_file():
            path.unlink()
            console.print(f"  Deleted {label}: {path}")
        elif path.is_dir():
            shutil.rmtree(path)
            console.print(f"  Deleted {label}: {path}")
        else:
            console.print(f"  {label}: {path} (not found, skipping)")

    console.print("[green]Local wipe complete.[/green] Run `i4g bootstrap local reset` to repopulate.")


def _wipe_dev(*, dry_run: bool) -> None:
    """Connect to Cloud SQL and TRUNCATE all user-data tables."""

    cfg = _get_db_config(Env.dev)
    password = _get_password(cfg)
    target_label = f"app ({cfg['database']}@{cfg['project']})"

    if dry_run:
        console.print(f"[yellow]Dry run[/yellow] — would TRUNCATE {len(_WIPE_TABLE_ORDER)} tables on {target_label}:")
        for t in _WIPE_TABLE_ORDER:
            console.print(f"  TRUNCATE TABLE {t} CASCADE;")
        return

    console.print(f"\n[bold]Wiping {target_label} ({len(_WIPE_TABLE_ORDER)} tables)[/bold]")

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

        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        existing_tables = {row[0] for row in cursor.fetchall()}

        for table in _WIPE_TABLE_ORDER:
            if table not in existing_tables:
                console.print(f"  [dim]SKIP {table} (table does not exist)[/dim]")
                continue
            console.print(f"  TRUNCATE TABLE {table} CASCADE;")
            cursor.execute(f"TRUNCATE TABLE {table} CASCADE;")  # noqa: S608 — table names from static list

        cursor.close()
        conn.close()
        console.print(f"[green]Wipe complete on {target_label}.[/green]")
    except ImportError:
        console.print("[red]Error:[/red] psycopg2 not installed. Run: pip install psycopg2-binary")
        raise typer.Exit(1) from None
    finally:
        _stop_proxy(proxy)


@db_app.command()
def backup(
    env: Annotated[WipeEnv, typer.Argument(help="Target environment: local or dev.")],
    output: Path = typer.Option(None, "--output", help="Output path for the backup archive."),
) -> None:
    """Create a backup of the platform database."""

    if env == WipeEnv.local:
        _backup_local(output=output)
    elif env == WipeEnv.dev:
        _backup_dev(output=output)


def _backup_local(*, output: Path | None) -> None:
    """Copy SQLite file + Chroma dir to a timestamped tar.gz archive."""

    settings = get_settings()
    project_root = Path(settings.project_root)
    data_dir = project_root / "data"
    sqlite_db = data_dir / "i4g_store.db"
    chroma_dir = data_dir / "chroma_store"
    backups_dir = data_dir / "backups"

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive_path = output or (backups_dir / f"backup_local_{ts}.tar.gz")
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    sources: list[tuple[str, Path]] = []
    if sqlite_db.exists():
        sources.append(("i4g_store.db", sqlite_db))
    if chroma_dir.exists():
        sources.append(("chroma_store", chroma_dir))

    if not sources:
        console.print("[yellow]Nothing to backup — no SQLite DB or Chroma store found.[/yellow]")
        return

    with tarfile.open(archive_path, "w:gz") as tar:
        for arcname, path in sources:
            tar.add(path, arcname=arcname)

    size_mb = archive_path.stat().st_size / (1024 * 1024)
    console.print(f"[green]Backup saved:[/green] {archive_path} ({size_mb:.1f} MB)")


def _backup_dev(*, output: Path | None) -> None:
    """Export Cloud SQL database via pg_dump through cloud-sql-proxy."""

    cfg = _get_db_config(Env.dev)
    password = _get_password(cfg)
    target_label = f"app ({cfg['database']}@{cfg['project']})"

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dump_path = output or Path(f"dump_dev_{ts}.sql.gz")
    dump_path.parent.mkdir(parents=True, exist_ok=True)

    console.print(f"\n[bold]Backing up {target_label}[/bold]")

    proxy = _start_proxy(cfg)
    try:
        import gzip

        pg_dump_bin = shutil.which("pg_dump")
        if not pg_dump_bin:
            console.print("[red]Error:[/red] pg_dump not found on PATH.")
            raise typer.Exit(1)

        pg_dump_cmd = [
            pg_dump_bin,
            "-h",
            "127.0.0.1",
            "-p",
            str(cfg["port"]),
            "-U",
            "postgres",
            "-d",
            cfg["database"],
            "--no-owner",
            "--no-acl",
        ]

        env_copy = {**__import__("os").environ, "PGPASSWORD": password}
        result = subprocess.run(pg_dump_cmd, env=env_copy, capture_output=True)
        if result.returncode != 0:
            console.print(f"[red]pg_dump failed:[/red]\n{result.stderr.decode()}")
            raise typer.Exit(result.returncode)

        with gzip.open(dump_path, "wb") as f:
            f.write(result.stdout)

        size_mb = dump_path.stat().st_size / (1024 * 1024)
        console.print(f"[green]Backup saved:[/green] {dump_path} ({size_mb:.1f} MB)")

        # Optionally upload to GCS
        gcs_uri = f"gs://i4g-dev-data-bundles/backups/{ts}/dump.sql.gz"
        console.print(f"[dim]To upload: gcloud storage cp {dump_path} {gcs_uri}[/dim]")
    finally:
        _stop_proxy(proxy)


@db_app.command()
def restore(
    env: Annotated[WipeEnv, typer.Argument(help="Target environment: local or dev.")],
    source: str = typer.Option(..., "--from", help="Path to backup archive (local tar.gz or GCS URI gs://...)."),
    confirm: str = typer.Option("", "--confirm", help="Safety flag. For dev, pass 'yes-restore-dev'."),
) -> None:
    """Restore the platform database from a backup."""

    if source.startswith("gs://"):
        if env == WipeEnv.local:
            console.print("[red]GCS URIs are not supported for local restore. Provide a local path.[/red]")
            raise typer.Exit(1)
    else:
        if not Path(source).exists():
            console.print(f"[red]Backup not found:[/red] {source}")
            raise typer.Exit(1)

    if env == WipeEnv.local:
        _restore_local(source=Path(source))
    elif env == WipeEnv.dev:
        if confirm != "yes-restore-dev":
            console.print(
                "[red]Refusing to restore dev without safety flag.[/red]\n"
                "Pass [bold]--confirm 'yes-restore-dev'[/bold] to proceed."
            )
            raise typer.Exit(1)
        _restore_dev(source=source)


def _get_alembic_head() -> str | None:
    """Return the current Alembic HEAD revision from the migration scripts."""
    alembic_cmd = [
        sys.executable,
        "-m",
        "alembic",
        "-c",
        "alembic.ini",
        "heads",
    ]
    result = subprocess.run(
        alembic_cmd,
        capture_output=True,
        text=True,
        cwd=str(get_settings().project_root),
    )
    if result.returncode != 0:
        return None
    # Output format: "20260321_02 (head)"
    for line in result.stdout.strip().splitlines():
        if "(head)" in line:
            return line.split()[0].strip()
    return None


def _validate_alembic_local(data_dir: Path) -> None:
    """Check that the restored SQLite DB has an Alembic revision matching the current HEAD."""
    import sqlite3

    db_path = data_dir / "i4g_store.db"
    if not db_path.exists():
        return

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT version_num FROM alembic_version LIMIT 1")
        row = cursor.fetchone()
        conn.close()
    except Exception:
        console.print("[yellow]⚠ Could not read alembic_version from restored DB — skipping revision check.[/yellow]")
        return

    if not row:
        console.print("[yellow]⚠ No Alembic revision found in restored DB.[/yellow]")
        return

    backup_rev = row[0]
    head_rev = _get_alembic_head()
    if head_rev and backup_rev != head_rev:
        console.print(
            f"[yellow]⚠ Alembic revision mismatch:[/yellow] "
            f"backup has [bold]{backup_rev}[/bold], current HEAD is [bold]{head_rev}[/bold].\n"
            f"  Run [cyan]alembic upgrade head[/cyan] to migrate the restored database."
        )
    elif head_rev:
        console.print(f"[green]Alembic revision OK:[/green] {backup_rev}")


def _validate_alembic_dev(cfg: dict, password: str) -> None:
    """Check that the restored Cloud SQL DB has an Alembic revision matching the current HEAD."""
    try:
        import psycopg2

        conn = psycopg2.connect(
            host="127.0.0.1",
            port=cfg["port"],
            user="postgres",
            password=password,
            dbname=cfg["database"],
        )
        cursor = conn.cursor()
        cursor.execute("SELECT version_num FROM alembic_version LIMIT 1")
        row = cursor.fetchone()
        cursor.close()
        conn.close()
    except Exception:
        console.print("[yellow]⚠ Could not read alembic_version from restored DB — skipping revision check.[/yellow]")
        return

    if not row:
        console.print("[yellow]⚠ No Alembic revision found in restored DB.[/yellow]")
        return

    backup_rev = row[0]
    head_rev = _get_alembic_head()
    if head_rev and backup_rev != head_rev:
        console.print(
            f"[yellow]⚠ Alembic revision mismatch:[/yellow] "
            f"backup has [bold]{backup_rev}[/bold], current HEAD is [bold]{head_rev}[/bold].\n"
            f"  Run [cyan]i4g db migrate {cfg.get('env_name', 'dev')}[/cyan] to upgrade."
        )
    elif head_rev:
        console.print(f"[green]Alembic revision OK:[/green] {backup_rev}")


def _restore_local(*, source: Path) -> None:
    """Wipe current local DB and extract backup archive."""

    settings = get_settings()
    project_root = Path(settings.project_root)
    data_dir = project_root / "data"

    console.print(f"[bold]Restoring local database from {source}[/bold]")

    # Wipe first
    _wipe_local(dry_run=False)

    # Extract archive
    with tarfile.open(source, "r:gz") as tar:
        tar.extractall(path=data_dir)  # noqa: S202 — trusted backup archive from known backup command

    # Validate Alembic revision after restore.
    _validate_alembic_local(data_dir)

    console.print("[green]Local restore complete.[/green]")


def _restore_dev(*, source: str | Path) -> None:
    """Wipe dev DB and restore from pg_dump archive."""

    cfg = _get_db_config(Env.dev)
    password = _get_password(cfg)
    target_label = f"app ({cfg['database']}@{cfg['project']})"

    console.print(f"\n[bold]Restoring {target_label} from {source}[/bold]")

    # Wipe first
    _wipe_dev(dry_run=False)

    proxy = _start_proxy(cfg)
    _tmp_path: str | None = None
    try:
        import gzip

        psql_bin = shutil.which("psql")
        if not psql_bin:
            console.print("[red]Error:[/red] psql not found on PATH.")
            raise typer.Exit(1)

        source_str = str(source)
        if source_str.startswith("gs://"):
            console.print(f"[dim]Downloading {source_str} ...[/dim]")
            with tempfile.NamedTemporaryFile(suffix=".sql.gz", delete=False) as _tmpf:
                _tmp_path = _tmpf.name
            dl = subprocess.run(
                ["gcloud", "storage", "cp", source_str, _tmp_path],
                capture_output=True,
                text=True,
            )
            if dl.returncode != 0:
                console.print(f"[red]Download failed:[/red]\n{dl.stderr}")
                raise typer.Exit(dl.returncode)
            local_source: Path = Path(_tmp_path)
        else:
            local_source = Path(source)

        with gzip.open(local_source, "rb") as f:
            sql_content = f.read()

        # Clear alembic_version before loading the dump so the dump's revision
        # is the only row.  _wipe_dev intentionally preserves alembic_version,
        # which would leave the pre-restore revision alongside the one in the
        # dump and cause "overlaps" errors on the next `alembic upgrade head`.
        import psycopg2

        _conn = psycopg2.connect(
            host="127.0.0.1",
            port=cfg["port"],
            user="postgres",
            password=password,
            dbname=cfg["database"],
        )
        _conn.autocommit = True
        _cur = _conn.cursor()
        _cur.execute("TRUNCATE TABLE alembic_version;")
        _cur.close()
        _conn.close()

        psql_cmd = [
            psql_bin,
            "-h",
            "127.0.0.1",
            "-p",
            str(cfg["port"]),
            "-U",
            "postgres",
            "-d",
            cfg["database"],
        ]

        env_copy = {**__import__("os").environ, "PGPASSWORD": password}
        result = subprocess.run(psql_cmd, input=sql_content, env=env_copy, capture_output=True)
        if result.returncode != 0:
            console.print(f"[red]Restore failed:[/red]\n{result.stderr.decode()}")
            raise typer.Exit(result.returncode)

        # Validate Alembic revision after restore.
        _validate_alembic_dev(cfg, password)

        console.print(f"[green]Restore complete on {target_label}.[/green]")
    finally:
        _stop_proxy(proxy)
        if _tmp_path is not None:
            Path(_tmp_path).unlink(missing_ok=True)
