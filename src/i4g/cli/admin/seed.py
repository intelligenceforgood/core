"""Seed the review queue with synthetic cases."""

from __future__ import annotations

import logging
import random
from typing import Dict, List, Tuple
from uuid import uuid4

from i4g.services.factories import build_review_store
from i4g.store.review_store import ReviewStore, SqlAlchemyReviewStore

LOGGER = logging.getLogger(__name__)

CASE_TEMPLATES: List[Dict[str, str]] = [
    {
        "code": "CRYPTO",
        "priority": "high",
        "summary": "TrustWallet verification request flagged by classifier.",
    },
    {
        "code": "ROMANCE",
        "priority": "medium",
        "summary": "Romance scam escalation asking the user for travel funds.",
    },
    {
        "code": "INVEST",
        "priority": "high",
        "summary": "Telegram pump-and-dump group directing users to unknown token.",
    },
    {
        "code": "SUPPORT",
        "priority": "low",
        "summary": "Customer-support impersonation featuring fake Coinbase help desk.",
    },
]

STATUS_NOTES: Dict[str, List[str]] = {
    "queued": [
        "Auto-triage pending analyst assignment.",
        "Classifier confidence above threshold; needs verification.",
    ],
    "in_review": [
        "Analyst assigned; reviewing blockchain transfers.",
        "Review in progress; awaiting user callback.",
    ],
    "accepted": [
        "Validated as active scam. Prepare evidence package.",
        "Confirmed scam; escalate to coordination team.",
    ],
    "rejected": [
        "Duplicate of existing case. Closing out.",
        "False positive triggered by mislabeled keywords.",
    ],
}


def _reset_store(store: ReviewStore | SqlAlchemyReviewStore) -> None:
    """Clear all data from the review store."""
    if isinstance(store, ReviewStore):
        with store._connect() as conn:
            conn.execute("DELETE FROM review_actions")
            conn.execute("DELETE FROM review_queue")
            conn.commit()
    elif isinstance(store, SqlAlchemyReviewStore):
        import sqlalchemy as sa
        from i4g.store import sql as sql_schema

        with store._session_factory() as session:
            session.execute(sa.delete(sql_schema.review_actions))
            session.execute(sa.delete(sql_schema.review_queue))
            session.commit()
    else:
        LOGGER.warning("Unknown store type %s; skipping reset.", type(store))


def _seed_case(store: ReviewStore | SqlAlchemyReviewStore, target_status: str) -> None:
    template = random.choice(CASE_TEMPLATES)
    case_id = f"{template['code']}-{uuid4().hex[:8].upper()}"
    review_id = store.enqueue_case(case_id=case_id, priority=template["priority"])

    summary = template["summary"]
    note_suffix = random.choice(STATUS_NOTES[target_status])
    note = f"{summary} {note_suffix}"

    store.update_status(review_id, status=target_status, notes=note)
    store.log_action(
        review_id=review_id,
        actor="synthetic_seed",
        action="status_set",
        payload={"status": target_status, "summary": summary},
    )


def seed_reviews(
    queued: int = 5,
    in_review: int = 2,
    accepted: int = 1,
    rejected: int = 1,
    reset: bool = False,
) -> None:
    """Populate the review store with synthetic queue entries."""
    store = build_review_store()

    if reset:
        LOGGER.info("Resetting review store...")
        _reset_store(store)

    plan: List[str] = []
    for status, count in [
        ("queued", queued),
        ("in_review", in_review),
        ("accepted", accepted),
        ("rejected", rejected),
    ]:
        plan.extend([status] * max(count, 0))
    random.shuffle(plan)

    LOGGER.info("Seeding %d cases...", len(plan))
    for status in plan:
        _seed_case(store, status)
    LOGGER.info("Done.")
