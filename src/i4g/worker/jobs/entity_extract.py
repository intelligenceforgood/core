"""Batch entity extraction job using LLM-based NER.

Reads cases from the database that lack entities, runs NER (LLM + rule-based
fallback), and writes extracted entities and indicators back to the DB.

Supports configurable concurrency via ``extraction.batch_concurrency``.
Tracks repeatedly failing cases in a dead-letter log.

Run manually::

    i4g jobs entity-extract
    i4g jobs entity-extract --backfill --limit 100

Or as a Cloud Run job during bootstrap.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Session

from i4g.extraction import ExtractionResult, extract_entities
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
from i4g.utils.entity_types import THREAT_ENTITY_TYPES
from i4g.worker.logging import configure_job_logging

logger = logging.getLogger(__name__)

# Maximum consecutive failures before a case is dead-lettered.
_MAX_FAILURES = 3


def _dead_letter_path() -> Path:
    """Return the path to the dead-letter log file."""
    from i4g.settings import get_settings

    settings = get_settings()
    return Path(settings.project_root) / "data" / "entity-qa" / "dead_letters.json"


def _load_dead_letters() -> dict[str, dict]:
    """Load the dead-letter log, returning ``{case_id: {count, last_error, last_attempt}}``."""
    path = _dead_letter_path()
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_dead_letters(dead_letters: dict[str, dict]) -> None:
    """Persist the dead-letter log."""
    path = _dead_letter_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dead_letters, indent=2, default=str) + "\n")


def _record_failure(dead_letters: dict[str, dict], case_id: str, error: str) -> None:
    """Increment failure count for a case, or add a new entry."""
    now = datetime.now(UTC).isoformat()
    if case_id in dead_letters:
        dead_letters[case_id]["count"] += 1
        dead_letters[case_id]["last_error"] = error
        dead_letters[case_id]["last_attempt"] = now
    else:
        dead_letters[case_id] = {"count": 1, "last_error": error, "last_attempt": now}


def _is_dead_lettered(dead_letters: dict[str, dict], case_id: str) -> bool:
    """Return True if the case has exceeded the max failure threshold."""
    entry = dead_letters.get(case_id)
    return entry is not None and entry["count"] >= _MAX_FAILURES


def _persist_extracted_entities(
    session: Session,
    case_id: str,
    result: ExtractionResult,
    dataset: str,
) -> tuple[int, int]:
    """Write entities and indicators to the DB. Returns (entity_count, indicator_count)."""
    now = datetime.now(UTC)
    entity_count = 0
    indicator_count = 0

    for ent in result.entities:
        canonical = ent.canonical_value.strip()
        if not canonical:
            continue
        confidence = ent.confidence

        # Upsert entity
        eid = str(uuid4())
        ins = dialect_insert(session, entities)
        ins_stmt = ins.on_conflict_do_nothing(
            index_elements=["case_id", "entity_type", "canonical_value"],
        )
        session.execute(
            ins_stmt.values(
                entity_id=eid,
                case_id=case_id,
                entity_type=ent.entity_type,
                canonical_value=canonical,
                raw_value=ent.value,
                confidence=confidence,
                created_at=now,
                updated_at=now,
            )
        )
        entity_count += 1

        # Upsert indicator (IoC mirror) — only for threat infrastructure types
        if ent.entity_type not in THREAT_ENTITY_TYPES:
            continue
        iid = str(uuid4())
        ind_ins = dialect_insert(session, indicators)
        ind_ins_stmt = ind_ins.on_conflict_do_nothing(
            index_elements=["dataset", "category", "number"],
        )
        session.execute(
            ind_ins_stmt.values(
                indicator_id=iid,
                case_id=case_id,
                category=ent.entity_type,
                type=ent.entity_type,
                number=canonical,
                dataset=dataset,
                status="active",
                confidence=confidence,
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        indicator_count += 1

    return entity_count, indicator_count


def _run_concurrent(
    *,
    unique_rows: list[tuple[str, str, str]],
    llm_client: object,
    llm_delay: float,
    concurrency: int,
    session: Session,
    reporter: TaskStatusReporter,
    dead_letters: dict[str, dict] | None = None,
) -> tuple[int, int, int, int]:
    """Run extraction concurrently using asyncio with a semaphore.

    The LLM calls run in a thread pool with bounded concurrency.
    DB writes remain sequential on the main thread to avoid session issues.

    Returns:
        (successes, failures, total_entities, total_indicators)
    """

    async def _extract_one(
        sem: asyncio.Semaphore,
        case_id: str,
        text: str,
    ) -> tuple[str, ExtractionResult | None, str | None]:
        """Extract entities for one case, respecting the semaphore."""
        async with sem:
            if llm_delay > 0:
                await asyncio.sleep(llm_delay)
            try:
                result = await asyncio.to_thread(extract_entities, text, llm_client=llm_client)
                return (case_id, result, None)
            except Exception as exc:
                logger.exception("entity-extract: extraction failed for case %s", case_id)
                return (case_id, None, str(exc))

    async def _run_all() -> list[tuple[str, ExtractionResult | None, str | None]]:
        sem = asyncio.Semaphore(concurrency)
        tasks = []
        for case_id, _dataset, text in unique_rows:
            if not text or not text.strip():
                continue
            tasks.append(_extract_one(sem, case_id, text))
        return await asyncio.gather(*tasks)

    # Run the async extraction loop.
    extraction_results = asyncio.run(_run_all())

    # Build a lookup for dataset by case_id.
    dataset_map = {case_id: dataset for case_id, dataset, _ in unique_rows}

    successes = 0
    failures = 0
    total_entities = 0
    total_indicators = 0
    total = len(unique_rows)

    for i, (case_id, result, error) in enumerate(extraction_results):
        if error is not None:
            failures += 1
            if dead_letters is not None:
                _record_failure(dead_letters, case_id, error)
            continue

        dataset = dataset_map.get(case_id, "unknown")
        try:
            if result and result.entities:
                ent_count, ind_count = _persist_extracted_entities(session, case_id, result, dataset or "unknown")
                total_entities += ent_count
                total_indicators += ind_count
                session.commit()
                successes += 1
            else:
                successes += 1
        except Exception as exc:
            session.rollback()
            failures += 1
            if dead_letters is not None:
                _record_failure(dead_letters, case_id, str(exc))
            logger.exception("entity-extract: persist failed for case %s", case_id)

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

    return successes, failures, total_entities, total_indicators


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
    llm_delay = float(os.environ.get("ENTITY_EXTRACT_LLM_DELAY_SECONDS", str(settings.extraction.llm_delay_seconds)))

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

        # Load dead-letter log to skip persistently failing cases.
        dead_letters = _load_dead_letters()
        skipped_dead = 0
        processable: list[tuple[str, str, str]] = []
        for case_id, dataset, text in unique_rows:
            if _is_dead_lettered(dead_letters, case_id):
                skipped_dead += 1
                continue
            processable.append((case_id, dataset, text))

        if skipped_dead:
            logger.info("entity-extract: skipping %d dead-lettered cases", skipped_dead)

        successes = 0
        failures = 0
        total_entities = 0
        total_indicators = 0

        concurrency = settings.extraction.batch_concurrency

        if concurrency > 1:
            # Concurrent extraction — DB writes are still sequential.
            successes, failures, total_entities, total_indicators = _run_concurrent(
                unique_rows=processable,
                llm_client=llm_client,
                llm_delay=llm_delay,
                concurrency=concurrency,
                session=session,
                reporter=reporter,
                dead_letters=dead_letters,
            )
        else:
            # Sequential extraction (default).
            for i, (case_id, dataset, text) in enumerate(processable):
                if not text or not text.strip():
                    logger.debug("entity-extract: skipping case %s (no text)", case_id)
                    continue

                text_len = len(text) if text else 0
                logger.info(
                    "entity-extract: [%d/%d] starting case %s (text_len=%d)",
                    i + 1,
                    len(processable),
                    case_id,
                    text_len,
                )
                case_start = time.monotonic()
                try:
                    result = extract_entities(text, llm_client=llm_client)
                    case_elapsed = time.monotonic() - case_start
                    if result.entities:
                        ent_count, ind_count = _persist_extracted_entities(
                            session, case_id, result, dataset or "unknown"
                        )
                        total_entities += ent_count
                        total_indicators += ind_count
                        session.commit()
                        successes += 1
                    else:
                        logger.debug("entity-extract: no entities found for case %s", case_id)
                        successes += 1
                    if case_elapsed > 30:
                        logger.warning(
                            "entity-extract: slow case %s took %.1fs (text_len=%d)",
                            case_id,
                            case_elapsed,
                            len(text),
                        )
                except Exception as exc:
                    session.rollback()
                    failures += 1
                    _record_failure(dead_letters, case_id, str(exc))
                    logger.exception("entity-extract: failed for case %s", case_id)

                # Throttle to avoid LLM quota contention with classification sweeper
                if llm_delay > 0:
                    time.sleep(llm_delay)

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

        # Persist dead-letter log if any failures occurred.
        if failures > 0:
            _save_dead_letters(dead_letters)
            dead_count = sum(1 for v in dead_letters.values() if v["count"] >= _MAX_FAILURES)
            if dead_count:
                logger.warning(
                    "entity-extract: %d cases now dead-lettered (>=%d failures)",
                    dead_count,
                    _MAX_FAILURES,
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
