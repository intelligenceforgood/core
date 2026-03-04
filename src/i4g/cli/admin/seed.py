"""Seed the review queue with synthetic cases."""

from __future__ import annotations

import logging
import random
from uuid import uuid4

from sqlalchemy import delete

from i4g.services.campaigns import CampaignService
from i4g.services.factories import build_review_store
from i4g.store import sql as sql_schema
from i4g.store.review_store import ReviewStore
from i4g.store.sql import session_factory

LOGGER = logging.getLogger(__name__)

DEFAULT_CAMPAIGNS = [
    {
        "name": "Romance scam",
        "description": "Relationship / affection grooming paired with money or asset requests.",
        "taxonomy_labels": {"intent": ["romance"], "techniques": ["grooming"]},
    },
    {
        "name": "Crypto investment",
        "description": "Wallet + coin mentions or high-return investment language.",
        "taxonomy_labels": {"intent": ["investment"]},
    },
    {
        "name": "Phishing",
        "description": "Suspicious login/reset prompts, impersonation, or short-link channels.",
        "taxonomy_labels": {"techniques": ["phishing", "impersonation"]},
    },
    {
        "name": "Potential crypto",
        "description": "Wallets present but weak pattern match; queue for analyst confirmation.",
        "taxonomy_labels": {"actions": ["crypto_transfer"]},
    },
]

CASE_TEMPLATES: list[dict[str, str]] = [
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

STATUS_NOTES: dict[str, list[str]] = {
    "new": [
        "Auto-triage pending analyst assignment.",
        "Classifier confidence above threshold; needs verification.",
    ],
    "in_review": [
        "Analyst assigned; reviewing blockchain transfers.",
        "Review in progress; awaiting user callback.",
    ],
    "awaiting_input": [
        "Blocked on external response from exchange.",
        "Waiting for victim to provide additional screenshots.",
    ],
    "accepted": [
        "Validated as active scam. Prepare evidence package.",
        "Confirmed scam; escalate to coordination team.",
        "Duplicate of existing case. Merged into primary.",
    ],
    "rejected": [
        "False positive triggered by mislabeled keywords.",
        "User confirmed legitimate transaction.",
    ],
}


def _reset_store(store: ReviewStore) -> None:
    """Clear all data from the review store."""
    with store._session_factory() as session:
        session.execute(delete(sql_schema.review_actions))
        session.execute(delete(sql_schema.review_queue))
        session.commit()


def _seed_case(store: ReviewStore, target_status: str) -> None:
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
    include_static: bool = False,
) -> None:
    """Populate the review store with synthetic queue entries."""
    from i4g.cli.bootstrap.seed import seed_static_review_cases

    store = build_review_store()

    if reset:
        LOGGER.info("Resetting review store...")
        _reset_store(store)

    plan: list[str] = []
    # Map counts to new statuses
    for status, count in [
        ("new", queued),
        ("in_review", in_review),  # Replaces 'active'
        ("accepted", accepted),  # Replaces 'closed'
        ("rejected", rejected),  # Replaces 'closed'
    ]:
        plan.extend([status] * max(count, 0))
    random.shuffle(plan)

    LOGGER.info("Seeding %d cases...", len(plan))
    for status in plan:
        _seed_case(store, status)

    if include_static:
        LOGGER.info("Seeding static review cases...")
        seed_static_review_cases()

    LOGGER.info("Done.")


def seed_campaigns() -> None:
    """Populate database with default active campaigns if missing."""
    LOGGER.info("Seeding default campaigns...")
    make_session = session_factory()
    with make_session() as session:
        service = CampaignService(session)
        existing = service.list_active_campaigns()
        existing_names = {c["name"] for c in existing}

        count = 0
        for campaign in DEFAULT_CAMPAIGNS:
            if campaign["name"] not in existing_names:
                service.create_campaign(
                    name=campaign["name"],
                    description=campaign["description"],
                    taxonomy_labels=campaign["taxonomy_labels"],
                )
                count += 1
        LOGGER.info("Created %d new campaigns (total %d).", count, len(DEFAULT_CAMPAIGNS))
