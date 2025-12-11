"""Tokenization and detokenization API endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from i4g.api.auth import require_token
from i4g.pii.tokenization import TokenizationService
from i4g.services.factories import build_tokenization_service

router = APIRouter(prefix="/tokenization", tags=["tokenization"])


class TokenizeRequest(BaseModel):
    """Request body for tokenization."""

    value: str = Field(..., description="Raw PII value to tokenize")
    prefix: Optional[str] = Field(None, description="PII prefix code (e.g., EID, PHN)")
    entity_type: Optional[str] = Field(None, description="Entity type used to derive the prefix")
    detector: Optional[str] = Field(None, description="Detector identifier for observability")
    case_id: Optional[str] = Field(None, description="Optional case identifier")


class DetokenizeRequest(BaseModel):
    """Request body for detokenization."""

    token: str = Field(..., description="Previously issued token")
    case_id: Optional[str] = Field(None, description="Optional case identifier")


def get_tokenization_service() -> TokenizationService:
    """Dependency injector for tokenization service."""

    return build_tokenization_service()


@router.post("/tokenize")
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:  # pragma: no cover - unexpected errors mapped to 500
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    return {
        "token": result.token,
        "prefix": result.prefix,
        "digest": result.digest,
        "normalized_value": result.normalized_value,
        "pepper_version": result.pepper_version,
    }


@router.post("/detokenize")
def detokenize(
    request: DetokenizeRequest,
    service: TokenizationService = Depends(get_tokenization_service),
    user=Depends(require_token),
):
    """Return the canonical value for a token, if present in the vault."""

    record = service.detokenize(request.token, actor=user.get("username"), case_id=request.case_id)
    if record is None or record.canonical_value is None:
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


@router.get("/health")
def tokenization_health(service: TokenizationService = Depends(get_tokenization_service)):
    """Expose a lightweight readiness check for tokenization secrets."""

    return {
        "pepper_configured": bool(service.pepper),
        "pepper_version": service.pepper_version,
        "encryption_enabled": bool(service._fernet),
    }
