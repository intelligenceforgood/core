"""Cloud Run job for batch classification of pending cases."""

from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from i4g.observability import get_observability
from i4g.services.factories import build_fraud_classifier
from i4g.settings import get_settings
from i4g.store import sql as sql_schema
from i4g.store.sql import session_factory as default_session_factory
from i4g.task_status import TaskStatusReporter
from i4g.taxonomy.models import FraudClassificationResult
from i4g.worker.logging import configure_job_logging

LOGGER = logging.getLogger("i4g.worker.jobs.classification_sweeper")


@dataclass
class SweeperMetrics:
    """Accumulated metrics for a sweeper run."""

    total_processed: int = 0
    classified_count: int = 0
    error_count: int = 0
    intent_distribution: Counter = field(default_factory=Counter)
    batch_durations: list[float] = field(default_factory=list)

    @property
    def avg_batch_duration(self) -> float:
        """Average batch classification time in seconds."""
        return sum(self.batch_durations) / len(self.batch_durations) if self.batch_durations else 0.0

    def summary(self) -> dict:
        """Return a loggable summary dict."""
        return {
            "total_processed": self.total_processed,
            "classified": self.classified_count,
            "errors": self.error_count,
            "avg_batch_seconds": round(self.avg_batch_duration, 2),
            "top_intents": dict(self.intent_distribution.most_common(5)),
        }


def run() -> None:
    """Execute the classification sweeper job."""
    settings = get_settings()
    configure_job_logging(settings)

    start_time = time.time()
    max_runtime_seconds = settings.sweep.max_runtime_seconds
    batch_size = settings.sweep.batch_size
    llm_delay = settings.sweep.llm_delay_seconds

    LOGGER.info(
        "Starting classification sweeper (batch_size=%d, timeout=%ds, llm_delay=%ss)",
        batch_size,
        max_runtime_seconds,
        llm_delay,
    )

    reporter = TaskStatusReporter()
    if reporter.is_enabled():
        reporter.update(
            status="started",
            message=f"Classification sweeper started (batch_size={batch_size})",
            batch_size=batch_size,
        )

    session_factory = default_session_factory()
    classifier = build_fraud_classifier()

    metrics = SweeperMetrics()

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
                batch_start = time.time()
                results = classifier.classify_batch(texts)
                batch_duration = time.time() - batch_start
                metrics.batch_durations.append(batch_duration)

                # Update statuses and accumulate metrics
                _update_batch(session, case_ids, results, metrics)
                session.commit()

                LOGGER.info(
                    "Batch complete: %d items in %.1fs (classified=%d, errors=%d)",
                    len(rows),
                    batch_duration,
                    metrics.classified_count,
                    metrics.error_count,
                )

                if reporter.is_enabled():
                    reporter.update(
                        status="processing",
                        message=f"Classified {metrics.total_processed} cases so far",
                        processed=metrics.total_processed,
                        classified=metrics.classified_count,
                        errors=metrics.error_count,
                    )

                # Throttle to avoid LLM quota contention with entity extraction
                if llm_delay > 0:
                    time.sleep(llm_delay)

    except Exception as e:
        LOGGER.exception("Job failed unexpectedly")
        if reporter.is_enabled():
            reporter.update(
                status="failed",
                message=f"Sweeper failed after {metrics.total_processed} cases: {e}",
                **metrics.summary(),
            )
        raise

    total_elapsed = time.time() - start_time
    status = "finished" if metrics.total_processed > 0 else "no_work"
    LOGGER.info(
        "Classification sweeper complete: %s",
        {**metrics.summary(), "total_elapsed_seconds": round(total_elapsed, 1)},
    )

    # F53: Emit operational metrics for classification accuracy dashboard
    try:
        obs = get_observability(component="classification_sweeper", settings=settings)
        obs.increment("classification.sweeper.processed", value=float(metrics.total_processed))
        obs.increment("classification.sweeper.classified", value=float(metrics.classified_count))
        obs.increment("classification.sweeper.errors", value=float(metrics.error_count))
        obs.record_timing("classification.sweeper.duration", value_ms=total_elapsed * 1000)
        for intent_label, count in metrics.intent_distribution.most_common():
            obs.increment("classification.sweeper.intent", value=float(count), tags={"intent": intent_label})
        obs.emit_event(
            "classification.sweeper.complete",
            **metrics.summary(),
            total_elapsed_seconds=round(total_elapsed, 1),
        )
    except Exception:
        LOGGER.debug("Metrics emission failed; non-critical", exc_info=True)

    if reporter.is_enabled():
        reporter.update(
            status=status,
            message=f"Sweeper complete: {metrics.total_processed} cases classified",
            **metrics.summary(),
            total_elapsed_seconds=round(total_elapsed, 1),
        )


def _update_batch(
    session: Session,
    case_ids: list[str],
    results: list[FraudClassificationResult | None],
    metrics: SweeperMetrics,
) -> None:
    """Update classification status and results for the batch."""

    now = datetime.now(UTC)

    for i, case_id in enumerate(case_ids):
        result = results[i]
        metrics.total_processed += 1

        values = {"updated_at": now}

        if result:
            metrics.classified_count += 1

            values.update(
                {
                    "classification_status": "classified",
                    "classification": "UNKNOWN",
                    "classification_result": result.model_dump(),
                    "confidence": (result.risk_score / 100.0 if result.risk_score is not None else 0.0),
                    "risk_score": result.risk_score if result.risk_score is not None else 0.0,
                    "taxonomy_version": result.taxonomy_version,
                }
            )

            if result.intent:
                top_intent = sorted(result.intent, key=lambda x: x.confidence, reverse=True)[0]
                values["classification"] = top_intent.label
                metrics.intent_distribution[top_intent.label] += 1
            else:
                values["classification"] = "Unspecified"
                metrics.intent_distribution["Unspecified"] += 1

        else:
            metrics.error_count += 1
            values.update({"classification_status": "error"})
            LOGGER.warning(f"Marking case {case_id} as error due to classification failure.")

        stmt = sa.update(sql_schema.cases).where(sql_schema.cases.c.case_id == case_id).values(**values)
        session.execute(stmt)


if __name__ == "__main__":
    run()
