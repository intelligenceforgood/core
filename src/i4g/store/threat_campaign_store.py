"""Store for threat campaign CRUD and case-linkage management."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from i4g.store import sql as sql_schema
from i4g.store.sql import session_factory as default_session_factory

LOGGER = logging.getLogger(__name__)

# Valid campaign statuses (lifecycle order)
CAMPAIGN_STATUSES = ("emerging", "active", "declining", "dormant", "closed")


class ThreatCampaignStore:
    """CRUD operations for ``threat_campaigns`` and ``threat_campaign_cases``.

    Supports create, get, list, update status, link/unlink cases, merge,
    and split operations for the threat campaign model.
    """

    def __init__(
        self,
        db_path: str | None = None,
        *,
        session_factory: sessionmaker | None = None,
    ) -> None:
        if session_factory is not None:
            self._session_factory = session_factory
        elif db_path is not None:
            engine = sa.create_engine(
                f"sqlite:///{db_path}",
                pool_pre_ping=True,
                connect_args={"check_same_thread": False},
            )
            sql_schema.METADATA.create_all(engine, checkfirst=True)
            self._session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        else:
            self._session_factory = default_session_factory()

    @contextmanager
    def _session_scope(self) -> Iterator[Session]:
        """Yield a session and close it on exit."""
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Campaign CRUD
    # ------------------------------------------------------------------

    def create_campaign(
        self,
        *,
        name: str,
        description: str | None = None,
        origin: str = "manual",
        status: str = "emerging",
        created_by: str = "system",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Create a new threat campaign.

        Args:
            name: Human-readable campaign name (≤60 chars recommended).
            description: Optional longer description.
            origin: How the campaign was created (manual, auto:wallet_cluster, etc.).
            status: Initial lifecycle status.
            created_by: Analyst identifier or "system".
            metadata: Optional JSON metadata.

        Returns:
            The generated campaign_id.
        """
        campaign_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        with self._session_scope() as session:
            session.execute(
                sa.insert(sql_schema.threat_campaigns).values(
                    campaign_id=campaign_id,
                    name=name,
                    description=description,
                    origin=origin,
                    status=status,
                    created_by=created_by,
                    metadata=metadata if isinstance(metadata, str) else (json.dumps(metadata) if metadata else None),
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()
        return campaign_id

    def get_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        """Fetch a single campaign by ID.

        Args:
            campaign_id: The campaign UUID.

        Returns:
            Campaign dict or None if not found.
        """
        with self._session_scope() as session:
            row = session.execute(
                sa.select(sql_schema.threat_campaigns).where(sql_schema.threat_campaigns.c.campaign_id == campaign_id)
            ).first()
            if not row:
                return None
            return dict(row._mapping)

    def list_campaigns(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List campaigns with optional status filter.

        Args:
            status: Filter by lifecycle status.
            limit: Max rows to return.
            offset: Pagination offset.

        Returns:
            List of campaign dicts.
        """
        stmt = sa.select(sql_schema.threat_campaigns).order_by(sql_schema.threat_campaigns.c.updated_at.desc())
        if status:
            stmt = stmt.where(sql_schema.threat_campaigns.c.status == status)
        stmt = stmt.limit(limit).offset(offset)

        with self._session_scope() as session:
            rows = session.execute(stmt).all()
            return [dict(r._mapping) for r in rows]

    def update_status(self, campaign_id: str, *, status: str) -> None:
        """Update a campaign's lifecycle status.

        Args:
            campaign_id: The campaign UUID.
            status: New status value.
        """
        now = datetime.now(UTC)
        with self._session_scope() as session:
            session.execute(
                sa.update(sql_schema.threat_campaigns)
                .where(sql_schema.threat_campaigns.c.campaign_id == campaign_id)
                .values(status=status, updated_at=now)
            )
            session.commit()

    def update_campaign(
        self,
        campaign_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        risk_score: float | None = None,
        taxonomy_rollup: dict | list | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Update campaign fields.

        Args:
            campaign_id: The campaign UUID.
            name: New name (optional).
            description: New description (optional).
            risk_score: New risk score (optional).
            taxonomy_rollup: New rollup data (optional).
            metadata: New metadata (optional).
        """
        values: dict[str, Any] = {"updated_at": datetime.now(UTC)}
        if name is not None:
            values["name"] = name
        if description is not None:
            values["description"] = description
        if risk_score is not None:
            values["risk_score"] = risk_score
        if taxonomy_rollup is not None:
            values["taxonomy_rollup"] = (
                json.dumps(taxonomy_rollup) if not isinstance(taxonomy_rollup, str) else taxonomy_rollup
            )
        if metadata is not None:
            values["metadata"] = json.dumps(metadata) if not isinstance(metadata, str) else metadata

        with self._session_scope() as session:
            session.execute(
                sa.update(sql_schema.threat_campaigns)
                .where(sql_schema.threat_campaigns.c.campaign_id == campaign_id)
                .values(**values)
            )
            session.commit()

    # ------------------------------------------------------------------
    # Case Linkage
    # ------------------------------------------------------------------

    def link_case(
        self,
        campaign_id: str,
        case_id: str,
        *,
        linked_by: str = "manual",
        link_reason: str | None = None,
    ) -> None:
        """Link a case to a campaign.

        Args:
            campaign_id: The campaign UUID.
            case_id: The case identifier.
            linked_by: Who/what created the link.
            link_reason: Optional rationale.
        """
        now = datetime.now(UTC)
        with self._session_scope() as session:
            session.execute(
                sql_schema.dialect_insert(session, sql_schema.threat_campaign_cases)
                .values(
                    campaign_id=campaign_id,
                    case_id=case_id,
                    linked_at=now,
                    linked_by=linked_by,
                    link_reason=link_reason,
                )
                .on_conflict_do_nothing(index_elements=["campaign_id", "case_id"])
            )
            session.commit()

    def unlink_case(self, campaign_id: str, case_id: str) -> None:
        """Remove a case from a campaign.

        Args:
            campaign_id: The campaign UUID.
            case_id: The case identifier.
        """
        with self._session_scope() as session:
            session.execute(
                sa.delete(sql_schema.threat_campaign_cases).where(
                    sa.and_(
                        sql_schema.threat_campaign_cases.c.campaign_id == campaign_id,
                        sql_schema.threat_campaign_cases.c.case_id == case_id,
                    )
                )
            )
            session.commit()

    def get_campaign_cases(self, campaign_id: str) -> list[dict[str, Any]]:
        """List all cases linked to a campaign.

        Args:
            campaign_id: The campaign UUID.

        Returns:
            List of link dicts (campaign_id, case_id, linked_at, linked_by, link_reason).
        """
        with self._session_scope() as session:
            rows = session.execute(
                sa.select(sql_schema.threat_campaign_cases).where(
                    sql_schema.threat_campaign_cases.c.campaign_id == campaign_id
                )
            ).all()
            return [dict(r._mapping) for r in rows]

    def get_case_campaigns(self, case_id: str) -> list[dict[str, Any]]:
        """List all campaigns that a case belongs to.

        Args:
            case_id: The case identifier.

        Returns:
            List of campaign dicts.
        """
        tcc = sql_schema.threat_campaign_cases
        tc = sql_schema.threat_campaigns
        with self._session_scope() as session:
            rows = session.execute(
                sa.select(tc).join(tcc, tcc.c.campaign_id == tc.c.campaign_id).where(tcc.c.case_id == case_id)
            ).all()
            return [dict(r._mapping) for r in rows]

    # ------------------------------------------------------------------
    # Merge & Split
    # ------------------------------------------------------------------

    def merge_campaigns(
        self,
        source_ids: list[str],
        *,
        target_name: str,
        merged_by: str = "system",
    ) -> str:
        """Merge multiple campaigns into a new one.

        All cases from source campaigns are linked to the new campaign.
        Source campaigns are set to status ``closed``.

        Args:
            source_ids: Campaign IDs to merge.
            target_name: Name for the merged campaign.
            merged_by: Who performed the merge.

        Returns:
            The new campaign_id.
        """
        target_id = self.create_campaign(
            name=target_name,
            origin="merge",
            created_by=merged_by,
            metadata={"merged_from": source_ids},
        )

        now = datetime.now(UTC)
        with self._session_scope() as session:
            # Collect all cases from source campaigns
            source_links = session.execute(
                sa.select(sql_schema.threat_campaign_cases).where(
                    sql_schema.threat_campaign_cases.c.campaign_id.in_(source_ids)
                )
            ).all()

            # Link them to the target campaign (deduplicate by case_id)
            seen_cases: set[str] = set()
            for link in source_links:
                case_id = link._mapping["case_id"]
                if case_id in seen_cases:
                    continue
                seen_cases.add(case_id)
                session.execute(
                    sql_schema.dialect_insert(session, sql_schema.threat_campaign_cases)
                    .values(
                        campaign_id=target_id,
                        case_id=case_id,
                        linked_at=now,
                        linked_by=f"merge:{merged_by}",
                        link_reason=f"Merged from campaigns: {', '.join(source_ids)}",
                    )
                    .on_conflict_do_nothing(index_elements=["campaign_id", "case_id"])
                )

            # Close source campaigns
            session.execute(
                sa.update(sql_schema.threat_campaigns)
                .where(sql_schema.threat_campaigns.c.campaign_id.in_(source_ids))
                .values(status="closed", updated_at=now)
            )
            session.commit()

        return target_id

    def split_campaign(
        self,
        campaign_id: str,
        *,
        case_groups: dict[str, list[str]],
        split_by: str = "system",
    ) -> dict[str, str]:
        """Split a campaign into multiple new campaigns.

        Args:
            campaign_id: The campaign to split.
            case_groups: Mapping of new campaign name → list of case_ids.
            split_by: Who performed the split.

        Returns:
            Mapping of new campaign name → new campaign_id.
        """
        result: dict[str, str] = {}

        for group_name, case_ids in case_groups.items():
            new_id = self.create_campaign(
                name=group_name,
                origin="split",
                created_by=split_by,
                metadata={"split_from": campaign_id},
            )
            for case_id in case_ids:
                self.link_case(new_id, case_id, linked_by=f"split:{split_by}")
            result[group_name] = new_id

        # Close the original campaign
        self.update_status(campaign_id, status="closed")

        return result
