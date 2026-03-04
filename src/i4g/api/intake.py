"""FastAPI router exposing intake submission endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, ValidationError

from i4g.api.auth import require_token
from i4g.api.response_models import (
    IntakeCaseAttachResponse,
    IntakeCreateResponse,
    IntakeJobResponse,
    IntakeJobUpdateResponse,
    IntakeRecordResponse,
    IntakeStatusUpdateResponse,
    ItemListResponse,
)
from i4g.services.intake import AttachmentPayload, IntakeService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/intakes", tags=["intakes"])


class IntakeSubmission(BaseModel):
    reporter_name: str
    summary: str
    details: str
    submitted_by: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    contact_handle: str | None = None
    preferred_contact: str | None = None
    incident_date: str | None = None
    loss_amount: float | None = None
    source: str = "unknown"
    metadata: dict[str, Any] = Field(default_factory=dict)


class IntakeJobUpdate(BaseModel):
    status: str
    message: str | None = None
    metadata: dict[str, Any] | None = None


class IntakeStatusUpdate(BaseModel):
    status: str
    message: str | None = None


class IntakeCaseAttachment(BaseModel):
    case_id: str | None = None
    review_id: str | None = None


def get_service() -> IntakeService:
    return IntakeService()


@router.post("/", summary="Submit a new intake", status_code=201, response_model=IntakeCreateResponse)
async def submit_intake(
    background_tasks: BackgroundTasks,
    payload: str = Form(..., description="JSON payload describing the intake metadata"),
    files: list[UploadFile] = File(default_factory=list, description="Evidence attachments"),
    user=Depends(require_token),
    service: IntakeService = Depends(get_service),
):
    try:
        submission_model = IntakeSubmission.model_validate_json(payload)
    except ValidationError as exc:  # pragma: no cover - FastAPI converts automatically in most flows
        logger.warning("submit_intake: invalid payload: %s", exc.errors()[0]["msg"])
        raise HTTPException(status_code=400, detail={"error": "invalid_payload", "details": exc.errors()}) from exc

    submission = submission_model.model_dump()
    submission.setdefault("metadata", {})
    submission["submitted_by"] = submission.get("submitted_by") or user.get("username") or "unknown"
    if not submission["submitted_by"]:
        raise HTTPException(status_code=400, detail="submitted_by is required")

    attachments: list[AttachmentPayload] = []
    for upload in files:
        data = await upload.read()
        attachments.append(
            AttachmentPayload(
                file_name=upload.filename or "upload",
                data=data,
                content_type=upload.content_type,
            )
        )

    result = service.create_intake(
        submission, attachments, create_job=True, job_metadata={"submitted_by": submission["submitted_by"]}
    )
    logger.info(
        "submit_intake: intake_id=%s job_id=%s attachments=%d", result["intake_id"], result["job_id"], len(attachments)
    )

    if result["job_id"]:
        background_tasks.add_task(service.process_job, result["intake_id"], result["job_id"])

    record = service.get_intake(result["intake_id"]) or {}

    return {
        "intake_id": result["intake_id"],
        "job_id": result["job_id"],
        "attachments": result["attachments"],
        "status": record.get("status", "received"),
        "job": record.get("job"),
    }


@router.get("/", summary="List recent intakes", response_model=ItemListResponse)
def list_intakes(
    limit: int = Query(25, ge=1, le=200),
    user=Depends(require_token),
    service: IntakeService = Depends(get_service),
):
    items = service.list_intakes(limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/{intake_id}", summary="Fetch intake details", response_model=IntakeRecordResponse)
def get_intake(intake_id: str, user=Depends(require_token), service: IntakeService = Depends(get_service)):
    record = service.get_intake(intake_id)
    if not record:
        raise HTTPException(status_code=404, detail="Intake not found")
    return record


@router.get("/jobs/{job_id}", summary="Fetch intake job status", response_model=IntakeJobResponse)
def get_job(job_id: str, user=Depends(require_token), service: IntakeService = Depends(get_service)):
    job = service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/jobs/{job_id}", summary="Update an intake job status", response_model=IntakeJobUpdateResponse)
def update_job(
    job_id: str,
    payload: IntakeJobUpdate,
    service: IntakeService = Depends(get_service),
    user=Depends(require_token),
):
    updated = service.update_job_status(
        job_id, status=payload.status, message=payload.message, metadata=payload.metadata
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"updated": True, "job_id": job_id}


@router.post("/{intake_id}/status", summary="Update intake status", response_model=IntakeStatusUpdateResponse)
def update_intake_status(
    intake_id: str,
    payload: IntakeStatusUpdate,
    service: IntakeService = Depends(get_service),
    user=Depends(require_token),
):
    service.update_intake_status(intake_id, status=payload.status, message=payload.message)
    return {"updated": True, "intake_id": intake_id}


@router.post("/{intake_id}/case", summary="Attach case metadata to intake", response_model=IntakeCaseAttachResponse)
def attach_case(
    intake_id: str,
    payload: IntakeCaseAttachment,
    service: IntakeService = Depends(get_service),
    user=Depends(require_token),
):
    service.attach_case(intake_id, case_id=payload.case_id, review_id=payload.review_id)
    return {"updated": True, "intake_id": intake_id, "case_id": payload.case_id, "review_id": payload.review_id}


__all__ = ["router"]
