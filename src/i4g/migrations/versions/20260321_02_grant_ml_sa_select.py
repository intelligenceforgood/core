"""Grant SELECT on ML-relevant tables to the ML platform service account.

The ML ETL pipeline (sa-ml-platform@i4g-ml) reads from core Cloud SQL
tables to sync data into BigQuery.  This migration grants read access
idempotently — if the IAM database user does not exist yet (e.g. prod
before ML is enabled), the GRANT is skipped silently.

Revision ID: 20260321_02
Revises: 20260321_01
Create Date: 2026-03-21

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "20260321_02"
down_revision: str | None = "20260321_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ML_SA_ROLE = "sa-ml-platform@i4g-ml.iam"
TABLES = ["cases", "entities", "analyst_labels"]


def upgrade() -> None:
    """Grant SELECT on ML-relevant tables to the ML service account."""
    conn = op.get_bind()

    # This migration is PostgreSQL-only; skip on SQLite.
    if conn.dialect.name != "postgresql":
        return

    # Check if the IAM database user exists (created by Terraform).
    # If it doesn't exist yet, skip — the GRANT will be applied on next
    # migration run after Terraform creates the user.
    result = conn.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :role"),
        {"role": ML_SA_ROLE},
    )
    if result.fetchone() is None:
        return

    table_list = ", ".join(TABLES)
    conn.execute(text(f'GRANT SELECT ON TABLE {table_list} TO "{ML_SA_ROLE}"'))  # noqa: S608


def downgrade() -> None:
    """Revoke SELECT from the ML service account."""
    conn = op.get_bind()

    # This migration is PostgreSQL-only; skip on SQLite.
    if conn.dialect.name != "postgresql":
        return

    result = conn.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :role"),
        {"role": ML_SA_ROLE},
    )
    if result.fetchone() is None:
        return

    table_list = ", ".join(TABLES)
    conn.execute(text(f'REVOKE SELECT ON TABLE {table_list} FROM "{ML_SA_ROLE}"'))  # noqa: S608
