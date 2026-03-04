"""Add file_sha256 and ingested_at columns to source_documents.

Revision ID: 20260225_01
Revises: 20260221_01
Create Date: 2026-02-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260225_01"
down_revision: str | None = "20260221_01"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add file_sha256 and ingested_at to source_documents."""
    with op.batch_alter_table("source_documents") as batch_op:
        batch_op.add_column(sa.Column("file_sha256", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("ingested_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Remove file_sha256 and ingested_at from source_documents."""
    with op.batch_alter_table("source_documents") as batch_op:
        batch_op.drop_column("ingested_at")
        batch_op.drop_column("file_sha256")
