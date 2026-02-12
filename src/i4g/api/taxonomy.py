"""Provide taxonomy metadata for the UI taxonomy explorer."""

import logging

from fastapi import APIRouter, Depends

from i4g.api.auth import require_token
from i4g.api.response_models import TaxonomyResponse
from i4g.taxonomy.data import TAXONOMY_DEFINITIONS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/taxonomy", tags=["taxonomy"], dependencies=[Depends(require_token)])


@router.get("", summary="Return the taxonomy tree", response_model=TaxonomyResponse)
def get_taxonomy() -> dict[str, object]:
    """Serve the taxonomy hierarchy that backs the UI filters."""

    return TAXONOMY_DEFINITIONS
