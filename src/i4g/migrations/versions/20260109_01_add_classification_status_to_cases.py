"""add_classification_status_to_cases

Revision ID: d8232e13626e
Revises: 20260106_01
Create Date: 2026-01-09 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260109_01"
down_revision: str | None = "20260106_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add classification_status column
    op.add_column("cases", sa.Column("classification_status", sa.Text(), server_default="pending", nullable=False))

    # Add indices
    op.create_index(
        "idx_cases_classification_status", "cases", ["classification_status"], unique=False, if_not_exists=True
    )
    op.create_index("idx_cases_tags", "cases", ["tags"], unique=False, postgresql_using="gin", if_not_exists=True)


def downgrade() -> None:
    # Remove indices
    op.drop_index("idx_cases_tags", table_name="cases", postgresql_using="gin")
    op.drop_index("idx_cases_classification_status", table_name="cases")

    # Remove column
    op.drop_column("cases", "classification_status")
