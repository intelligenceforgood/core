"""Cloud Run job for batch classification of pending cases."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from typing import List, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Session

from i4g.services.factories import build_fraud_classifier
from i4g.store import sql as sql_schema
from i4g.store.sql import session_factory as default_session_factory
from i4g.taxonomy.models import FraudClassificationResult

LOGGER = logging.getLogger("i4g.worker.jobs.classification_sweeper")


def _configure_logging() -> None:
    """Configures the logging level based on environment variables."""
    level_name = os.getenv("I4G_RUNTIME__LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def run() -> None:
    """Execute the classification sweeper job."""
    _configure_logging()

    start_time = time.time()
    # Default execution limit is 55 mins (Cloud Run default timeout is usually 60m)
    max_runtime_seconds = int(os.getenv("JOB_MAX_RUNTIME_SECONDS", "3300"))
    # Lower default batch size to improve reliability with gemini-2.5-flash
    batch_size = int(os.getenv("JOB_BATCH_SIZE", "20"))

    LOGGER.info(f"Starting classification sweeper (batch_size={batch_size}, timeout={max_runtime_seconds}s)")

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
                # Fetch pending cases
                # Postgres supports SKIP LOCKED which is ideal for queue processing
                # But we default to simple select for broad compatibility if sqlite is mistakenly used in dev
                # For Cloud SQL (Postgres), we can optimize later if concurrency is high.
                # Since we enforce parallelism=1 in Cloud Run config, simple LIMIT is safe enough.

                query = (
                    sa.select(sql_schema.cases.c.case_id, sql_schema.source_documents.c.text)
                    .join(
                        sql_schema.source_documents, sql_schema.cases.c.case_id == sql_schema.source_documents.c.case_id
                    )
                    .where(sql_schema.cases.c.classification_status == "pending")
                    .where(sql_schema.cases.c.is_deleted.is_(False))
                    # Prefer cases with non-empty text
                    .where(sql_schema.source_documents.c.text.is_not(None))
                    .where(sql_schema.source_documents.c.text != "")
                    # Prefer cases with text; join ensures we have the document text
                    # We might need to aggregate text if multiple docs exist,
                    # but typically first doc is the main one for simple classification.
                    # Or we can select cases and join text.
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

    except Exception as e:
        LOGGER.exception("Job failed unexpectedly")
        # In a real job, we might not want to exit with non-zero if we processed some items,
        # but failing hard ensures the scheduler/monitoring knows something is wrong.
        raise


def _update_batch(session: Session, case_ids: List[str], results: List[Optional[FraudClassificationResult]]) -> None:
    """Update classification status and results for the batch."""

    now = datetime.utcnow()

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
