"""BigQuery export job — sync aggregate tables from Cloud SQL to BigQuery.

Exports the following tables with the ``engagement_id`` dimension intact:

- ``platform_kpis`` (global + per-engagement daily/weekly KPIs)
- ``entity_stats``
- ``indicator_stats``
- ``campaign_stats``
- ``engagement_analyst_stats``
- ``engagements`` (metadata for join context in Looker)

Run manually::

    i4g jobs bq-export

Or schedule via Cloud Scheduler targeting ``I4G_BQ_EXPORT__*`` env vars.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from i4g.settings import get_settings
from i4g.store.sql import (
    campaign_stats,
    engagement_analyst_stats,
    engagements,
    entity_stats,
    indicator_stats,
    platform_kpis,
)
from i4g.store.sql import session_factory as build_sql_session_factory
from i4g.task_status import TaskStatusReporter
from i4g.worker.logging import configure_job_logging

if TYPE_CHECKING:
    from google.cloud import bigquery

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Table export definitions
# ---------------------------------------------------------------------------

# Each entry maps a Cloud SQL source table to a BigQuery table name and the
# column list to transfer.  Column order must match the BQ schema.

_EXPORT_TABLES: list[dict[str, Any]] = [
    {
        "source": engagements,
        "bq_table": "engagements",
        "columns": [
            "engagement_id",
            "name",
            "description",
            "status",
            "starts_at",
            "ends_at",
            "created_by",
            "created_at",
            "updated_at",
        ],
    },
    {
        "source": platform_kpis,
        "bq_table": "platform_kpis",
        "columns": [
            "period_type",
            "period_start",
            "engagement_id",
            "total_cases",
            "proactive_cases",
            "reactive_cases",
            "total_loss",
            "new_indicators",
            "new_entities",
            "site_scans",
            "ecx_submissions",
            "cases_actioned",
            "median_action_hours",
            "updated_at",
        ],
    },
    {
        "source": entity_stats,
        "bq_table": "entity_stats",
        "columns": [
            "entity_type",
            "canonical_value",
            "case_count",
            "victim_count",
            "loss_sum",
            "loss_currency",
            "max_risk_score",
            "avg_risk_score",
            "first_seen_at",
            "last_seen_at",
            "status",
            "top_classifications",
            "ecx_submitted",
            "ecx_hit",
            "updated_at",
        ],
    },
    {
        "source": indicator_stats,
        "bq_table": "indicator_stats",
        "columns": [
            "indicator_id",
            "category",
            "item",
            "type",
            "number",
            "case_count",
            "loss_sum",
            "first_seen_at",
            "last_seen_at",
            "max_risk_score",
            "ecx_status",
            "updated_at",
        ],
    },
    {
        "source": campaign_stats,
        "bq_table": "campaign_stats",
        "columns": [
            "campaign_id",
            "case_count",
            "indicator_count",
            "loss_sum",
            "victim_count",
            "risk_score",
            "first_case_at",
            "last_case_at",
            "status",
            "updated_at",
        ],
    },
    {
        "source": engagement_analyst_stats,
        "bq_table": "engagement_analyst_stats",
        "columns": [
            "engagement_id",
            "analyst_email",
            "cases_reviewed",
            "avg_review_time_seconds",
            "classification_accuracy",
            "risk_score_mae",
            "actions_logged",
            "last_activity_at",
            "computed_at",
        ],
    },
]


# ---------------------------------------------------------------------------
# BigQuery helpers
# ---------------------------------------------------------------------------


def _get_bq_client(project_id: str) -> bigquery.Client:
    """Return a BigQuery client for the given project."""
    from google.cloud import bigquery as bq

    return bq.Client(project=project_id)


def _export_table(
    session: Session,
    bq_client: bigquery.Client,
    dataset_id: str,
    spec: dict[str, Any],
) -> int:
    """Read rows from Cloud SQL and write to BigQuery via streaming inserts.

    Uses WRITE_TRUNCATE (full replace) per table for idempotent runs.

    Returns the number of rows exported.
    """
    from google.cloud import bigquery as bq

    source_table = spec["source"]
    bq_table_name = spec["bq_table"]
    columns = spec["columns"]

    col_objects = [source_table.c[col_name] for col_name in columns]
    rows = session.execute(sa.select(*col_objects)).fetchall()

    if not rows:
        logger.info("bq-export: %s — 0 rows, skipping", bq_table_name)
        return 0

    table_ref = f"{bq_client.project}.{dataset_id}.{bq_table_name}"

    # Convert Row objects to dicts, serializing non-JSON-native types.
    json_rows: list[dict[str, Any]] = []
    for row in rows:
        record: dict[str, Any] = {}
        for col_name, value in zip(columns, row, strict=True):
            if isinstance(value, datetime) or hasattr(value, "isoformat"):
                record[col_name] = value.isoformat()
            elif value is None:
                record[col_name] = None
            else:
                record[col_name] = value
            # Coerce Decimal to float for BQ JSON serialization
            if hasattr(record[col_name], "as_integer_ratio"):
                record[col_name] = float(record[col_name])
        json_rows.append(record)

    # Use load_table_from_json with WRITE_TRUNCATE for idempotency.
    job_config = bq.LoadJobConfig(write_disposition=bq.WriteDisposition.WRITE_TRUNCATE)
    load_job = bq_client.load_table_from_json(json_rows, table_ref, job_config=job_config)
    load_job.result()  # Wait for completion

    logger.info("bq-export: %s — %d rows exported", bq_table_name, len(json_rows))
    return len(json_rows)


# ---------------------------------------------------------------------------
# Dry-run mode (for local testing without BQ credentials)
# ---------------------------------------------------------------------------


def _dry_run_export(session: Session) -> dict[str, int]:
    """Simulate export by reading row counts from each source table."""
    results: dict[str, int] = {}
    for spec in _EXPORT_TABLES:
        source_table = spec["source"]
        count = session.execute(sa.select(sa.func.count()).select_from(source_table)).scalar() or 0
        results[spec["bq_table"]] = count
        logger.info("bq-export [dry-run]: %s — %d rows would be exported", spec["bq_table"], count)
    return results


# ---------------------------------------------------------------------------
# Cross-engagement analytics queries (used by comparison API)
# ---------------------------------------------------------------------------


def get_cross_engagement_kpis(session: Session) -> list[dict[str, Any]]:
    """Return per-engagement KPI summaries from ``platform_kpis``.

    Groups by engagement_id and returns the latest weekly snapshot for each.
    Excludes the ``__global__`` sentinel.
    """
    pk = platform_kpis
    eng = engagements

    stmt = (
        sa.select(
            pk.c.engagement_id,
            eng.c.name.label("engagement_name"),
            eng.c.status.label("engagement_status"),
            eng.c.starts_at,
            eng.c.ends_at,
            eng.c.metadata.label("engagement_metadata"),
            pk.c.total_cases,
            pk.c.proactive_cases,
            pk.c.reactive_cases,
            pk.c.total_loss,
            pk.c.new_indicators,
            pk.c.new_entities,
            pk.c.cases_actioned,
            pk.c.period_start,
        )
        .select_from(pk.join(eng, pk.c.engagement_id == eng.c.engagement_id))
        .where(pk.c.engagement_id != "__global__")
        .where(pk.c.period_type == "weekly")
        .order_by(pk.c.engagement_id, pk.c.period_start.desc())
    )

    rows = session.execute(stmt).fetchall()

    # Deduplicate: keep only the latest period_start for each engagement
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for row in rows:
        eid = row.engagement_id
        if eid in seen:
            continue
        seen.add(eid)
        results.append(dict(row._mapping))

    return results


def get_semester_trends(session: Session, engagement_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Return weekly KPI time series for specified (or all) engagements.

    Returns rows ordered by engagement_id, period_start — suitable for
    semester-over-semester trend visualization in Looker.
    """
    pk = platform_kpis
    eng = engagements

    stmt = (
        sa.select(
            pk.c.engagement_id,
            eng.c.name.label("engagement_name"),
            pk.c.period_type,
            pk.c.period_start,
            pk.c.total_cases,
            pk.c.proactive_cases,
            pk.c.reactive_cases,
            pk.c.total_loss,
            pk.c.new_indicators,
            pk.c.new_entities,
            pk.c.cases_actioned,
        )
        .select_from(pk.join(eng, pk.c.engagement_id == eng.c.engagement_id))
        .where(pk.c.engagement_id != "__global__")
        .where(pk.c.period_type == "weekly")
        .order_by(pk.c.engagement_id, pk.c.period_start)
    )

    if engagement_ids:
        stmt = stmt.where(pk.c.engagement_id.in_(engagement_ids))

    rows = session.execute(stmt).fetchall()
    return [dict(r._mapping) for r in rows]


def get_university_comparison(session: Session) -> list[dict[str, Any]]:
    """Return per-university engagement stats for partnership comparison reports.

    Extracts ``university`` from ``engagements.metadata`` (JSON field) and
    aggregates KPIs across engagements belonging to the same university.
    """
    # Step 1: Get latest weekly KPI for each engagement along with metadata
    eng_kpis = get_cross_engagement_kpis(session)

    # Step 2: Group by university from metadata
    from collections import defaultdict

    uni_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in eng_kpis:
        meta = row.get("engagement_metadata") or {}
        university = meta.get("university", "Unknown")
        uni_groups[university].append(row)

    # Step 3: Aggregate per university
    results: list[dict[str, Any]] = []
    for university, engs in sorted(uni_groups.items()):
        total_cases = sum(e.get("total_cases", 0) for e in engs)
        total_loss = sum(float(e.get("total_loss", 0)) for e in engs)
        total_indicators = sum(e.get("new_indicators", 0) for e in engs)
        total_entities = sum(e.get("new_entities", 0) for e in engs)
        cases_actioned = sum(e.get("cases_actioned", 0) for e in engs)

        results.append(
            {
                "university": university,
                "engagement_count": len(engs),
                "total_cases": total_cases,
                "total_loss": total_loss,
                "total_indicators": total_indicators,
                "total_entities": total_entities,
                "cases_actioned": cases_actioned,
                "engagements": [
                    {
                        "engagement_id": e["engagement_id"],
                        "name": e.get("engagement_name"),
                        "status": e.get("engagement_status"),
                    }
                    for e in engs
                ],
            }
        )

    return results


# ---------------------------------------------------------------------------
# Job entry point
# ---------------------------------------------------------------------------


def main(*, dry_run: bool = False) -> int:
    """Entry point executed by the Cloud Run job container or CLI."""
    settings = get_settings()
    configure_job_logging(settings)
    reporter = TaskStatusReporter()

    bq_settings = settings.bq_export
    if not bq_settings.enabled and not dry_run:
        logger.info("bq-export: disabled (I4G_BQ_EXPORT__ENABLED=false). Use --dry-run for local testing.")
        return 0

    logger.info("bq-export: starting export (dry_run=%s)", dry_run)
    if reporter.is_enabled():
        reporter.update(status="processing", message="Starting BigQuery export")

    sf = build_sql_session_factory()
    session: Session = sf()
    failures = 0
    results: dict[str, int] = {}

    try:
        if dry_run:
            results = _dry_run_export(session)
        else:
            bq_client = _get_bq_client(bq_settings.project_id)
            for idx, spec in enumerate(_EXPORT_TABLES, 1):
                try:
                    count = _export_table(session, bq_client, bq_settings.dataset_id, spec)
                    results[spec["bq_table"]] = count
                except Exception:
                    logger.exception("bq-export: failed on %s", spec["bq_table"])
                    failures += 1

                if reporter.is_enabled():
                    reporter.update(
                        status="processing",
                        message=f"Exported {spec['bq_table']}",
                        progress=idx,
                        total=len(_EXPORT_TABLES),
                    )
    finally:
        session.close()

    status = "finished" if failures == 0 else "failed"
    summary = ", ".join(f"{k}={v}" for k, v in results.items())
    logger.info("bq-export: %s — %s (failures=%d)", status, summary, failures)

    if reporter.is_enabled():
        reporter.update(
            status=status,
            message=f"BigQuery export {status}: {summary}",
            processed=sum(results.values()),
        )

    return 0 if failures == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
