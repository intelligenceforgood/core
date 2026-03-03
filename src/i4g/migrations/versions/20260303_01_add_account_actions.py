"""Add account_actions table for admin audit trail.

The account management operations (role changes, deactivation,
reactivation) were previously logged to ``review_actions`` with a
dummy ``review_id='system'``.  This violates the FK constraint
``review_actions_review_id_fkey`` in PostgreSQL because no row with
``review_id='system'`` exists in ``review_queue``.

This migration creates a dedicated ``account_actions`` table without
that FK dependency.  Existing rows in ``review_actions`` with
``review_id='system'`` are migrated to the new table and then deleted.

Revision ID: 20260303_01
Revises: 20260302_01
Create Date: 2026-03-03

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260303_01"
down_revision: Union[str, None] = "20260302_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create account_actions table and migrate legacy rows."""
    op.create_table(
        "account_actions",
        sa.Column("action_id", sa.Text(), primary_key=True),
        sa.Column("target_email", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("idx_account_actions_target", "account_actions", ["target_email"])
    op.create_index("idx_account_actions_created_at", "account_actions", ["created_at"])

    # Migrate any existing system audit rows from review_actions.
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT action_id, actor, action, payload, created_at "
            "FROM review_actions WHERE review_id = 'system'"
        )
    ).fetchall()

    if rows:
        for r in rows:
            # Extract target_email from the payload JSON.
            payload = r[3] if r[3] else {}
            target_email = ""
            if isinstance(payload, dict):
                target_email = payload.get("target_email", "")
            conn.execute(
                sa.text(
                    "INSERT INTO account_actions "
                    "(action_id, target_email, actor, action, payload, created_at) "
                    "VALUES (:aid, :target, :actor, :action, :payload, :created_at)"
                ),
                {
                    "aid": r[0],
                    "target": target_email,
                    "actor": r[1],
                    "action": r[2],
                    "payload": r[3],
                    "created_at": r[4],
                },
            )

        # Remove migrated rows from review_actions.
        conn.execute(sa.text("DELETE FROM review_actions WHERE review_id = 'system'"))


def downgrade() -> None:
    """Drop account_actions table."""
    op.drop_index("idx_account_actions_created_at", table_name="account_actions")
    op.drop_index("idx_account_actions_target", table_name="account_actions")
    op.drop_table("account_actions")
