"""Alembic environment configuration for the i4g PII Vault."""

from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path
from typing import Any, Dict

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection

from i4g.settings import get_settings
from i4g.store.sql import VAULT_METADATA, build_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = VAULT_METADATA


def _resolve_database_url() -> str:
    """Determine the database URL used for migrations."""

    override = os.getenv("I4G_DATABASE_URL") or os.getenv("ALEMBIC_DATABASE_URL")
    if override:
        return override

    # Default to a local sqlite file for vault if not specified
    settings = get_settings()
    sqlite_path = Path(settings.storage.sqlite_path).parent / "vault.db"
    if not sqlite_path.is_absolute():
        sqlite_path = (Path(settings.project_root) / sqlite_path).resolve()
    normalized = sqlite_path.as_posix()
    return f"sqlite:///{normalized}"


def _prepare_config_section() -> Dict[str, Any]:
    """Update the Alembic config section with the resolved database URL."""

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _resolve_database_url()
    return section


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""

    section = _prepare_config_section()
    url = section["sqlalchemy.url"]
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"}
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using a SQLAlchemy engine."""

    # Check if a connection is already provided in the config attributes
    connectable = config.attributes.get("connection", None)

    if connectable is None:
        settings = get_settings()
        backend = settings.pii.backend

        if backend == "cloudsql":
            connection_details = {}
            if settings.pii.cloudsql_instance:
                connection_details["instance"] = settings.pii.cloudsql_instance
            if settings.pii.cloudsql_database:
                connection_details["database"] = settings.pii.cloudsql_database
            if settings.pii.cloudsql_user:
                connection_details["user"] = settings.pii.cloudsql_user
            if settings.pii.cloudsql_password:
                connection_details["password"] = settings.pii.cloudsql_password
            if settings.pii.cloudsql_enable_iam_auth:
                connection_details["enable_iam_auth"] = settings.pii.cloudsql_enable_iam_auth

            connectable = build_engine(
                backend_override="cloudsql",
                connection_details=connection_details,
            )
        else:
            section = _prepare_config_section()
            connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    if isinstance(connectable, Connection):
        context.configure(connection=connectable, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    else:
        with connectable.connect() as connection:  # type: ignore[assignment]
            context.configure(connection=connection, target_metadata=target_metadata)

            with context.begin_transaction():
                context.run_migrations()


def main() -> None:
    """Entrypoint used by Alembic to execute migrations."""

    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()


main()
