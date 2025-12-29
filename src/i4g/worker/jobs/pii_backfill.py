"""Backfill job to tokenize existing PII in the StructuredStore."""

import json
import logging
from datetime import datetime

from i4g.pii.tokenization import TokenizationService
from i4g.services.factories import build_structured_store, build_tokenization_service
from i4g.store.schema import ScamRecord

logger = logging.getLogger(__name__)


def run_pii_backfill(dry_run: bool = False) -> None:
    """Scan all records and tokenize PII fields."""
    
    store = build_structured_store()
    service = build_tokenization_service()
    
    # Access underlying connection to iterate all records
    conn = store._conn
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM scam_records")
    
    count = 0
    updated = 0
    
    logger.info(f"Starting PII backfill (dry_run={dry_run})...")
    
    for row in cursor:
        count += 1
        case_id = row["case_id"]
        
        # 1. Text
        original_text = row["text"] or ""
        tokenized_text = service.tokenize_text_content(original_text, detector="backfill", case_id=case_id)
        
        # 2. Entities
        entities_json = row["entities"]
        entities = json.loads(entities_json) if entities_json else {}
        tokenized_entities = service.tokenize_tree(entities, detector="backfill", case_id=case_id)
        
        # 3. Metadata
        metadata_json = row["metadata"]
        metadata = json.loads(metadata_json) if metadata_json else {}
        tokenized_metadata = service.tokenize_tree(metadata, detector="backfill", case_id=case_id)
        
        # Check if changes needed
        # Note: Simple equality check might be expensive for large objects but safe for correctness
        if (tokenized_text != original_text or 
            tokenized_entities != entities or 
            tokenized_metadata != metadata):
            
            if not dry_run:
                # Parse created_at
                created_at_str = row["created_at"]
                try:
                    created_at = datetime.fromisoformat(created_at_str)
                except (ValueError, TypeError):
                    created_at = datetime.utcnow()

                # Parse embedding
                embedding_json = row["embedding"]
                embedding = json.loads(embedding_json) if embedding_json else None

                # Update
                store.upsert_record(ScamRecord(
                    case_id=case_id,
                    text=tokenized_text,
                    entities=tokenized_entities,
                    classification=row["classification"],
                    confidence=row["confidence"],
                    created_at=created_at,
                    embedding=embedding,
                    metadata=tokenized_metadata
                ))
            updated += 1
            
    logger.info(f"Backfill complete. Scanned {count} records. Updated {updated} records. Dry run: {dry_run}")
