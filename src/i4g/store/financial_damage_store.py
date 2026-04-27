"""FinancialDamageStore: CRUD and upsert for financial_damage_claims table."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.store import sql as sql_schema
from i4g.store.sql import METADATA
from i4g.store.sql import session_factory as default_session_factory


def _json_field_eq(session: sa.orm.Session, col: sa.Column, field: str, value: str) -> sa.ColumnElement:
    """Return a dialect-aware WHERE clause matching a top-level JSON field value."""
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        return col.op("->>")(field) == value
    return sa.func.json_extract(col, f"$.{field}") == value


class FinancialDamageStore:
    """SQLAlchemy-backed store for financial damage claim records."""

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

    def create(
        self,
        *,
        case_id: str | None = None,
        campaign_id: str | None = None,
        session_id: str | None = None,
        currency: str,
        chain: str | None = None,
        amount_claimed: Decimal,
        amount_confirmed: Decimal | None = None,
        tx_hash: str | None = None,
        wallet_address: str | None = None,
        verification_status: str = "unverified",
        metadata_json: dict[str, Any] | None = None,
        source_provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Insert a new financial damage claim and return its row dict."""
        claim_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        row = {
            "claim_id": claim_id,
            "case_id": case_id,
            "campaign_id": campaign_id,
            "session_id": session_id,
            "currency": currency,
            "chain": chain,
            "amount_claimed": amount_claimed,
            "amount_confirmed": amount_confirmed,
            "tx_hash": tx_hash,
            "wallet_address": wallet_address,
            "verification_status": verification_status,
            "metadata_json": metadata_json,
            "source_provenance": source_provenance,
            "created_at": now,
            "updated_at": now,
        }
        tbl = sql_schema.financial_damage_claims
        with self._session_factory() as session:
            session.execute(sa.insert(tbl).values(row))
            session.commit()
        return row

    def get(self, claim_id: str) -> dict[str, Any] | None:
        """Return a single damage claim by ID, or None."""
        tbl = sql_schema.financial_damage_claims
        with self._session_factory() as session:
            result = session.execute(sa.select(tbl).where(tbl.c.claim_id == claim_id)).first()
            if result is None:
                return None
            return dict(result._mapping)

    def upsert_by_provenance(
        self,
        *,
        source_provenance: dict[str, Any],
        currency: str,
        amount_claimed: Decimal,
        case_id: str | None = None,
        campaign_id: str | None = None,
        session_id: str | None = None,
        chain: str | None = None,
        amount_confirmed: Decimal | None = None,
        tx_hash: str | None = None,
        wallet_address: str | None = None,
        verification_status: str = "unverified",
        metadata_json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Insert or update a damage claim keyed on (source_provenance.source, source_provenance.record_id).

        Preserves created_at on update; refreshes updated_at and all content fields.
        Returns the final row dict.
        """
        tbl = sql_schema.financial_damage_claims
        prov_source = source_provenance["source"]
        prov_record_id = source_provenance["record_id"]
        now = datetime.now(UTC)

        with self._session_factory() as session:
            existing = session.execute(
                sa.select(tbl).where(
                    sa.and_(
                        _json_field_eq(session, tbl.c.source_provenance, "source", prov_source),
                        _json_field_eq(session, tbl.c.source_provenance, "record_id", prov_record_id),
                    )
                )
            ).first()

            if existing is None:
                claim_id = str(uuid.uuid4())
                row = {
                    "claim_id": claim_id,
                    "case_id": case_id,
                    "campaign_id": campaign_id,
                    "session_id": session_id,
                    "currency": currency,
                    "chain": chain,
                    "amount_claimed": amount_claimed,
                    "amount_confirmed": amount_confirmed,
                    "tx_hash": tx_hash,
                    "wallet_address": wallet_address,
                    "verification_status": verification_status,
                    "metadata_json": metadata_json,
                    "source_provenance": source_provenance,
                    "created_at": now,
                    "updated_at": now,
                }
                session.execute(sa.insert(tbl).values(row))
            else:
                claim_id = existing._mapping["claim_id"]
                session.execute(
                    sa.update(tbl)
                    .where(tbl.c.claim_id == claim_id)
                    .values(
                        case_id=case_id,
                        campaign_id=campaign_id,
                        session_id=session_id,
                        currency=currency,
                        chain=chain,
                        amount_claimed=amount_claimed,
                        amount_confirmed=amount_confirmed,
                        tx_hash=tx_hash,
                        wallet_address=wallet_address,
                        verification_status=verification_status,
                        metadata_json=metadata_json,
                        source_provenance=source_provenance,
                        updated_at=now,
                    )
                )
            session.commit()

        with self._session_factory() as session:
            result = session.execute(sa.select(tbl).where(tbl.c.claim_id == claim_id)).first()
            return dict(result._mapping)

    def list_by_campaign(
        self, campaign_id: str, *, currency: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return damage claims for a campaign, optionally filtered by currency."""
        tbl = sql_schema.financial_damage_claims
        predicate = tbl.c.campaign_id == campaign_id
        if currency is not None:
            predicate = sa.and_(predicate, tbl.c.currency == currency)
        stmt = sa.select(tbl).where(predicate).order_by(tbl.c.created_at.desc()).limit(limit)
        with self._session_factory() as session:
            rows = session.execute(stmt).fetchall()
            return [dict(r._mapping) for r in rows]

    def totals_by_currency(self, campaign_id: str) -> dict[str, dict[str, Decimal]]:
        """Return claimed and confirmed totals per currency for a campaign.

        Returns a mapping of ``{currency: {claimed: Decimal, confirmed: Decimal}}``.
        Uses SQL aggregation; does not pull rows into Python.
        """
        tbl = sql_schema.financial_damage_claims
        stmt = (
            sa.select(
                tbl.c.currency,
                sa.func.sum(tbl.c.amount_claimed).label("total_claimed"),
                sa.func.sum(tbl.c.amount_confirmed).label("total_confirmed"),
            )
            .where(tbl.c.campaign_id == campaign_id)
            .group_by(tbl.c.currency)
        )
        with self._session_factory() as session:
            rows = session.execute(stmt).fetchall()

        result: dict[str, dict[str, Decimal]] = {}
        for row in rows:
            currency = row._mapping["currency"]
            claimed = row._mapping["total_claimed"]
            confirmed = row._mapping["total_confirmed"]
            result[currency] = {
                "claimed": Decimal(str(claimed)) if claimed is not None else Decimal("0"),
                "confirmed": Decimal(str(confirmed)) if confirmed is not None else Decimal("0"),
            }
        return result
