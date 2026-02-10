"""Campaign management endpoints."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from i4g.api.auth import require_token
from i4g.services.campaigns import CampaignService
from i4g.store.sql import session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/campaigns", tags=["campaigns"], dependencies=[Depends(require_token)])


def get_db_session():
    """Yield a database session."""
    factory = session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


def get_service(session: Session = Depends(get_db_session)) -> CampaignService:
    return CampaignService(session)


class CampaignResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    taxonomy_labels: Optional[Dict[str, Any]] = None
    taxonomy_rollup: List[str] = []


class CreateCampaignRequest(BaseModel):
    name: str
    description: str
    taxonomy_labels: Dict[str, Any]
    associated_taxonomy_ids: Optional[List[str]] = None


class UpdateCampaignRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    taxonomy_labels: Optional[Dict[str, Any]] = None
    associated_taxonomy_ids: Optional[List[str]] = None


@router.get("", response_model=List[CampaignResponse])
def list_campaigns(service: CampaignService = Depends(get_service)):
    return service.list_active_campaigns()


@router.post("", response_model=str)
def create_campaign(payload: CreateCampaignRequest, service: CampaignService = Depends(get_service)):
    logger.info("create_campaign: name=%r", payload.name)
    try:
        return service.create_campaign(
            name=payload.name,
            description=payload.description,
            taxonomy_labels=payload.taxonomy_labels,
            associated_taxonomy_ids=payload.associated_taxonomy_ids,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{campaign_id}", response_model=Dict[str, Any])
def update_campaign(campaign_id: str, payload: UpdateCampaignRequest, service: CampaignService = Depends(get_service)):
    logger.info("update_campaign: campaign_id=%s", campaign_id)
    try:
        service.update_campaign(
            campaign_id=campaign_id,
            name=payload.name,
            description=payload.description,
            taxonomy_labels=payload.taxonomy_labels,
            associated_taxonomy_ids=payload.associated_taxonomy_ids,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"updated": True, "campaign_id": campaign_id}
