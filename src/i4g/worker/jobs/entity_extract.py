"""Batch entity extraction job using LLM-based NER.

Reads cases from the database that lack entities, runs NER (LLM + rule-based
fallback), and writes extracted entities and indicators back to the DB.

Run manually::

    i4g jobs entity-extract
    i4g jobs entity-extract --backfill --limit 100

Or as a Cloud Run job during bootstrap.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Session

from i4g.extraction.ner_rules import extract_entities as rule_extract_entities
from i4g.llm.client import build_llm_client
from i4g.settings import get_settings
from i4g.store.sql import (
    cases,
    dialect_insert,
    entities,
    indicators,
)
from i4g.store.sql import session_factory as build_sql_session_factory
from i4g.store.sql import (
    source_documents,
)
from i4g.task_status import TaskStatusReporter
from i4g.worker.logging import configure_job_logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# NER prompt — mirrors semantic_ner.py but works with the simple generate()
# interface so it's compatible with all LLM providers (Vertex AI, Ollama, mock).
# ---------------------------------------------------------------------------

_ENTITY_KEYS = [
    "people",
    "organizations",
    "crypto_assets",
    "wallet_addresses",
    "contact_channels",
    "locations",
    "scam_indicators",
]

_EXTRACTION_PROMPT = """\
You are an assistant whose only job is to extract structured entities from text for \
the purpose of user support and law enforcement investigation. You must NOT provide \
operational advice or anything that enables wrongdoing.

Return ONLY a JSON object with these exact top-level keys:
{keys}

If a field has no values, return an empty list for that field. Do NOT add extra keys.

Example Input: "Hi, I'm Anna from TrustWallet. Send 0xAbC... to verify and pay 50 USDT."
Example Output:
{{"people": ["Anna"], "organizations": ["TrustWallet"], "crypto_assets": ["USDT"], \
"wallet_addresses": ["0xAbC..."], "contact_channels": [], "locations": [], \
"scam_indicators": ["verification fee", "send to verify"]}}

Now analyze the following text and return ONLY the JSON object:

{text}
"""


def _parse_entity_response(response_text: str) -> dict[str, list[str]]:
    """Parse LLM response into entity dict."""
    cleaned = response_text.strip()

    # Try direct parse
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if isinstance(v, list)}
    except json.JSONDecodeError:
        pass

    # Extract JSON from markdown blocks
    if "```json" in cleaned:
        start = cleaned.find("```json") + 7
        end = cleaned.find("```", start)
        if end != -1:
            try:
                data = json.loads(cleaned[start:end].strip())
                if isinstance(data, dict):
                    return {k: v for k, v in data.items() if isinstance(v, list)}
            except json.JSONDecodeError:
                pass

    # Regex fallback for JSON object
    m = re.search(r"\{(?:[^{}]|\{[^{}]*\})*\}", cleaned, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if isinstance(v, list)}
        except json.JSONDecodeError:
            pass

    return {}


def _extract_entities_for_text(llm_client: object, text: str) -> dict[str, list[str]]:
    """Run LLM + rule-based NER on a text and merge results."""
    llm_result: dict[str, list[str]] = {}

    # LLM extraction
    prompt = _EXTRACTION_PROMPT.format(keys=", ".join(_ENTITY_KEYS), text=text[:8000])
    try:
        response = llm_client.generate(prompt)  # type: ignore[attr-defined]
        llm_result = _parse_entity_response(response)
    except Exception:
        logger.warning("LLM entity extraction failed; falling back to rules only", exc_info=True)

    # Rule-based extraction (always runs as supplement/fallback)
    rule_result = rule_extract_entities(text)

    # Merge: union of LLM + rules, deduped
    merged: dict[str, list[str]] = {}
    for key in _ENTITY_KEYS:
        llm_items = set(llm_result.get(key, [])) if isinstance(llm_result.get(key), list) else set()
        rule_items = set(rule_result.get(key, [])) if isinstance(rule_result.get(key), list) else set()
        combined = sorted(str(v) for v in llm_items | rule_items if v)
        if combined:
            merged[key] = combined

    return merged


def _persist_extracted_entities(
    session: Session,
    case_id: str,
    entity_map: dict[str, list[str]],
    dataset: str,
) -> tuple[int, int]:
    """Write entities and indicators to the DB. Returns (entity_count, indicator_count)."""
    now = datetime.now(UTC)
    entity_count = 0
    indicator_count = 0

    for entity_type, values in entity_map.items():
        if not isinstance(values, list):
            continue
        for val in values:
            canonical = str(val).strip() if isinstance(val, str) else str(val)
            if not canonical:
                continue

            # Upsert entity
            eid = str(uuid4())
            ins = dialect_insert(session, entities)
            ins_stmt = ins.on_conflict_do_nothing(
                constraint="uq_entities_case_type_value",
            )
            session.execute(
                ins_stmt.values(
                    entity_id=eid,
                    case_id=case_id,
                    entity_type=entity_type,
                    canonical_value=canonical,
                    raw_value=canonical,
                    confidence=0.7,
                    created_at=now,
                    updated_at=now,
                )
            )
            entity_count += 1

            # Upsert indicator (IoC mirror)
            iid = str(uuid4())
            ind_ins = dialect_insert(session, indicators)
            ind_ins_stmt = ind_ins.on_conflict_do_nothing(
                constraint="uq_indicators_dataset_category_number",
            )
            session.execute(
                ind_ins_stmt.values(
                    indicator_id=iid,
                    case_id=case_id,
                    category=entity_type,
                    type=entity_type,
                    number=canonical,
                    dataset=dataset,
                    status="active",
                    confidence=0.7,
                    first_seen_at=now,
                    last_seen_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            indicator_count += 1

    return entity_count, indicator_count


def main(*, backfill: bool = False, limit: int = 0) -> int:
    """Entry point executed by Cloud Run job or CLI.

    Args:
        backfill: When True, re-extract entities for ALL cases (not just missing).
        limit: Maximum number of cases to process (0 = unlimited).

    Returns:
        Exit code (0=success, nonzero=failure).
    """
    settings = get_settings()
    configure_job_logging(settings)
    reporter = TaskStatusReporter()

    logger.info("entity-extract: starting (backfill=%s, limit=%s)", backfill, limit)
    if reporter.is_enabled():
        reporter.update(status="processing", message="Starting entity extraction")

    sf = build_sql_session_factory()
    session: Session = sf()
    llm_client = build_llm_client()

    try:
        # Build query: cases joined with their primary document text
        stmt = (
            sa.select(
                cases.c.case_id,
                cases.c.dataset,
                source_documents.c.text,
            )
            .join(source_documents, cases.c.case_id == source_documents.c.case_id)
            .where(cases.c.is_deleted == sa.false())
        )

        if not backfill:
            # Only cases without entities
            has_entities = sa.select(entities.c.entity_id).where(entities.c.case_id == cases.c.case_id).exists()
            stmt = stmt.where(~has_entities)

        # Deduplicate to one row per case (pick longest text)
        stmt = stmt.order_by(cases.c.case_id, sa.func.length(source_documents.c.text).desc())

        if limit > 0:
            stmt = stmt.limit(limit)

        rows = session.execute(stmt).fetchall()

        # Deduplicate: keep first (longest text) per case_id
        seen_cases: set[str] = set()
        unique_rows: list[tuple[str, str, str]] = []
        for row in rows:
            if row.case_id not in seen_cases:
                seen_cases.add(row.case_id)
                unique_rows.append((row.case_id, row.dataset, row.text))

        total = len(unique_rows)
        logger.info("entity-extract: found %d cases to process", total)

        if total == 0:
            logger.info("entity-extract: no cases need entity extraction")
            return 0

        successes = 0
        failures = 0
        total_entities = 0
        total_indicators = 0

        for i, (case_id, dataset, text) in enumerate(unique_rows):
            if not text or not text.strip():
                logger.debug("entity-extract: skipping case %s (no text)", case_id)
                continue

            try:
                entity_map = _extract_entities_for_text(llm_client, text)
                if entity_map:
                    ent_count, ind_count = _persist_extracted_entities(
                        session, case_id, entity_map, dataset or "unknown"
                    )
                    total_entities += ent_count
                    total_indicators += ind_count
                    session.commit()
                    successes += 1
                else:
                    logger.debug("entity-extract: no entities found for case %s", case_id)
                    successes += 1
            except Exception:
                session.rollback()
                failures += 1
                logger.exception("entity-extract: failed for case %s", case_id)

            if (i + 1) % 25 == 0:
                logger.info(
                    "entity-extract: progress %d/%d (entities=%d, indicators=%d)",
                    i + 1,
                    total,
                    total_entities,
                    total_indicators,
                )
                if reporter.is_enabled():
                    reporter.update(
                        status="processing",
                        message=f"Processed {i + 1}/{total} cases",
                        processed=i + 1,
                    )

        status = "finished" if failures == 0 else "partial"
        logger.info(
            "entity-extract: %s — %d successes, %d failures, %d entities, %d indicators",
            status,
            successes,
            failures,
            total_entities,
            total_indicators,
        )
        if reporter.is_enabled():
            reporter.update(
                status=status,
                message=f"Entity extraction {status}: {successes} cases, {total_entities} entities",
                processed=successes + failures,
                successes=successes,
                failures=failures,
            )

        return 0 if failures == 0 else 1

    except Exception:
        logger.exception("entity-extract: job failed")
        return 1
    finally:
        session.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
