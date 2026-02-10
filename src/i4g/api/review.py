"""Review API router — orchestrator.

Combines the search, queue/action, and detail sub-routers into a
single ``router`` that is mounted by ``app.py`` under ``/reviews``.

Sub-modules:
  - ``review_search``  — search + saved-search CRUD
  - ``review_queue``   — enqueue, claim, annotate, decision
  - ``review_detail``  — single-review detail, case lookup, action history
  - ``review_deps``    — shared dependency factories

Backward-compatible re-exports are provided so that existing imports
(``from i4g.api.review import get_store``, etc.) continue to work.
"""

from fastapi import APIRouter

# Sub-routers ----------------------------------------------------------------
from i4g.api.review_detail import router as detail_router
from i4g.api.review_queue import router as queue_router
from i4g.api.review_search import router as search_router

# Backward-compatible re-exports ---------------------------------------------
from i4g.api.review_deps import (  # noqa: F401 — re-exported for callers
    SEARCH_AUDIT_REVIEW_ID,
    SETTINGS,
    get_campaign_service,
    get_db_session,
    get_hybrid_search_service,
    get_retriever,
    get_store,
)
from i4g.api.review_queue import (  # noqa: F401
    AnnotateRequest,
    DecisionRequest,
    EnqueueRequest,
    generate_report_for_case,
)
from i4g.api.review_search import (  # noqa: F401
    BulkTagUpdateRequest,
    EntityFilterModel,
    HybridSearchRequest,
    SavedSearchCloneRequest,
    SavedSearchImportRequest,
    SavedSearchRequest,
    SavedSearchUpdate,
    TimeRangeModel,
)

# Composite router -----------------------------------------------------------

router = APIRouter()
router.include_router(search_router)
router.include_router(queue_router)
router.include_router(detail_router)
