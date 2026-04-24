"""PhishDestroy Sprint 1: threat_actors, actor_identities, actor_identity_edges,
blocklist_hits, domain_discoveries tables.

Revision ID: 20260424_01
Revises: 20260407_02
Create Date: 2026-04-24

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260424_01"
down_revision: str | None = "20260407_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Column type helpers (must match sql.py definitions)
UUID_TYPE = sa.String(length=64)
TIMESTAMP = sa.DateTime(timezone=True)
JSON_TYPE = sa.JSON()


def _index_exists(inspector: sa.Inspector, table: str, index_name: str) -> bool:
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # 1. threat_actors
    if not inspector.has_table("threat_actors"):
        op.create_table(
            "threat_actors",
            sa.Column("actor_id", UUID_TYPE, primary_key=True),
            sa.Column("display_name", sa.Text(), nullable=False),
            sa.Column("role", sa.Text(), nullable=True),
            sa.Column("campaign_id", UUID_TYPE, nullable=True),
            sa.Column("real_name", sa.Text(), nullable=True),
            sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
            sa.Column("first_seen_at", TIMESTAMP, nullable=True),
            sa.Column("last_seen_at", TIMESTAMP, nullable=True),
            sa.Column("metadata", JSON_TYPE, nullable=True),
            sa.Column("source_provenance", JSON_TYPE, nullable=True),
            sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        with op.batch_alter_table("threat_actors") as batch_op:
            batch_op.create_foreign_key(
                "fk_threat_actors_campaign_id",
                "campaigns",
                ["campaign_id"],
                ["campaign_id"],
                ondelete="SET NULL",
            )
    if not _index_exists(inspector, "threat_actors", "idx_threat_actors_campaign_id"):
        op.create_index("idx_threat_actors_campaign_id", "threat_actors", ["campaign_id"])

    # 2. actor_identities (FK to threat_actors)
    if not inspector.has_table("actor_identities"):
        op.create_table(
            "actor_identities",
            sa.Column("identity_id", UUID_TYPE, primary_key=True),
            sa.Column("actor_id", UUID_TYPE, nullable=False),
            sa.Column("platform", sa.Text(), nullable=False),
            sa.Column("handle", sa.Text(), nullable=False),
            sa.Column("platform_user_id", sa.Text(), nullable=True),
            sa.Column("username_history", JSON_TYPE, nullable=True),
            sa.Column("display_name_history", JSON_TYPE, nullable=True),
            sa.Column("first_seen_at", TIMESTAMP, nullable=True),
            sa.Column("last_seen_at", TIMESTAMP, nullable=True),
            sa.Column("metadata", JSON_TYPE, nullable=True),
            sa.Column("source_provenance", JSON_TYPE, nullable=True),
            sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("platform", "handle", name="uq_actor_identities_platform_handle"),
        )
        with op.batch_alter_table("actor_identities") as batch_op:
            batch_op.create_foreign_key(
                "fk_actor_identities_actor_id",
                "threat_actors",
                ["actor_id"],
                ["actor_id"],
                ondelete="CASCADE",
            )
    if not _index_exists(inspector, "actor_identities", "idx_actor_identities_actor_id"):
        op.create_index("idx_actor_identities_actor_id", "actor_identities", ["actor_id"])

    # 3. actor_identity_edges (FKs to actor_identities ×2)
    if not inspector.has_table("actor_identity_edges"):
        op.create_table(
            "actor_identity_edges",
            sa.Column("edge_id", UUID_TYPE, primary_key=True),
            sa.Column("source_identity_id", UUID_TYPE, nullable=False),
            sa.Column("target_identity_id", UUID_TYPE, nullable=False),
            sa.Column("edge_type", sa.Text(), nullable=False),
            sa.Column("weight", sa.Numeric(), nullable=True),
            sa.Column("evidence", JSON_TYPE, nullable=True),
            sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint(
                "source_identity_id",
                "target_identity_id",
                "edge_type",
                name="uq_actor_identity_edges_triple",
            ),
        )
        with op.batch_alter_table("actor_identity_edges") as batch_op:
            batch_op.create_foreign_key(
                "fk_aie_source_identity_id",
                "actor_identities",
                ["source_identity_id"],
                ["identity_id"],
                ondelete="CASCADE",
            )
            batch_op.create_foreign_key(
                "fk_aie_target_identity_id",
                "actor_identities",
                ["target_identity_id"],
                ["identity_id"],
                ondelete="CASCADE",
            )

    # 4. blocklist_hits (FK to indicators)
    if not inspector.has_table("blocklist_hits"):
        op.create_table(
            "blocklist_hits",
            sa.Column("hit_id", UUID_TYPE, primary_key=True),
            sa.Column("indicator_id", UUID_TYPE, nullable=False),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("first_seen_at", TIMESTAMP, nullable=True),
            sa.Column("last_seen_at", TIMESTAMP, nullable=True),
            sa.Column("metadata", JSON_TYPE, nullable=True),
            sa.Column("source_provenance", JSON_TYPE, nullable=True),
            sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("indicator_id", "source", name="uq_blocklist_hits_indicator_source"),
        )
        with op.batch_alter_table("blocklist_hits") as batch_op:
            batch_op.create_foreign_key(
                "fk_blocklist_hits_indicator_id",
                "indicators",
                ["indicator_id"],
                ["indicator_id"],
                ondelete="CASCADE",
            )

    # 5. domain_discoveries
    if not inspector.has_table("domain_discoveries"):
        op.create_table(
            "domain_discoveries",
            sa.Column("discovery_id", UUID_TYPE, primary_key=True),
            sa.Column("domain", sa.Text(), nullable=False),
            sa.Column("subject_common_name", sa.Text(), nullable=True),
            sa.Column("not_before", TIMESTAMP, nullable=True),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("seen_at", TIMESTAMP, nullable=False),
            sa.Column("filter_match", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("filter_reason", sa.Text(), nullable=True),
            sa.Column("enqueued_scan_id", UUID_TYPE, nullable=True),
            sa.Column("raw", JSON_TYPE, nullable=True),
            sa.Column("source_provenance", JSON_TYPE, nullable=True),
            sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    # 6. Indexes
    if not _index_exists(inspector, "domain_discoveries", "idx_domain_discoveries_seen_at"):
        op.create_index("idx_domain_discoveries_seen_at", "domain_discoveries", ["seen_at"])
    if not _index_exists(inspector, "domain_discoveries", "idx_domain_discoveries_filter_match"):
        op.create_index("idx_domain_discoveries_filter_match", "domain_discoveries", ["filter_match"])


def downgrade() -> None:
    # Indexes first, then tables in reverse creation order.
    op.drop_index("idx_domain_discoveries_filter_match", table_name="domain_discoveries")
    op.drop_index("idx_domain_discoveries_seen_at", table_name="domain_discoveries")
    op.drop_table("domain_discoveries")

    with op.batch_alter_table("blocklist_hits") as batch_op:
        batch_op.drop_constraint("fk_blocklist_hits_indicator_id", type_="foreignkey")
    op.drop_table("blocklist_hits")

    with op.batch_alter_table("actor_identity_edges") as batch_op:
        batch_op.drop_constraint("fk_aie_target_identity_id", type_="foreignkey")
        batch_op.drop_constraint("fk_aie_source_identity_id", type_="foreignkey")
    op.drop_table("actor_identity_edges")

    op.drop_index("idx_actor_identities_actor_id", table_name="actor_identities")
    with op.batch_alter_table("actor_identities") as batch_op:
        batch_op.drop_constraint("fk_actor_identities_actor_id", type_="foreignkey")
    op.drop_table("actor_identities")

    op.drop_index("idx_threat_actors_campaign_id", table_name="threat_actors")
    with op.batch_alter_table("threat_actors") as batch_op:
        batch_op.drop_constraint("fk_threat_actors_campaign_id", type_="foreignkey")
    op.drop_table("threat_actors")
