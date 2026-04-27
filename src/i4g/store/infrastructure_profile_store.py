"""InfrastructureProfileStore: CRUD and upsert for infrastructure_profiles table."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.store import sql as sql_schema
from i4g.store.sql import METADATA
from i4g.store.sql import session_factory as default_session_factory


class InfrastructureProfileStore:
    """SQLAlchemy-backed store for infrastructure profile records."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        session_factory: sessionmaker | None = None,
    ) -> None:
        if session_factory is not None:
            self._session_factory = session_factory
        elif db_path is not None:
            resolved = Path(db_path)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            engine = sa.create_engine(
                f"sqlite:///{resolved}",
                connect_args={"check_same_thread": False, "timeout": 30},
                future=True,
            )
            self._session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        else:
            self._session_factory = default_session_factory()

        with self._session_factory() as session:
            if session.bind.dialect.name == "sqlite":
                METADATA.create_all(session.connection())

    def upsert_by_campaign_domain(
        self,
        *,
        campaign_id: str,
        primary_domain: str,
        subdomain_roles: dict[str, Any] | None = None,
        tech_stack: dict[str, Any] | None = None,
        source_maps_exposed: bool = False,
        auth_model: str | None = None,
        cors_config: str | None = None,
        metadata_json: dict[str, Any] | None = None,
        source_provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Insert or update an infrastructure profile keyed on (campaign_id, primary_domain).

        The UNIQUE constraint on (campaign_id, primary_domain) ensures exactly one row per pair.
        On update, all content fields are refreshed; created_at is preserved.
        Returns the final row dict.
        """
        tbl = sql_schema.infrastructure_profiles
        now = datetime.now(UTC)

        with self._session_factory() as session:
            existing = session.execute(
                sa.select(tbl).where(
                    sa.and_(
                        tbl.c.campaign_id == campaign_id,
                        tbl.c.primary_domain == primary_domain,
                    )
                )
            ).first()

            if existing is None:
                profile_id = str(uuid.uuid4())
                row = {
                    "profile_id": profile_id,
                    "campaign_id": campaign_id,
                    "primary_domain": primary_domain,
                    "subdomain_roles": subdomain_roles,
                    "tech_stack": tech_stack,
                    "source_maps_exposed": source_maps_exposed,
                    "auth_model": auth_model,
                    "cors_config": cors_config,
                    "metadata_json": metadata_json,
                    "source_provenance": source_provenance,
                    "created_at": now,
                    "updated_at": now,
                }
                session.execute(sa.insert(tbl).values(row))
            else:
                profile_id = existing._mapping["profile_id"]
                session.execute(
                    sa.update(tbl)
                    .where(tbl.c.profile_id == profile_id)
                    .values(
                        subdomain_roles=subdomain_roles,
                        tech_stack=tech_stack,
                        source_maps_exposed=source_maps_exposed,
                        auth_model=auth_model,
                        cors_config=cors_config,
                        metadata_json=metadata_json,
                        source_provenance=source_provenance,
                        updated_at=now,
                    )
                )
            session.commit()

        with self._session_factory() as session:
            result = session.execute(sa.select(tbl).where(tbl.c.profile_id == profile_id)).first()
            return dict(result._mapping)

    def get(self, profile_id: str) -> dict[str, Any] | None:
        """Return a single infrastructure profile by ID, or None."""
        tbl = sql_schema.infrastructure_profiles
        with self._session_factory() as session:
            result = session.execute(sa.select(tbl).where(tbl.c.profile_id == profile_id)).first()
            if result is None:
                return None
            return dict(result._mapping)

    def get_by_campaign(self, campaign_id: str) -> list[dict[str, Any]]:
        """Return all infrastructure profiles for a given campaign."""
        tbl = sql_schema.infrastructure_profiles
        stmt = sa.select(tbl).where(tbl.c.campaign_id == campaign_id).order_by(tbl.c.primary_domain.asc())
        with self._session_factory() as session:
            rows = session.execute(stmt).fetchall()
            return [dict(r._mapping) for r in rows]
