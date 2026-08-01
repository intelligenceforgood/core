"""API Key management endpoints (self-service & admin).

Provides REST endpoints for users to generate, list, and revoke their own API keys,
and for admins to manage all system keys and provision partner API keys.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ConfigDict, Field, field_validator

from i4g.api.auth import require_role, require_token
from i4g.api.camel import CamelModel
from i4g.api.scopes import require_internal_session
from i4g.services.factories import build_api_key_store

logger = logging.getLogger(__name__)

router = APIRouter(tags=["api-keys"])


# ------------------------------------------------------------------
# Request & Response Schemas
# ------------------------------------------------------------------


class CreateApiKeyRequest(CamelModel):
    """Request payload for user self-service API key creation."""

    description: str = Field(..., description="Human-readable description for the API key")
    scopes: list[str] | None = Field(default=None, description="Optional scopes granted to the key")
    expires_in_days: int | None = Field(default=None, description="Days until expiration (None for perpetual)")


class CreatePartnerKeyRequest(CamelModel):
    """Request payload for admin partner API key creation."""

    partner_name: str = Field(..., description="Partner organization name")
    owner_email: str | None = Field(default=None, description="Owner email for partner key")
    scopes: list[str] | None = Field(default=None, description="Scopes granted to partner key")
    expires_in_days: int | None = Field(default=None, description="Days until expiration (None for perpetual)")
    rate_limit_per_minute: int | None = Field(default=60, description="Per-minute rate limit")
    description: str | None = Field(default=None, description="Optional description")


class CreateApiKeyResponse(CamelModel):
    """Response payload containing the generated raw key (shown ONCE)."""

    raw_key: str
    key_id: str
    key_prefix: str
    expires_at: datetime | None = None


class ApiKeyInfo(CamelModel):
    """Public details of an API key (excludes hash and raw key)."""

    model_config = ConfigDict(
        alias_generator=CamelModel.model_config.get("alias_generator"),
        populate_by_name=True,
        extra="ignore",
    )

    key_id: str
    key_prefix: str
    description: str | None = None
    owner_email: str | None = None
    key_type: str = "partner"
    partner_name: str | None = None
    scopes: list[str] = Field(default_factory=list)
    is_active: bool = True
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime

    @field_validator("scopes", mode="before")
    @classmethod
    def _validate_scopes(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            import json

            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
            except Exception:
                pass
            return [v]
        return v

    @field_validator("key_type", mode="before")
    @classmethod
    def _validate_key_type(cls, v: Any) -> str:
        if not v:
            return "partner"
        return str(v)


class ApiKeyListResponse(CamelModel):
    """Response payload listing API keys."""

    keys: list[ApiKeyInfo]


# ------------------------------------------------------------------
# Self-Service User Endpoints
# ------------------------------------------------------------------


@router.post("/api-keys", response_model=CreateApiKeyResponse, status_code=status.HTTP_201_CREATED)
def create_user_api_key(
    req: CreateApiKeyRequest,
    current_user: dict[str, Any] = Depends(require_token),
) -> CreateApiKeyResponse:
    """Create a new self-service API key for the authenticated user."""
    if req.expires_in_days is not None and req.expires_in_days <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="expires_in_days must be positive",
        )

    owner_email = current_user.get("username")
    store = build_api_key_store()
    raw_key, record = store.create_key(
        owner_email=owner_email,
        key_type="user",
        description=req.description,
        scopes=req.scopes or [],
        expires_in_days=req.expires_in_days,
        created_by=owner_email or "system",
    )

    return CreateApiKeyResponse(
        raw_key=raw_key,
        key_id=record["key_id"],
        key_prefix=record["key_prefix"],
        expires_at=record["expires_at"],
    )


@router.get("/api-keys", response_model=ApiKeyListResponse)
def list_user_api_keys(
    current_user: dict[str, Any] = Depends(require_token),
) -> ApiKeyListResponse:
    """List API keys owned by the authenticated user."""
    owner_email = current_user.get("username")
    if not owner_email:
        return ApiKeyListResponse(keys=[])

    store = build_api_key_store()
    records = store.list_keys_for_owner(owner_email=owner_email)
    keys = [ApiKeyInfo(**r) for r in records]
    return ApiKeyListResponse(keys=keys)


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_user_api_key(
    key_id: str,
    current_user: dict[str, Any] = Depends(require_token),
) -> None:
    """Revoke an API key owned by the authenticated user."""
    owner_email = current_user.get("username")
    store = build_api_key_store()
    success = store.revoke_key(key_id=key_id, owner_email=owner_email)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or not owned by user",
        )


# ------------------------------------------------------------------
# Admin Controls Endpoints
# ------------------------------------------------------------------


@router.get("/admin/api-keys", response_model=ApiKeyListResponse, dependencies=[Depends(require_internal_session)])
def admin_list_api_keys(
    key_type: str | None = None,
    active_only: bool = False,
    current_user: dict[str, Any] = Depends(require_role("admin")),
) -> ApiKeyListResponse:
    """Admin endpoint to list all API keys in the system."""
    store = build_api_key_store()
    records = store.list_all_keys(key_type=key_type, active_only=active_only)
    keys = [ApiKeyInfo(**r) for r in records]
    return ApiKeyListResponse(keys=keys)


@router.delete(
    "/admin/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_internal_session)],
)
def admin_revoke_api_key(
    key_id: str,
    current_user: dict[str, Any] = Depends(require_role("admin")),
) -> None:
    """Admin endpoint to revoke any API key by key_id."""
    store = build_api_key_store()
    success = store.revoke_key(key_id=key_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or already revoked",
        )


@router.post(
    "/admin/api-keys/partner",
    response_model=CreateApiKeyResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_internal_session)],
)
def admin_create_partner_api_key(
    req: CreatePartnerKeyRequest,
    current_user: dict[str, Any] = Depends(require_role("admin")),
) -> CreateApiKeyResponse:
    """Admin endpoint to provision a partner-type API key."""
    if req.expires_in_days is not None and req.expires_in_days <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="expires_in_days must be positive",
        )

    admin_email = current_user.get("username")
    store = build_api_key_store()
    owner_email = req.owner_email or (req.partner_name if "@" in req.partner_name else None)
    raw_key, record = store.create_key(
        owner_email=owner_email,
        key_type="partner",
        partner_name=req.partner_name,
        description=req.description,
        scopes=req.scopes or ["partner:feed"],
        expires_in_days=req.expires_in_days,
        rate_limit_per_minute=req.rate_limit_per_minute or 60,
        created_by=admin_email or "admin",
    )

    return CreateApiKeyResponse(
        raw_key=raw_key,
        key_id=record["key_id"],
        key_prefix=record["key_prefix"],
        expires_at=record["expires_at"],
    )
