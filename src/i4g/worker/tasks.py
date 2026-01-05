"""
Background worker tasks for i4g.

This module defines asynchronous and manual worker functions that perform
post-review operations such as report generation and export.
"""

import logging
from typing import Optional

from i4g.reports.generator import ReportGenerator
from i4g.services.factories import (
    build_fraud_classifier,
    build_review_store,
    build_structured_store,
)
from i4g.store.review_store import ReviewStore

logger = logging.getLogger(__name__)


def _resolve_review_store(candidate: Optional[ReviewStore]) -> ReviewStore:
    """Return a review store honoring patched mocks when supplied."""

    if candidate is not None:
        return candidate

    # Tests often monkeypatch ``ReviewStore`` with a MagicMock factory.
    if not isinstance(ReviewStore, type):
        return ReviewStore()

    return build_review_store()


def generate_report_for_case(
    review_id: str,
    store: Optional[ReviewStore] = None,
) -> str:
    """Generate and export a report for a specific accepted review case.

    Args:
        review_id: Unique ID of the review record.
        store: Optional ReviewStore instance; creates new if omitted.

    Returns:
        The local path of the created report, or "error:<message>" on failure.
    """
    store = _resolve_review_store(store)

    case = store.get_review(review_id)
    if not case:
        logger.error("No such review ID: %s", review_id)
        return "error:review_not_found"

    if case.get("status") != "accepted":
        logger.warning("Review %s is not marked accepted; skipping", review_id)
        return "error:not_accepted"

    try:
        generator = ReportGenerator()
        report_result = generator.generate_report(case_id=case.get("case_id"))

        report_path = report_result.get("report_path")
        if not report_path:
            raise Exception("Report generated but no local path returned.")

        store.log_action(
            review_id,
            actor="worker",
            action="report_generated",
            payload={"report_path": report_path},
        )
        logger.info("Generated and exported report for %s → %s", review_id, report_path)
        return report_path
    except Exception as exc:
        logger.exception("Report generation/export failed for %s", review_id)
        store.log_action(review_id, actor="worker", action="error", payload={"error": str(exc)})
        return f"error:{exc}"

def classify_case(case_id: str) -> str:
    """Run fraud classification on a specific case and update the record.

    Args:
        case_id: The unique case identifier.

    Returns:
        "success" or "error:<message>"
    """
    try:
        store = build_structured_store()
        record = store.get_by_id(case_id)
        if not record:
            return "error:case_not_found"

        if not record.text:
            return "error:no_text"

        classifier = build_fraud_classifier()
        result = classifier.classify(record.text)

        # Map primary intent to legacy fields
        if result.intent:
            # Sort by confidence desc
            top_intent = sorted(result.intent, key=lambda x: x.confidence, reverse=True)[0]
            record.classification = top_intent.label
            record.confidence = top_intent.confidence

        # Store full result in metadata
        if not record.metadata:
            record.metadata = {}
        record.metadata["classification_result"] = result.model_dump()

        store.upsert_record(record)
        logger.info("Reclassified case %s as %s", case_id, record.classification)
        return "success"

    except Exception as exc:
        logger.exception("Classification failed for case %s", case_id)
        return f"error:{exc}"
