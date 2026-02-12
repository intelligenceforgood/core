"""Cloud Run job for batch classification of pending cases."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Session

from i4g.services.factories import build_fraud_classifier
from i4g.settings import get_settings
from i4g.store import sql as sql_schema
from i4g.store.sql import session_factory as default_session_factory
from i4g.task_status import TaskStatusReporter
from i4g.taxonomy.models import FraudClassificationResult
from i4g.worker.logging import configure_job_logging

LOGGER = logging.getLogger("i4g.worker.jobs.classification_sweeper")


def run() -> None:
    """Execute the classification sweeper job."""
    settings = get_settings()
    configure_job_logging(settings)

    start_time = time.time()
    max_runtime_seconds = settings.sweep.max_runtime_seconds
    batch_size = settings.sweep.batch_size

    LOGGER.info(f"Starting classification sweeper (batch_size={batch_size}, timeout={max_runtime_seconds}s)")

    reporter = TaskStatusReporter()
    if reporter.is_enabled():
        reporter.update(
            status="started",
            message=f"Classification sweeper started (batch_size={batch_size})",
            batch_size=batch_size,
        )

    session_factory = default_session_factory()
    classifier = build_fraud_classifier()

    total_processed = 0

    try:
        while True:
            # Check timeout
            elapsed = time.time() - start_time
            if elapsed > max_runtime_seconds:
                LOGGER.info(f"Time limit reached ({elapsed:.1f}s). Exiting gracefully.")
                break

            with session_factory() as session:
                query = (
                    sa.select(sql_schema.cases.c.case_id, sql_schema.source_documents.c.text)
                    .join(
                        sql_schema.source_documents, sql_schema.cases.c.case_id == sql_schema.source_documents.c.case_id
                    )
                    .where(sql_schema.cases.c.classification_status == "pending")
                    .where(sql_schema.cases.c.is_deleted.is_(False))
                    .where(sql_schema.source_documents.c.text.is_not(None))
                    .where(sql_schema.source_documents.c.text != "")
                    .limit(batch_size)
                )

                rows = session.execute(query).fetchall()

                if not rows:
                    LOGGER.info("No pending cases found. Job complete.")
                    break

                LOGGER.info(f"Fetched batch of {len(rows)} cases.")

                case_ids = [row.case_id for row in rows]
                texts = [row.text or "" for row in rows]

                # Classify batch
                results = classifier.classify_batch(texts)

                # Update statuses
                _update_batch(session, case_ids, results)
                session.commit()

                total_processed += len(rows)
                LOGGER.info(f"Processed batch. Total so far: {total_processed}")

                if reporter.is_enabled():
                    reporter.update(
                        status="processing",
                        message=f"Classified {total_processed} cases so far",
                        processed=total_processed,
                    )

    except Exception as e:
        LOGGER.exception("Job failed unexpectedly")
        if reporter.is_enabled():
            reporter.update(
                status="failed",
                message=f"Sweeper failed after {total_processed} cases: {e}",
                processed=total_processed,
            )
        raise

    status = "finished" if total_processed > 0 else "no_work"
    LOGGER.info("Classification sweeper complete. Total processed: %d", total_processed)
    if reporter.is_enabled():
        reporter.update(
            status=status,
            message=f"Sweeper complete: {total_processed} cases classified",
            processed=total_processed,
        )


def _update_batch(session: Session, case_ids: List[str], results: List[Optional[FraudClassificationResult]]) -> None:
    """Update classification status and results for the batch."""

    now = datetime.now(timezone.utc)

    # We can do this in a loop or bulk update. Loop is clearer for mixed results.
    for i, case_id in enumerate(case_ids):
        result = results[i]

        values = {"updated_at": now}

        if result:
            # Success
            values.update(
                {
                    "classification_status": "classified",
                    "classification": "UNKNOWN",  # Will be refined below based on intent
                    "classification_result": result.dict(),  # Pydantic v1, or .model_dump() in v2
                    "confidence": (
                        result.risk_score / 100.0 if result.risk_score is not None else 0.0
                    ),  # Approximate mapping
                    # We could also update tags here based on labels
                }
            )

            # Map specific primary label if possible.
            # The schema expects a single string for 'classification'.
            # Usually we pick the highest confidence intent.
            if result.intent:
                # Sort by confidence desc
                top_intent = sorted(result.intent, key=lambda x: x.confidence, reverse=True)[0]
                values["classification"] = top_intent.label
            else:
                values["classification"] = "Unspecified"

        else:
            # Failure (LLM error or parsing error)
            # We mark as 'error' so it doesn't loop forever.
            values.update({"classification_status": "error"})
            LOGGER.warning(f"Marking case {case_id} as error due to classification failure.")

        stmt = sa.update(sql_schema.cases).where(sql_schema.cases.c.case_id == case_id).values(**values)
        session.execute(stmt)


if __name__ == "__main__":
    run()
