"""Add indexes on review_queue and review_actions for query performance.

Revision ID: 20260212_01
Revises: 20260204_01
Create Date: 2026-02-12 12:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20260212_01"
down_revision: Union[str, None] = "20260204_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # review_queue: high-traffic query columns (E19)
    op.create_index("idx_review_queue_status", "review_queue", ["status"], unique=False)
    op.create_index("idx_review_queue_priority", "review_queue", ["priority"], unique=False)
    op.create_index("idx_review_queue_case_id", "review_queue", ["case_id"], unique=False)
    op.create_index("idx_review_queue_queued_at", "review_queue", ["queued_at"], unique=False)

    # review_actions: timeline and history lookups (E20)
    op.create_index("idx_review_actions_review_id", "review_actions", ["review_id"], unique=False)
    op.create_index("idx_review_actions_created_at", "review_actions", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_review_actions_created_at", table_name="review_actions")
    op.drop_index("idx_review_actions_review_id", table_name="review_actions")
    op.drop_index("idx_review_queue_queued_at", table_name="review_queue")
    op.drop_index("idx_review_queue_case_id", table_name="review_queue")
    op.drop_index("idx_review_queue_priority", table_name="review_queue")
    op.drop_index("idx_review_queue_status", table_name="review_queue")
