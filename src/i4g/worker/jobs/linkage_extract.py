"""LLM-driven extraction of financial indicators from intake narratives.

Parses intake narrative text (``details`` + ``summary``) to identify mentioned
financial indicators (wallet addresses, bank accounts, phone numbers, URLs, etc.)
and writes ``intake_indicator_links`` rows with confidence scores.

Run manually::

    i4g jobs linkage-extract

Or as a backfill::

    i4g jobs linkage-extract --backfill
"""

from __future__ import annotations

import json
import logging
import sys

import sqlalchemy as sa
from sqlalchemy.orm import Session

from i4g.llm.client import build_llm_client
from i4g.settings import get_settings
from i4g.store.sql import (
    dialect_insert,
    indicators,
    intake_indicator_links,
    intake_records,
)
from i4g.store.sql import session_factory as build_sql_session_factory
from i4g.task_status import TaskStatusReporter
from i4g.worker.logging import configure_job_logging

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """\
You are a financial crime analyst. Given the following fraud intake narrative, \
identify all financial indicators mentioned (wallet addresses, bank account numbers, \
phone numbers, email addresses, URLs, domain names, IP addresses, transaction IDs, \
or any other identifiers that could be linked to financial fraud).

For each indicator found, return a JSON array of objects with these fields:
- "type": one of "wallet", "bank_account", "phone", "email", "url", "domain", \
"ip_address", "transaction_id", "other"
- "value": the exact indicator value as it appears in the text
- "confidence": a number between 0 and 1 indicating how confident you are \
that this is a genuine financial indicator

If no indicators are found, return an empty array: []

Narrative:
{narrative}

Return ONLY the JSON array, no other text.
"""


def _parse_extraction_response(response_text: str) -> list[dict]:
    """Parse LLM response into a list of indicator dicts.

    Args:
        response_text: Raw LLM output.

    Returns:
        List of dicts with keys ``type``, ``value``, ``confidence``.
    """
    cleaned = response_text.strip()

    # Extract from ```json ... ``` blocks
    if "```json" in cleaned:
        start = cleaned.find("```json") + 7
        end = cleaned.find("```", start)
        if end != -1:
            cleaned = cleaned[start:end].strip()

    # Try to find array boundaries
    start_bracket = cleaned.find("[")
    end_bracket = cleaned.rfind("]")
    if start_bracket != -1 and end_bracket != -1:
        cleaned = cleaned[start_bracket : end_bracket + 1]

    data = json.loads(cleaned)
    if not isinstance(data, list):
        return []

    results = []
    for item in data:
        if not isinstance(item, dict):
            continue
        ind_type = item.get("type", "other")
        value = item.get("value", "")
        confidence = float(item.get("confidence", 0.5))
        if value:
            results.append({"type": ind_type, "value": str(value), "confidence": confidence})
    return results


def _match_indicators(session: Session, extracted: list[dict]) -> list[tuple[str, float]]:
    """Match extracted indicator values against the ``indicators`` table.

    Args:
        session: Active DB session.
        extracted: Output from ``_parse_extraction_response``.

    Returns:
        List of ``(indicator_id, confidence)`` tuples for matched indicators.
    """
    matches: list[tuple[str, float]] = []
    for item in extracted:
        value = item["value"]
        confidence = item["confidence"]

        # Try exact match on indicator number
        stmt = sa.select(indicators.c.indicator_id).where(indicators.c.number == value).limit(1)
        row = session.execute(stmt).fetchone()
        if row:
            matches.append((row.indicator_id, confidence))
    return matches


def _process_intake(session: Session, llm_client: object, intake_id: str, narrative: str) -> int:
    """Extract indicators from a single intake narrative and write links.

    Args:
        session: Active DB session.
        llm_client: LLM client with ``generate()`` method.
        intake_id: Intake record ID.
        narrative: Combined summary + details text.

    Returns:
        Number of links created.
    """
    prompt = _EXTRACTION_PROMPT.format(narrative=narrative)
    try:
        response = llm_client.generate(prompt)  # type: ignore[attr-defined]
        extracted = _parse_extraction_response(response)
    except (json.JSONDecodeError, ValueError):
        logger.warning("linkage-extract: failed to parse LLM response for intake %s", intake_id)
        return 0

    matches = _match_indicators(session, extracted)
    links_created = 0

    for indicator_id, confidence in matches:
        ins = dialect_insert(session, intake_indicator_links)
        ins_stmt = ins.on_conflict_do_nothing(index_elements=["intake_id", "indicator_id"])
        session.execute(
            ins_stmt.values(
                intake_id=intake_id,
                indicator_id=indicator_id,
                confidence=confidence,
                linked_by="llm_extraction",
            )
        )
        links_created += 1

    return links_created


def main(*, backfill: bool = False) -> int:
    """Entry point executed by the Cloud Run job container or CLI.

    Args:
        backfill: When ``True``, process all intake records.
            When ``False``, only process records not yet linked.
    """
    settings = get_settings()
    configure_job_logging(settings)
    reporter = TaskStatusReporter()
    threshold = settings.analytics.loss_linkage_confidence_threshold

    logger.info("linkage-extract: starting (backfill=%s, threshold=%.2f)", backfill, threshold)
    if reporter.is_enabled():
        reporter.update(status="processing", message="Starting indicator linkage extraction")

    sf = build_sql_session_factory()
    session: Session = sf()
    llm_client = build_llm_client()

    try:
        # Select intakes to process
        base_query = sa.select(
            intake_records.c.intake_id,
            intake_records.c.summary,
            intake_records.c.details,
        ).where(
            sa.or_(
                intake_records.c.summary.isnot(None),
                intake_records.c.details.isnot(None),
            )
        )

        if not backfill:
            # Only process intakes that have no existing links
            already_linked = sa.select(sa.distinct(intake_indicator_links.c.intake_id))
            base_query = base_query.where(intake_records.c.intake_id.notin_(already_linked))

        rows = session.execute(base_query).fetchall()
        total = len(rows)
        logger.info("linkage-extract: %d intake records to process", total)

        if total == 0:
            if reporter.is_enabled():
                reporter.update(status="finished", message="No intakes to process", processed=0)
            return 0

        successes = 0
        failures = 0

        for idx, row in enumerate(rows, 1):
            narrative_parts = []
            if row.summary:
                narrative_parts.append(str(row.summary))
            if row.details:
                narrative_parts.append(str(row.details))
            narrative = "\n\n".join(narrative_parts)

            try:
                links = _process_intake(session, llm_client, row.intake_id, narrative)
                session.commit()
                if links > 0:
                    successes += 1
                    logger.debug("linkage-extract: %d links for intake %s", links, row.intake_id)
            except Exception:
                logger.exception("linkage-extract: error processing intake %s", row.intake_id)
                session.rollback()
                failures += 1

            if reporter.is_enabled() and (idx % 10 == 0 or idx == total):
                reporter.update(
                    status="processing",
                    message=f"Processed {idx}/{total} intakes",
                    progress=idx,
                    total=total,
                    successes=successes,
                    failures=failures,
                )

        status = "finished" if failures == 0 else "failed"
        logger.info(
            "linkage-extract: %s — %d successes, %d failures out of %d",
            status,
            successes,
            failures,
            total,
        )
        if reporter.is_enabled():
            reporter.update(
                status=status,
                message=f"Linkage extraction {status}: {successes} linked, {failures} failed",
                processed=successes + failures,
                successes=successes,
                failures=failures,
            )

        return 0 if failures == 0 else 1

    finally:
        session.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
