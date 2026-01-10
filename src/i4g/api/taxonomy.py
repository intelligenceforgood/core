"""Provide taxonomy metadata for the UI taxonomy explorer."""

from fastapi import APIRouter

from i4g.taxonomy.data import TAXONOMY_DEFINITIONS

router = APIRouter(prefix="/taxonomy", tags=["taxonomy"])


@router.get("", summary="Return the taxonomy tree")
def get_taxonomy() -> dict[str, object]:
    """Serve the taxonomy hierarchy that backs the UI filters."""

    return TAXONOMY_DEFINITIONS
