"""Tokenization and detokenization API endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from i4g.api.auth import require_role, require_token
from i4g.api.response_models import DetokenizeResponse, TokenizationHealthResponse, TokenizeResponse
from i4g.pii.tokenization import TokenizationService
from i4g.services.alerting import get_alerting_service
from i4g.services.factories import build_tokenization_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tokenization", tags=["tokenization"])


class TokenizeRequest(BaseModel):
    """Request body for tokenization."""

    value: str = Field(..., description="Raw PII value to tokenize")
    prefix: str | None = Field(None, description="PII prefix code (e.g., EID, PHN)")
    entity_type: str | None = Field(None, description="Entity type used to derive the prefix")
    detector: str | None = Field(None, description="Detector identifier for observability")
    case_id: str | None = Field(None, description="Optional case identifier")


class DetokenizeRequest(BaseModel):
    """Request body for detokenization."""

    token: str = Field(..., description="Previously issued token")
    case_id: str | None = Field(None, description="Optional case identifier")


def get_tokenization_service() -> TokenizationService:
    """Dependency injector for tokenization service."""

    return build_tokenization_service()


@router.post("/tokenize", response_model=TokenizeResponse)
def tokenize(
    request: TokenizeRequest,
    service: TokenizationService = Depends(get_tokenization_service),
    user=Depends(require_token),
):
    """Tokenize a single PII value and return the token payload."""

    prefix = request.prefix or service.resolve_prefix(request.entity_type)
    try:
        result = service.tokenize(
            request.value,
            prefix,
            detector=request.detector or request.entity_type,
            case_id=request.case_id,
        )
    except ValueError as exc:
        logger.warning("tokenize: bad request: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:  # pragma: no cover - unexpected errors mapped to 500
        logger.error("tokenize: unexpected error", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    return {
        "token": result.token,
        "prefix": result.prefix,
        "digest": result.digest,
        "normalized_value": result.normalized_value,
        "pepper_version": result.pepper_version,
    }


@router.post("/detokenize", response_model=DetokenizeResponse)
def detokenize(
    request: DetokenizeRequest,
    service: TokenizationService = Depends(get_tokenization_service),
    user=Depends(require_role("analyst")),
):
    """Return the canonical value for a token, if present in the vault."""

    actor = user.get("username", "unknown")
    alerting = get_alerting_service()
    alerting.check_detokenization_rate(actor=actor, case_id=request.case_id)

    record = service.detokenize(request.token, actor=actor, case_id=request.case_id)
    if record is None or record.canonical_value is None:
        logger.debug("detokenize: token not found: %s", request.token)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found or lacks canonical value")

    return {
        "token": record.token,
        "prefix": record.prefix,
        "canonical_value": record.canonical_value,
        "pepper_version": record.pepper_version,
        "case_id": record.case_id,
        "detector": record.detector,
        "created_at": record.created_at,
    }


@router.get("/health", response_model=TokenizationHealthResponse)
def tokenization_health(
    service: TokenizationService = Depends(get_tokenization_service),
    user=Depends(require_token),
):
    """Expose a lightweight readiness check for tokenization secrets."""

    return {
        "pepper_configured": bool(service.pepper),
        "pepper_version": service.pepper_version,
        "encryption_enabled": bool(service._fernet),
    }
