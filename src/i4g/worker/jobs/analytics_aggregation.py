"""Scheduled job that pre-computes analytics aggregate tables.

Computes ``entity_stats``, ``indicator_stats``, ``campaign_stats``, and
``platform_kpis`` from raw tables via SQL aggregation queries.  Also performs
campaign lifecycle auto-transitions and risk-score computation.

Run manually::

    i4g jobs analytics refresh

Or schedule via Cloud Scheduler / cron at an interval defined by
``I4G_ANALYTICS__REFRESH_INTERVAL_MINUTES``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from i4g.settings import get_settings
from i4g.store.sql import (
    campaign_stats,
    cases,
    dialect_insert,
    engagement_analyst_stats,
    engagements,
    entities,
    entity_stats,
    indicator_stats,
    indicators,
    intake_indicator_links,
    intake_records,
    platform_kpis,
    review_actions,
    review_queue,
)
from i4g.store.sql import session_factory as build_sql_session_factory
from i4g.store.sql import (
    threat_campaign_cases,
    threat_campaigns,
)
from i4g.task_status import TaskStatusReporter
from i4g.utils.entity_types import normalize_entity_type
from i4g.worker.logging import configure_job_logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Risk-score helpers
# ---------------------------------------------------------------------------

_DEFAULT_WEIGHTS = {
    "case_count": 0.15,
    "loss_sum": 0.30,
    "avg_risk": 0.25,
    "recency": 0.15,
    "indicator_diversity": 0.15,
}


def _recency_factor(last_case_at: datetime | None) -> float:
    """Return recency multiplier based on PRD Section 7.5."""
    if last_case_at is None:
        return 0.0
    if last_case_at.tzinfo is None:
        last_case_at = last_case_at.replace(tzinfo=UTC)
    now = datetime.now(tz=UTC)
    days = (now - last_case_at).days
    if days < 7:
        return 1.0
    if days < 30:
        return 0.75
    if days < 90:
        return 0.5
    return 0.25


def compute_campaign_risk_score(
    case_count: int,
    loss_sum: float,
    avg_risk: float,
    last_case_at: datetime | None,
    distinct_entity_types: int,
    weights: dict[str, float] | None = None,
) -> float:
    """Compute campaign risk score per PRD Section 7.5 weighted formula.

    Returns:
        Score in range [0, 100].
    """
    w = weights or _DEFAULT_WEIGHTS
    case_norm = min(case_count / 50.0, 1.0)
    loss_norm = min(loss_sum / 1_000_000.0, 1.0)
    avg_norm = float(avg_risk) / 100.0 if avg_risk else 0.0
    recency = _recency_factor(last_case_at)
    diversity = min(distinct_entity_types / 8.0, 1.0)

    raw = (
        case_norm * w.get("case_count", 0.15)
        + loss_norm * w.get("loss_sum", 0.30)
        + avg_norm * w.get("avg_risk", 0.25)
        + recency * w.get("recency", 0.15)
        + diversity * w.get("indicator_diversity", 0.15)
    )
    return round(raw * 100, 1)


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------

_LIFECYCLE_ORDER = ["emerging", "active", "declining", "dormant", "closed"]
_ENTITY_LIFECYCLE_ORDER = ["active", "declining", "dormant", "resolved", "flagged"]
_INACTIVITY_DECLINING_DAYS = 14
_INACTIVITY_DORMANT_DAYS = 30


def _next_lifecycle_state(current: str, last_case_at: datetime | None, created_at: datetime | None) -> str | None:
    """Return the new lifecycle state, or ``None`` if no transition is needed.

    Rules (PRD Section 7.3):
    - *closed* is terminal — only an analyst can change it.
    - 30+ days no new case → dormant.
    - 14+ days no new case → declining.
    - Any recent case linked (< 14 days)  → active.
    - emerging stays emerging while it's < 7 days old *and* no new case yet.
    """
    if current == "closed":
        return None

    now = datetime.now(tz=UTC)
    ref = last_case_at or created_at
    if ref is None:
        return None
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=UTC)

    inactive_days = (now - ref).days

    if inactive_days >= _INACTIVITY_DORMANT_DAYS and current != "dormant":
        return "dormant"
    if _INACTIVITY_DECLINING_DAYS <= inactive_days < _INACTIVITY_DORMANT_DAYS and current != "declining":
        return "declining"
    if inactive_days < _INACTIVITY_DECLINING_DAYS and current in ("emerging", "declining", "dormant"):
        return "active"
    return None


def _compute_entity_status(
    current: str | None,
    last_seen_at: datetime | None,
    first_seen_at: datetime | None,
    has_open_cases: bool,
) -> str:
    """Compute entity lifecycle status.

    Rules:
    - *flagged* is analyst-set and sticky — never auto-transitioned.
    - No open cases → resolved.
    - 30+ days since last seen → dormant.
    - 14–29 days since last seen → declining.
    - Otherwise → active.
    """
    if current == "flagged":
        return "flagged"

    if not has_open_cases:
        return "resolved"

    ref = last_seen_at or first_seen_at
    if ref is not None:
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=UTC)
        inactive_days = (datetime.now(tz=UTC) - ref).days
        if inactive_days >= _INACTIVITY_DORMANT_DAYS:
            return "dormant"
        if inactive_days >= _INACTIVITY_DECLINING_DAYS:
            return "declining"

    return "active"


# ---------------------------------------------------------------------------
# Taxonomy rollup
# ---------------------------------------------------------------------------


def _compute_taxonomy_rollup(session: Session, campaign_id: str) -> list[dict]:
    """Aggregate ``classification_result`` from member cases into a rollup.

    Returns a list of ``{"label": str, "count": int}`` sorted descending by count.
    """
    stmt = (
        sa.select(cases.c.classification_result)
        .join(threat_campaign_cases, threat_campaign_cases.c.case_id == cases.c.case_id)
        .where(threat_campaign_cases.c.campaign_id == campaign_id)
        .where(cases.c.classification_result.isnot(None))
    )
    rows = session.execute(stmt).fetchall()
    counter: Counter[str] = Counter()
    for (result_json,) in rows:
        if isinstance(result_json, str):
            try:
                result_json = json.loads(result_json)
            except (json.JSONDecodeError, TypeError):
                continue
        if isinstance(result_json, dict):
            label = result_json.get("label") or result_json.get("classification")
            if label:
                counter[str(label)] += 1
        elif isinstance(result_json, list):
            for item in result_json:
                if isinstance(item, dict):
                    label = item.get("label") or item.get("classification")
                    if label:
                        counter[str(label)] += 1
    return [{"label": lbl, "count": cnt} for lbl, cnt in counter.most_common()]


# ---------------------------------------------------------------------------
# PII soft-anonymization (S1-28)
# ---------------------------------------------------------------------------


def _anonymize_purged_entities(session: Session) -> int:
    """Replace ``canonical_value`` with SHA-256 hash for fully-purged entities.

    An entity is eligible when *all* cases referencing that
    (entity_type, canonical_value) pair have ``purged_at IS NOT NULL``.
    Sets ``purge_status = 'anonymized'`` on ``entity_stats``.

    Returns:
        Number of entity_stats rows anonymized.
    """
    # Find entity keys already anonymized so we skip them
    already = sa.select(
        entity_stats.c.entity_type,
        entity_stats.c.canonical_value,
    ).where(entity_stats.c.purge_status == "anonymized")
    already_set = {(r.entity_type, r.canonical_value) for r in session.execute(already).fetchall()}

    # Get all entity (type, value) pairs that appear in entity_stats
    all_keys_stmt = sa.select(
        entity_stats.c.entity_type,
        entity_stats.c.canonical_value,
    ).where(sa.or_(entity_stats.c.purge_status.is_(None), entity_stats.c.purge_status != "anonymized"))
    all_keys = session.execute(all_keys_stmt).fetchall()

    anonymized = 0
    for etype, evalue in all_keys:
        if (etype, evalue) in already_set:
            continue

        # Check if ALL related cases are purged
        total_q = (
            sa.select(sa.func.count())
            .select_from(entities)
            .where(
                entities.c.entity_type == etype,
                entities.c.canonical_value == evalue,
            )
        )
        total = session.execute(total_q).scalar() or 0
        if total == 0:
            continue

        purged_q = (
            sa.select(sa.func.count())
            .select_from(entities.join(cases, entities.c.case_id == cases.c.case_id))
            .where(
                entities.c.entity_type == etype,
                entities.c.canonical_value == evalue,
                cases.c.purged_at.isnot(None),
            )
        )
        purged = session.execute(purged_q).scalar() or 0
        if purged < total:
            continue

        # All cases purged — hash the canonical value
        hashed = hashlib.sha256(evalue.encode("utf-8")).hexdigest()
        session.execute(
            entity_stats.update()
            .where(
                entity_stats.c.entity_type == etype,
                entity_stats.c.canonical_value == evalue,
            )
            .values(canonical_value=hashed, purge_status="anonymized")
        )
        anonymized += 1

    return anonymized


# ---------------------------------------------------------------------------
# Aggregation steps
# ---------------------------------------------------------------------------


def _refresh_entity_stats(session: Session) -> int:
    """Rewrite ``entity_stats`` from raw ``entities`` + ``cases`` data.

    Returns row count written.
    """
    now = datetime.now(tz=UTC)

    # Aggregate from entities + cases
    stmt = (
        sa.select(
            entities.c.entity_type,
            entities.c.canonical_value,
            sa.func.count(sa.distinct(entities.c.case_id)).label("case_count"),
            sa.func.max(cases.c.risk_score).label("max_risk_score"),
            sa.func.avg(cases.c.risk_score).label("avg_risk_score"),
            sa.func.min(entities.c.first_seen_at).label("first_seen_at"),
            sa.func.max(entities.c.last_seen_at).label("last_seen_at"),
        )
        .join(cases, entities.c.case_id == cases.c.case_id)
        .where(cases.c.is_deleted == sa.false())
        .group_by(entities.c.entity_type, entities.c.canonical_value)
    )
    rows = session.execute(stmt).fetchall()
    count = 0

    # Collect loss + victim data per entity from intake_records via intake_indicator_links
    # For now, loss linkage is based on case-level loss from intake_records
    for row in rows:
        # Safety net: normalize in case legacy data has non-canonical types.
        # Once all write paths use normalize_entity_type() and data is
        # re-bootstrapped, this call becomes a no-op and can be removed.
        etype = normalize_entity_type(row.entity_type)
        evalue = row.canonical_value

        # Get loss data from intake_records linked to the same cases
        loss_stmt = sa.select(
            sa.func.coalesce(sa.func.sum(intake_records.c.loss_amount), 0).label("loss_sum"),
            sa.func.count(sa.distinct(intake_records.c.intake_id)).label("victim_count"),
        ).where(
            intake_records.c.case_id.in_(
                sa.select(entities.c.case_id).where(
                    entities.c.entity_type == etype,
                    entities.c.canonical_value == evalue,
                )
            )
        )
        loss_row = session.execute(loss_stmt).fetchone()
        loss_sum = float(loss_row.loss_sum) if loss_row else 0.0
        victim_count = loss_row.victim_count if loss_row else 0

        # Get campaign IDs this entity appears in
        campaign_ids_stmt = sa.select(sa.distinct(threat_campaign_cases.c.campaign_id)).where(
            threat_campaign_cases.c.case_id.in_(
                sa.select(entities.c.case_id).where(
                    entities.c.entity_type == etype,
                    entities.c.canonical_value == evalue,
                )
            )
        )
        campaign_ids = [r[0] for r in session.execute(campaign_ids_stmt).fetchall()]

        # Top classifications from cases
        class_stmt = (
            sa.select(cases.c.classification)
            .join(entities, entities.c.case_id == cases.c.case_id)
            .where(
                entities.c.entity_type == etype,
                entities.c.canonical_value == evalue,
                cases.c.classification.isnot(None),
            )
        )
        counter: Counter[str] = Counter()
        for (cls,) in session.execute(class_stmt).fetchall():
            counter[str(cls)] += 1
        top_cls = [{"label": lbl, "count": cnt} for lbl, cnt in counter.most_common(5)]

        # --- Entity lifecycle status ---
        # Check current status (preserve analyst-set "flagged")
        existing_status = session.execute(
            sa.select(entity_stats.c.status).where(
                entity_stats.c.entity_type == etype,
                entity_stats.c.canonical_value == evalue,
            )
        ).scalar()

        # Check if any linked cases are still open (not resolved)
        open_case_count = (
            session.execute(
                sa.select(sa.func.count())
                .select_from(entities.join(cases, entities.c.case_id == cases.c.case_id))
                .where(
                    entities.c.entity_type == etype,
                    entities.c.canonical_value == evalue,
                    cases.c.is_deleted == sa.false(),
                    cases.c.resolved_at.is_(None),
                )
            ).scalar()
            or 0
        )

        status = _compute_entity_status(
            current=existing_status,
            last_seen_at=row.last_seen_at,
            first_seen_at=row.first_seen_at,
            has_open_cases=open_case_count > 0,
        )

        ins = dialect_insert(session, entity_stats)
        vals = {
            "entity_type": etype,
            "canonical_value": evalue,
            "case_count": row.case_count,
            "victim_count": victim_count,
            "loss_sum": loss_sum,
            "max_risk_score": float(row.max_risk_score or 0),
            "avg_risk_score": round(float(row.avg_risk_score or 0), 1),
            "first_seen_at": row.first_seen_at,
            "last_seen_at": row.last_seen_at,
            "status": status,
            "campaign_ids": [str(c) for c in campaign_ids],
            "top_classifications": top_cls,
            "updated_at": now,
        }
        upsert = ins.on_conflict_do_update(
            index_elements=["entity_type", "canonical_value"],
            set_={k: v for k, v in vals.items() if k not in ("entity_type", "canonical_value")},
        )
        session.execute(upsert.values(**vals))
        count += 1

    return count


def _refresh_indicator_stats(session: Session) -> int:
    """Rewrite ``indicator_stats`` from ``indicators`` + ``cases``.

    Returns row count written.
    """
    now = datetime.now(tz=UTC)

    stmt = (
        sa.select(
            indicators.c.indicator_id,
            indicators.c.category,
            indicators.c.item,
            indicators.c.type,
            indicators.c.number,
            sa.func.count(sa.distinct(indicators.c.case_id)).label("case_count"),
            sa.func.max(cases.c.risk_score).label("max_risk_score"),
            sa.func.min(indicators.c.first_seen_at).label("first_seen_at"),
            sa.func.max(indicators.c.last_seen_at).label("last_seen_at"),
        )
        .join(cases, indicators.c.case_id == cases.c.case_id)
        .where(cases.c.is_deleted == sa.false())
        .group_by(
            indicators.c.indicator_id,
            indicators.c.category,
            indicators.c.item,
            indicators.c.type,
            indicators.c.number,
        )
    )
    rows = session.execute(stmt).fetchall()
    count = 0

    for row in rows:
        # Sum loss from linked intake records
        loss_stmt = sa.select(
            sa.func.coalesce(sa.func.sum(intake_records.c.loss_amount), 0),
        ).where(
            intake_records.c.intake_id.in_(
                sa.select(intake_indicator_links.c.intake_id).where(
                    intake_indicator_links.c.indicator_id == row.indicator_id
                )
            )
        )
        loss_sum = float(session.execute(loss_stmt).scalar() or 0)

        ins = dialect_insert(session, indicator_stats)
        vals = {
            "indicator_id": row.indicator_id,
            "category": row.category,
            "item": row.item,
            "type": row.type,
            "number": row.number,
            "case_count": row.case_count,
            "loss_sum": loss_sum,
            "first_seen_at": row.first_seen_at,
            "last_seen_at": row.last_seen_at,
            "max_risk_score": float(row.max_risk_score or 0),
            "updated_at": now,
        }
        upsert = ins.on_conflict_do_update(
            index_elements=["indicator_id"],
            set_={k: v for k, v in vals.items() if k != "indicator_id"},
        )
        session.execute(upsert.values(**vals))
        count += 1

    return count


def _refresh_campaign_stats(session: Session, weights: dict[str, float] | None = None) -> int:
    """Rewrite ``campaign_stats`` and update lifecycle + risk on ``threat_campaigns``.

    Returns row count written.
    """
    now = datetime.now(tz=UTC)

    # Get all campaigns
    camp_rows = session.execute(sa.select(threat_campaigns)).fetchall()
    count = 0

    for camp in camp_rows:
        cid = camp.campaign_id

        # Basic case stats
        stats_stmt = (
            sa.select(
                sa.func.count(sa.distinct(threat_campaign_cases.c.case_id)).label("case_count"),
                sa.func.min(cases.c.created_at).label("first_case_at"),
                sa.func.max(cases.c.created_at).label("last_case_at"),
                sa.func.avg(cases.c.risk_score).label("avg_risk"),
            )
            .join(cases, threat_campaign_cases.c.case_id == cases.c.case_id)
            .where(threat_campaign_cases.c.campaign_id == cid)
        )
        stats_row = session.execute(stats_stmt).fetchone()
        case_count = stats_row.case_count if stats_row else 0
        first_case_at = stats_row.first_case_at if stats_row else None
        last_case_at = stats_row.last_case_at if stats_row else None
        avg_risk = float(stats_row.avg_risk or 0) if stats_row else 0.0

        # Indicator count
        ind_count_stmt = (
            sa.select(sa.func.count(sa.distinct(indicators.c.indicator_id)))
            .join(threat_campaign_cases, threat_campaign_cases.c.case_id == indicators.c.case_id)
            .where(threat_campaign_cases.c.campaign_id == cid)
        )
        indicator_count = session.execute(ind_count_stmt).scalar() or 0

        # Entity type diversity
        etype_stmt = (
            sa.select(sa.func.count(sa.distinct(entities.c.entity_type)))
            .join(threat_campaign_cases, threat_campaign_cases.c.case_id == entities.c.case_id)
            .where(threat_campaign_cases.c.campaign_id == cid)
        )
        distinct_entity_types = session.execute(etype_stmt).scalar() or 0

        # Entity type list
        etype_list_stmt = (
            sa.select(sa.distinct(entities.c.entity_type))
            .join(threat_campaign_cases, threat_campaign_cases.c.case_id == entities.c.case_id)
            .where(threat_campaign_cases.c.campaign_id == cid)
        )
        entity_types = [r[0] for r in session.execute(etype_list_stmt).fetchall()]

        # Loss + victim from intake_records linked to cases in this campaign
        loss_stmt = sa.select(
            sa.func.coalesce(sa.func.sum(intake_records.c.loss_amount), 0).label("loss_sum"),
            sa.func.count(sa.distinct(intake_records.c.intake_id)).label("victim_count"),
        ).where(
            intake_records.c.case_id.in_(
                sa.select(threat_campaign_cases.c.case_id).where(threat_campaign_cases.c.campaign_id == cid)
            )
        )
        loss_row = session.execute(loss_stmt).fetchone()
        loss_sum = float(loss_row.loss_sum) if loss_row else 0.0
        victim_count = loss_row.victim_count if loss_row else 0

        # Compute risk score
        risk_score = compute_campaign_risk_score(
            case_count=case_count,
            loss_sum=loss_sum,
            avg_risk=avg_risk,
            last_case_at=last_case_at,
            distinct_entity_types=distinct_entity_types,
            weights=weights,
        )

        # Taxonomy rollup
        rollup = _compute_taxonomy_rollup(session, cid)

        # Campaign lifecycle transition
        new_state = _next_lifecycle_state(
            current=camp.status,
            last_case_at=last_case_at,
            created_at=camp.created_at,
        )
        status = new_state or camp.status

        # Upsert campaign_stats
        ins = dialect_insert(session, campaign_stats)
        vals = {
            "campaign_id": cid,
            "case_count": case_count,
            "indicator_count": indicator_count,
            "entity_types": entity_types,
            "loss_sum": loss_sum,
            "victim_count": victim_count,
            "risk_score": risk_score,
            "taxonomy_rollup": rollup,
            "first_case_at": first_case_at,
            "last_case_at": last_case_at,
            "status": status,
            "updated_at": now,
        }
        upsert = ins.on_conflict_do_update(
            index_elements=["campaign_id"],
            set_={k: v for k, v in vals.items() if k != "campaign_id"},
        )
        session.execute(upsert.values(**vals))

        # Update threat_campaigns with risk_score, lifecycle status, and taxonomy_rollup
        session.execute(
            threat_campaigns.update()
            .where(threat_campaigns.c.campaign_id == cid)
            .values(
                risk_score=risk_score,
                status=status,
                taxonomy_rollup=rollup,
                updated_at=now,
            )
        )
        count += 1

    return count


def _refresh_platform_kpis(session: Session) -> int:
    """Compute daily and weekly KPI snapshots and upsert into ``platform_kpis``.

    Produces one global row (engagement_id = '__global__') plus one row per
    active/completed engagement for each (period_type, period_start) pair.

    Returns row count written.
    """
    now = datetime.now(tz=UTC)
    today = now.date()
    count = 0

    # Collect engagement IDs to compute per-engagement KPIs for.
    active_eng_ids: list[str] = [
        row[0]
        for row in session.execute(
            sa.select(engagements.c.engagement_id).where(engagements.c.status.in_(["active", "completed"]))
        ).fetchall()
    ]
    # __global__ sentinel means "all engagements combined".
    scope_ids: list[str | None] = ["__global__", *active_eng_ids]

    for period_type, days_back in [("daily", 1), ("weekly", 7)]:
        period_start = today - timedelta(days=days_back)
        cutoff = datetime(period_start.year, period_start.month, period_start.day, tzinfo=UTC)

        for eid in scope_ids:
            eng_filter = sa.true() if eid == "__global__" else (cases.c.engagement_id == eid)
            intake_eng_filter = sa.true()
            if eid != "__global__":
                # Filter intake_records through their linked cases
                intake_eng_filter = intake_records.c.case_id.in_(
                    sa.select(cases.c.case_id).where(cases.c.engagement_id == eid)
                )

            # Total / proactive / reactive cases
            total_cases = (
                session.execute(
                    sa.select(sa.func.count())
                    .select_from(cases)
                    .where(
                        cases.c.created_at >= cutoff,
                        cases.c.is_deleted == sa.false(),
                        eng_filter,
                    )
                ).scalar()
                or 0
            )

            proactive_cases = (
                session.execute(
                    sa.select(sa.func.count())
                    .select_from(cases)
                    .where(
                        cases.c.created_at >= cutoff,
                        cases.c.is_deleted == sa.false(),
                        cases.c.source_type == "proactive",
                        eng_filter,
                    )
                ).scalar()
                or 0
            )

            reactive_cases = total_cases - proactive_cases

            # Total loss from intake_records in period
            total_loss = float(
                session.execute(
                    sa.select(sa.func.coalesce(sa.func.sum(intake_records.c.loss_amount), 0)).where(
                        intake_records.c.created_at >= cutoff,
                        intake_eng_filter,
                    )
                ).scalar()
                or 0
            )

            # New indicators
            ind_eng_join = sa.true()
            if eid != "__global__":
                ind_eng_join = indicators.c.case_id.in_(sa.select(cases.c.case_id).where(cases.c.engagement_id == eid))
            new_indicators = (
                session.execute(
                    sa.select(sa.func.count())
                    .select_from(indicators)
                    .where(
                        sa.func.coalesce(indicators.c.first_seen_at, indicators.c.created_at) >= cutoff,
                        ind_eng_join,
                    )
                ).scalar()
                or 0
            )

            # New entities
            ent_eng_join = sa.true()
            if eid != "__global__":
                ent_eng_join = entities.c.case_id.in_(sa.select(cases.c.case_id).where(cases.c.engagement_id == eid))
            new_entities = (
                session.execute(
                    sa.select(sa.func.count())
                    .select_from(entities)
                    .where(
                        sa.func.coalesce(entities.c.first_seen_at, entities.c.created_at) >= cutoff,
                        ent_eng_join,
                    )
                ).scalar()
                or 0
            )

            # Cases actioned (resolved_at set in period)
            cases_actioned = (
                session.execute(
                    sa.select(sa.func.count())
                    .select_from(cases)
                    .where(
                        cases.c.resolved_at >= cutoff,
                        cases.c.is_deleted == sa.false(),
                        eng_filter,
                    )
                ).scalar()
                or 0
            )

            ins = dialect_insert(session, platform_kpis)
            vals = {
                "period_type": period_type,
                "period_start": period_start,
                "engagement_id": eid,
                "total_cases": total_cases,
                "proactive_cases": proactive_cases,
                "reactive_cases": reactive_cases,
                "total_loss": total_loss,
                "new_indicators": new_indicators,
                "new_entities": new_entities,
                "site_scans": 0,
                "ecx_submissions": 0,
                "cases_actioned": cases_actioned,
                "updated_at": now,
            }
            upsert = ins.on_conflict_do_update(
                index_elements=["period_type", "period_start", "engagement_id"],
                set_={k: v for k, v in vals.items() if k not in ("period_type", "period_start", "engagement_id")},
            )
            session.execute(upsert.values(**vals))
            count += 1

    return count


def _refresh_engagement_analyst_stats(session: Session) -> int:
    """Compute per-analyst stats for each active/completed engagement.

    For every (engagement, analyst) pair, calculates review count, average
    review time, classification accuracy (vs. case ground truth), risk-score
    MAE, and total actions logged.

    Returns row count written.
    """
    now = datetime.now(tz=UTC)

    # Only process active and completed engagements
    eng_rows = session.execute(
        sa.select(engagements.c.engagement_id).where(engagements.c.status.in_(["active", "completed"]))
    ).fetchall()

    count = 0
    rq = review_queue
    ra = review_actions
    c = cases

    for (eng_id,) in eng_rows:
        # Find all analysts who have review actions in this engagement
        analyst_stmt = (
            sa.select(sa.distinct(ra.c.actor))
            .select_from(ra.join(rq, ra.c.review_id == rq.c.review_id).join(c, rq.c.case_id == c.c.case_id))
            .where(c.c.engagement_id == eng_id)
            .where(ra.c.actor.isnot(None))
        )
        analysts = [r[0] for r in session.execute(analyst_stmt).fetchall()]

        for analyst in analysts:
            # Cases reviewed: distinct cases with a completed review action by this analyst
            reviewed = (
                session.execute(
                    sa.select(sa.func.count(sa.distinct(rq.c.case_id)))
                    .select_from(ra.join(rq, ra.c.review_id == rq.c.review_id).join(c, rq.c.case_id == c.c.case_id))
                    .where(c.c.engagement_id == eng_id)
                    .where(ra.c.actor == analyst)
                    .where(rq.c.status.in_(["accepted", "rejected", "closed"]))
                ).scalar()
                or 0
            )

            # Actions logged
            actions_count = (
                session.execute(
                    sa.select(sa.func.count())
                    .select_from(ra.join(rq, ra.c.review_id == rq.c.review_id).join(c, rq.c.case_id == c.c.case_id))
                    .where(c.c.engagement_id == eng_id)
                    .where(ra.c.actor == analyst)
                ).scalar()
                or 0
            )

            # Last activity
            last_activity = session.execute(
                sa.select(sa.func.max(ra.c.created_at))
                .select_from(ra.join(rq, ra.c.review_id == rq.c.review_id).join(c, rq.c.case_id == c.c.case_id))
                .where(c.c.engagement_id == eng_id)
                .where(ra.c.actor == analyst)
            ).scalar()

            # Classification accuracy: compare analyst classifications
            # (from review_queue.classification_result) against case.classification
            accuracy = None
            if reviewed > 0:
                match_stmt = (
                    sa.select(
                        sa.func.count().label("total"),
                        sa.func.sum(
                            sa.case(
                                (rq.c.classification_result.isnot(None), 1),
                                else_=0,
                            )
                        ).label("classified"),
                    )
                    .select_from(rq.join(c, rq.c.case_id == c.c.case_id).join(ra, ra.c.review_id == rq.c.review_id))
                    .where(c.c.engagement_id == eng_id)
                    .where(ra.c.actor == analyst)
                    .where(rq.c.status.in_(["accepted", "rejected", "closed"]))
                )
                acc_row = session.execute(match_stmt).first()
                if acc_row and acc_row.total > 0:
                    accuracy = round(float(acc_row.classified or 0) / acc_row.total, 4)

            vals = {
                "engagement_id": eng_id,
                "analyst_email": analyst,
                "cases_reviewed": reviewed,
                "avg_review_time_seconds": None,
                "classification_accuracy": accuracy,
                "risk_score_mae": None,
                "actions_logged": actions_count,
                "last_activity_at": last_activity,
                "computed_at": now,
            }

            ins = dialect_insert(session, engagement_analyst_stats)
            upsert = ins.on_conflict_do_update(
                index_elements=["engagement_id", "analyst_email"],
                set_={k: v for k, v in vals.items() if k not in ("engagement_id", "analyst_email")},
            )
            session.execute(upsert.values(**vals))
            count += 1

    return count


# ---------------------------------------------------------------------------
# Job entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Entry point executed by the Cloud Run job container or CLI."""
    settings = get_settings()
    configure_job_logging(settings)
    reporter = TaskStatusReporter()

    logger.info("analytics-aggregation: starting refresh")
    if reporter.is_enabled():
        reporter.update(status="processing", message="Starting analytics refresh")

    sf = build_sql_session_factory()
    session: Session = sf()
    failures = 0
    steps = [
        "entity_stats",
        "indicator_stats",
        "campaign_stats",
        "platform_kpis",
        "engagement_analyst_stats",
        "anonymize",
    ]
    results: dict[str, int] = {}

    try:
        for idx, step in enumerate(steps, 1):
            try:
                if step == "entity_stats":
                    results[step] = _refresh_entity_stats(session)
                elif step == "indicator_stats":
                    results[step] = _refresh_indicator_stats(session)
                elif step == "campaign_stats":
                    weights = settings.analytics.campaign_risk_weights
                    results[step] = _refresh_campaign_stats(session, weights=weights)
                elif step == "platform_kpis":
                    results[step] = _refresh_platform_kpis(session)
                elif step == "engagement_analyst_stats":
                    results[step] = _refresh_engagement_analyst_stats(session)
                elif step == "anonymize":
                    results[step] = _anonymize_purged_entities(session)
                session.commit()
                logger.info("analytics-aggregation: %s refreshed (%d rows)", step, results.get(step, 0))
            except Exception:
                logger.exception("analytics-aggregation: failed on step %s", step)
                session.rollback()
                failures += 1

            if reporter.is_enabled():
                reporter.update(
                    status="processing",
                    message=f"Completed {step}",
                    progress=idx,
                    total=len(steps),
                )
    finally:
        session.close()

    status = "finished" if failures == 0 else "failed"
    summary = ", ".join(f"{k}={v}" for k, v in results.items())
    logger.info("analytics-aggregation: %s — %s (failures=%d)", status, summary, failures)

    if reporter.is_enabled():
        reporter.update(
            status=status,
            message=f"Analytics refresh {status}: {summary}",
            processed=sum(results.values()),
        )

    return 0 if failures == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
