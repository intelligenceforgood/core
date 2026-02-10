"""Backfill job to tokenize existing PII in the StructuredStore."""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

from i4g.services.factories import build_structured_store, build_tokenization_service
from i4g.store.schema import ScamRecord
from i4g.task_status import TaskStatusReporter
from i4g.utils.coerce import env_bool

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    level_name = os.getenv("I4G_RUNTIME__LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def run_pii_backfill(
    *,
    dry_run: bool = False,
    reporter: TaskStatusReporter | None = None,
) -> int:
    """Scan all records and tokenize PII fields.

    Args:
        dry_run: If ``True``, detect changes but do not write them.
        reporter: Optional task-status reporter for progress updates.

    Returns:
        Exit code: 0 on success, 1 on partial failure.
    """
    reporter = reporter or TaskStatusReporter()

    store = build_structured_store()
    service = build_tokenization_service()

    records = store.list_all()
    total = len(records)

    count = 0
    updated = 0
    failed = 0

    logger.info("Starting PII backfill (dry_run=%s, total_records=%d)...", dry_run, total)
    if reporter.is_enabled():
        reporter.update(status="started", message="PII backfill started", total=total, dry_run=dry_run)

    for record in records:
        count += 1
        case_id = record.case_id

        try:
            original_text = record.text or ""
            tokenized_text = service.tokenize_text_content(original_text, detector="backfill", case_id=case_id)

            entities = record.entities or {}
            tokenized_entities = service.tokenize_tree(entities, detector="backfill", case_id=case_id)

            metadata = record.metadata or {}
            tokenized_metadata = service.tokenize_tree(metadata, detector="backfill", case_id=case_id)

            if (
                tokenized_text != original_text
                or tokenized_entities != entities
                or tokenized_metadata != metadata
            ):
                if not dry_run:
                    store.upsert_record(
                        ScamRecord(
                            case_id=case_id,
                            text=tokenized_text,
                            entities=tokenized_entities,
                            classification=record.classification,
                            confidence=record.confidence,
                            created_at=record.created_at or datetime.now(timezone.utc),
                            embedding=record.embedding,
                            metadata=tokenized_metadata,
                        )
                    )
                updated += 1
        except Exception:
            failed += 1
            logger.exception("Failed to process case %s (%d/%d)", case_id, count, total)

        # Progress every 50 records or at the end
        if reporter.is_enabled() and (count % 50 == 0 or count == total):
            reporter.update(
                status="processing",
                message=f"Processed {count}/{total} records",
                progress=count,
                total=total,
                updated=updated,
                failed=failed,
            )

    status = "finished" if failed == 0 else "partial"
    logger.info(
        "PII backfill %s. Scanned %d records. Updated %d. Failed %d. Dry run: %s",
        status, count, updated, failed, dry_run,
    )
    if reporter.is_enabled():
        reporter.update(
            status=status,
            message=f"Backfill {status}: {updated} updated, {failed} failed out of {count}",
            processed=count,
            updated=updated,
            failed=failed,
        )

    return 1 if failed > 0 else 0


def main() -> int:
    """Entry point executed by Cloud Run jobs and local CLI."""

    _configure_logging()
    dry_run = env_bool("I4G_PII_BACKFILL__DRY_RUN", default=False)

    logger.info("Starting PII backfill job: dry_run=%s", dry_run)
    reporter = TaskStatusReporter()
    return run_pii_backfill(dry_run=dry_run, reporter=reporter)


if __name__ == "__main__":
    sys.exit(main())
