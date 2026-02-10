"""Shared dependencies and models for the review sub-routers.

This module centralises dependency-injection factories and Pydantic
request/response models so that ``review_search``, ``review_queue``,
and ``review_detail`` can share them without circular imports.
"""

import logging
from typing import Any, Dict

from fastapi import Depends

from i4g.services.campaigns import CampaignService
from i4g.services.factories import build_review_store
from i4g.services.hybrid_search import HybridSearchService
from i4g.settings import get_settings
from i4g.store.retriever import HybridRetriever
from i4g.store.review_store import ReviewStore
from i4g.store.sql import session_factory as build_sql_session_factory

logger = logging.getLogger(__name__)

SETTINGS = get_settings()

SEARCH_AUDIT_REVIEW_ID = "audit-search-history"


# ---------------------------------------------------------------------------
# Dependency factories (used via ``Depends(...)`` in sub-routers)
# ---------------------------------------------------------------------------


def get_store() -> ReviewStore:
    """Return a ReviewStore instance (mounted to default DB path).

    Returns:
        A configured ReviewStore instance.
    """
    return build_review_store()


def get_retriever() -> HybridRetriever:
    """Return a HybridRetriever instance.

    Returns:
        A configured HybridRetriever instance.
    """
    return HybridRetriever()


def get_hybrid_search_service() -> HybridSearchService:
    """Return a HybridSearchService instance for dependency injection.

    Returns:
        A configured HybridSearchService instance.
    """
    return HybridSearchService()


def get_db_session():
    """Yield a database session."""
    factory = build_sql_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


def get_campaign_service(session=Depends(get_db_session)) -> CampaignService:
    """Return a configured CampaignService."""
    return CampaignService(session)
