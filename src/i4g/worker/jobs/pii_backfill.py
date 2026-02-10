"""Backfill job to tokenize existing PII in the StructuredStore."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from i4g.services.factories import build_structured_store, build_tokenization_service
from i4g.store.schema import ScamRecord

logger = logging.getLogger(__name__)


def run_pii_backfill(dry_run: bool = False) -> None:
    """Scan all records and tokenize PII fields."""

    store = build_structured_store()
    service = build_tokenization_service()

    records = store.list_all()

    count = 0
    updated = 0

    logger.info("Starting PII backfill (dry_run=%s)...", dry_run)

    for record in records:
        count += 1
        case_id = record.case_id

        # 1. Text
        original_text = record.text or ""
        tokenized_text = service.tokenize_text_content(original_text, detector="backfill", case_id=case_id)

        # 2. Entities
        entities = record.entities or {}
        tokenized_entities = service.tokenize_tree(entities, detector="backfill", case_id=case_id)

        # 3. Metadata
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

    logger.info("Backfill complete. Scanned %d records. Updated %d records. Dry run: %s", count, updated, dry_run)
