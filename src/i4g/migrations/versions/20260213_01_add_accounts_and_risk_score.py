"""Add accounts table and risk_score/taxonomy_version columns to cases.

WS-3 (Classification & Risk Scoring) added risk_score and taxonomy_version
to the cases table.  WS-5 (RBAC & Role Enforcement) added the accounts
table.  Both were present in sql.py but missing an Alembic migration,
so Cloud SQL environments never received the schema changes.

Revision ID: 20260213_01
Revises: 20260212_01
Create Date: 2026-02-13 18:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260213_01"
down_revision: Union[str, None] = "20260212_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    existing_tables = insp.get_table_names()

    # --- WS-5: accounts table for RBAC ---
    if "accounts" not in existing_tables:
        op.create_table(
            "accounts",
            sa.Column("email", sa.Text(), primary_key=True),
            sa.Column("role", sa.Text(), nullable=False, server_default="analyst"),
            sa.Column("display_name", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("idx_accounts_role", "accounts", ["role"], unique=False)

    # --- WS-3: risk scoring columns on cases ---
    existing_columns = {c["name"] for c in insp.get_columns("cases")}
    if "risk_score" not in existing_columns:
        op.add_column("cases", sa.Column("risk_score", sa.Numeric(5, 1), nullable=False, server_default="0"))
        op.create_index("idx_cases_risk_score", "cases", ["risk_score"], unique=False)
    if "taxonomy_version" not in existing_columns:
        op.add_column("cases", sa.Column("taxonomy_version", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_index("idx_cases_risk_score", table_name="cases")
    op.drop_column("cases", "taxonomy_version")
    op.drop_column("cases", "risk_score")
    op.drop_index("idx_accounts_role", table_name="accounts")
    op.drop_table("accounts")
