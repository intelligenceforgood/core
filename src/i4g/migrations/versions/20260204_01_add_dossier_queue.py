"""add_dossier_queue

Revision ID: 20260204_01
Revises: 20260109_01
Create Date: 2026-02-04 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260204_01"
down_revision: Union[str, None] = "20260109_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dossier_queue",
        sa.Column("plan_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("priority", sa.Text(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("warnings", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("plan_id"),
    )
    op.create_index("idx_dossier_queue_status", "dossier_queue", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_dossier_queue_status", table_name="dossier_queue")
    op.drop_table("dossier_queue")
