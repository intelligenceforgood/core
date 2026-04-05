"""Schema normalization: add cases.description, FKs, drop scam_records dead columns.

1. Add ``cases.description`` TEXT column for narrative text.
2. Backfill ``cases.description`` from ``scam_records.text``.
3. Delete orphaned ``scam_records`` and ``review_queue`` rows whose
   ``case_id`` does not exist in ``cases``.
4. Add FK constraints: ``review_queue.case_id`` and ``scam_records.case_id``
   → ``cases.case_id`` (ON DELETE CASCADE).
5. Drop dead columns from ``scam_records``:
   ``classification_result`` (never read for display),
   ``tags`` (never read from scam_records).

Revision ID: 20260404_01
Revises: 20260331_01
Create Date: 2026-04-04

"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

# revision identifiers, used by Alembic.
revision: str = "20260404_01"
down_revision: str | None = "20260331_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite(conn: sa.Connection) -> bool:
    return conn.dialect.name == "sqlite"


def _column_exists(conn: sa.Connection, table: str, column: str) -> bool:
    insp = inspect(conn)
    cols = {c["name"] for c in insp.get_columns(table)}
    return column in cols


def _fk_exists(conn: sa.Connection, table: str, constrained_col: str, referred_table: str) -> bool:
    """Check whether a FK from *table.constrained_col* → *referred_table* already exists."""
    insp = inspect(conn)
    for fk in insp.get_foreign_keys(table):
        if constrained_col in fk.get("constrained_columns", []) and fk.get("referred_table") == referred_table:
            return True
    return False


def upgrade() -> None:
    conn = op.get_bind()

    # --- M1: Add cases.description ---
    if not _column_exists(conn, "cases", "description"):
        op.add_column("cases", sa.Column("description", sa.Text(), nullable=True))

    # --- M2: Backfill cases.description from scam_records.text ---
    if _is_sqlite(conn):
        conn.execute(
            text(
                "UPDATE cases SET description = ("
                "  SELECT text FROM scam_records WHERE scam_records.case_id = cases.case_id"
                ") WHERE description IS NULL"
            )
        )
    else:
        conn.execute(
            text(
                "UPDATE cases SET description = sr.text "
                "FROM scam_records sr "
                "WHERE sr.case_id = cases.case_id AND cases.description IS NULL"
            )
        )

    # --- M3: Clean up orphans ---
    conn.execute(text("DELETE FROM scam_records WHERE case_id NOT IN (SELECT case_id FROM cases)"))
    # review_actions FK to review_queue means we must delete actions first for
    # orphaned reviews, then the review_queue rows.
    conn.execute(
        text(
            "DELETE FROM review_actions WHERE review_id IN ("
            "  SELECT review_id FROM review_queue "
            "  WHERE case_id NOT IN (SELECT case_id FROM cases)"
            ")"
        )
    )
    conn.execute(text("DELETE FROM review_queue WHERE case_id NOT IN (SELECT case_id FROM cases)"))

    # --- M4: Add FK constraints ---
    if _is_sqlite(conn):
        # SQLite doesn't support ALTER TABLE ADD CONSTRAINT.
        # FKs are enforced at runtime via PRAGMA foreign_keys=ON.
        # The table definitions in sql.py carry the FKs for new databases.
        pass
    else:
        if not _fk_exists(conn, "review_queue", "case_id", "cases"):
            op.create_foreign_key(
                "fk_review_queue_case_id",
                "review_queue",
                "cases",
                ["case_id"],
                ["case_id"],
                ondelete="CASCADE",
            )
        if not _fk_exists(conn, "scam_records", "case_id", "cases"):
            op.create_foreign_key(
                "fk_scam_records_case_id",
                "scam_records",
                "cases",
                ["case_id"],
                ["case_id"],
                ondelete="CASCADE",
            )

    # --- M5: Drop dead columns from scam_records ---
    if _is_sqlite(conn):
        # SQLite 3.35+ supports ALTER TABLE DROP COLUMN
        for col in ("classification_result", "tags"):
            if _column_exists(conn, "scam_records", col):
                with contextlib.suppress(Exception):
                    conn.execute(text(f"ALTER TABLE scam_records DROP COLUMN {col}"))
    else:
        for col in ("classification_result", "tags"):
            if _column_exists(conn, "scam_records", col):
                op.drop_column("scam_records", col)


def downgrade() -> None:
    conn = op.get_bind()

    # Re-add dropped columns
    if not _column_exists(conn, "scam_records", "classification_result"):
        op.add_column(
            "scam_records",
            sa.Column("classification_result", sa.JSON(), nullable=True),
        )
    if not _column_exists(conn, "scam_records", "tags"):
        op.add_column(
            "scam_records",
            sa.Column("tags", sa.JSON(), nullable=True),
        )

    # Drop FK constraints
    if not _is_sqlite(conn):
        if _fk_exists(conn, "review_queue", "case_id", "cases"):
            op.drop_constraint("fk_review_queue_case_id", "review_queue", type_="foreignkey")
        if _fk_exists(conn, "scam_records", "case_id", "cases"):
            op.drop_constraint("fk_scam_records_case_id", "scam_records", type_="foreignkey")

    # Drop description column
    if _column_exists(conn, "cases", "description"):
        op.drop_column("cases", "description")
