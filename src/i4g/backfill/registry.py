"""Backfill task registry — defines and registers all backfill-eligible tasks.

Each task wraps an existing worker job entry point and adds:
- A human-readable name and description
- A pending-work query (how many items need processing)
- Lock TTL and scheduling hints
- The callable that does the actual work
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from i4g.store import sql as sql_schema

logger = logging.getLogger(__name__)


@dataclass
class BackfillTask:
    """Definition of a backfill-eligible task."""

    name: str
    description: str
    run_fn: Callable[..., int]
    pending_count_fn: Callable[[Session], int]
    lock_ttl_seconds: int = 3600
    default_kwargs: dict[str, Any] = field(default_factory=dict)
    envs: tuple[str, ...] = ("local", "dev", "prod")


# Global registry
_REGISTRY: dict[str, BackfillTask] = {}


def register(task: BackfillTask) -> None:
    """Register a backfill task."""
    _REGISTRY[task.name] = task


def get_task(name: str) -> BackfillTask:
    """Get a registered task by name.  Raises KeyError if not found."""
    _ensure_registered()
    return _REGISTRY[name]


def all_tasks() -> dict[str, BackfillTask]:
    """Return all registered tasks."""
    _ensure_registered()
    return dict(_REGISTRY)


# ---------------------------------------------------------------------------
# Pending-count queries
# ---------------------------------------------------------------------------


def _pending_classification(session: Session) -> int:
    """Count cases with classification_status='pending'."""
    result = session.execute(
        sa.select(sa.func.count())
        .select_from(sql_schema.cases)
        .where(
            sql_schema.cases.c.classification_status == "pending",
            sql_schema.cases.c.is_deleted.is_(False),
        )
    )
    return result.scalar() or 0


def _pending_ssi_investigation(session: Session) -> int:
    """Count URL indicators not linked to any investigation."""
    investigated_cases = sa.select(sa.distinct(sql_schema.case_investigations.c.case_id))
    result = session.execute(
        sa.select(sa.func.count())
        .select_from(
            sql_schema.indicators.join(
                sql_schema.cases,
                sql_schema.indicators.c.case_id == sql_schema.cases.c.case_id,
            )
        )
        .where(
            sql_schema.indicators.c.category == "url",
            sql_schema.indicators.c.type == "url",
            sql_schema.cases.c.dataset != "ssi",
            sql_schema.indicators.c.case_id.notin_(investigated_cases),
        )
    )
    return result.scalar() or 0


def _pending_analytics(_session: Session) -> int:
    """Analytics aggregation is always eligible (returns 1 to indicate runnable)."""
    return 1


def _pending_linkage(session: Session) -> int:
    """Count intakes without indicator links extracted."""
    try:
        linked_intakes = sa.select(sa.distinct(sql_schema.intake_indicator_links.c.intake_id))
        result = session.execute(
            sa.select(sa.func.count())
            .select_from(sql_schema.intake_records)
            .where(sql_schema.intake_records.c.intake_id.notin_(linked_intakes))
        )
        return result.scalar() or 0
    except Exception:
        return 0


def _pending_dossier(session: Session) -> int:
    """Count queued dossier jobs."""
    result = session.execute(
        sa.select(sa.func.count())
        .select_from(sql_schema.dossier_queue)
        .where(sql_schema.dossier_queue.c.status == "queued")
    )
    return result.scalar() or 0


def _pending_evidence_integrity(session: Session) -> int:
    """Count documents without file_sha256."""
    result = session.execute(
        sa.select(sa.func.count())
        .select_from(sql_schema.source_documents)
        .where(sql_schema.source_documents.c.file_sha256.is_(None))
    )
    return result.scalar() or 0


def _pending_ingest_retry(session: Session) -> int:
    """Count pending ingestion retry records."""
    result = session.execute(sa.select(sa.func.count()).select_from(sql_schema.ingestion_retry_queue))
    return result.scalar() or 0


# ---------------------------------------------------------------------------
# Registration (lazy — called on first access)
# ---------------------------------------------------------------------------

_registered = False


def _ensure_registered() -> None:
    global _registered
    if _registered:
        return
    _registered = True

    # Classification sweeper
    def _run_classify(**_kwargs: Any) -> int:
        from i4g.worker.jobs import classification_sweeper

        classification_sweeper.run()
        return 0

    register(
        BackfillTask(
            name="classify",
            description="Batch classify cases with classification_status='pending'",
            run_fn=_run_classify,
            pending_count_fn=_pending_classification,
            lock_ttl_seconds=3600,
        )
    )

    # SSI auto-investigation
    def _run_ssi(**kwargs: Any) -> int:
        from i4g.worker.jobs import auto_investigate

        return auto_investigate.main(
            dry_run=kwargs.get("dry_run", False),
            limit=kwargs.get("limit", 100),
        )

    register(
        BackfillTask(
            name="ssi",
            description="Trigger SSI investigations for uninvestigated URL indicators",
            run_fn=_run_ssi,
            pending_count_fn=_pending_ssi_investigation,
            lock_ttl_seconds=1800,
            default_kwargs={"limit": 100},
        )
    )

    # Analytics aggregation
    def _run_analytics(**_kwargs: Any) -> int:
        from i4g.worker.jobs import analytics_aggregation

        return analytics_aggregation.main()

    register(
        BackfillTask(
            name="analytics",
            description="Refresh pre-computed analytics aggregates, risk scores, and campaign stats",
            run_fn=_run_analytics,
            pending_count_fn=_pending_analytics,
            lock_ttl_seconds=1800,
        )
    )

    # Linkage extraction
    def _run_linkage(**kwargs: Any) -> int:
        from i4g.worker.jobs import linkage_extract

        return linkage_extract.main(
            backfill=kwargs.get("backfill", False),
            mode=kwargs.get("mode", "intake"),
        )

    register(
        BackfillTask(
            name="linkage",
            description="Extract indicator links from intake narratives via LLM",
            run_fn=_run_linkage,
            pending_count_fn=_pending_linkage,
            lock_ttl_seconds=3600,
        )
    )

    # Dossier queue
    def _run_dossier(**_kwargs: Any) -> int:
        from i4g.worker.jobs import dossier_queue

        return dossier_queue.main()

    register(
        BackfillTask(
            name="dossier",
            description="Process queued dossier generation jobs",
            run_fn=_run_dossier,
            pending_count_fn=_pending_dossier,
            lock_ttl_seconds=1800,
        )
    )

    # Evidence integrity
    def _run_evidence(**kwargs: Any) -> int:
        from i4g.worker.jobs import evidence_integrity

        return evidence_integrity.main(
            backfill=kwargs.get("backfill", True),
            limit=kwargs.get("limit"),
        )

    register(
        BackfillTask(
            name="evidence",
            description="Verify and backfill evidence file SHA-256 checksums",
            run_fn=_run_evidence,
            pending_count_fn=_pending_evidence_integrity,
            lock_ttl_seconds=1800,
            default_kwargs={"backfill": True},
        )
    )

    # Ingest retry
    def _run_ingest_retry(**_kwargs: Any) -> int:
        from i4g.worker.jobs import ingest_retry

        return ingest_retry.main()

    register(
        BackfillTask(
            name="ingest-retry",
            description="Retry failed ingestion records",
            run_fn=_run_ingest_retry,
            pending_count_fn=_pending_ingest_retry,
            lock_ttl_seconds=1800,
        )
    )
