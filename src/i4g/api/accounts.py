"""User account management API endpoints (RBAC).

Provides ``/accounts/me`` for the current user's identity and role,
``GET /accounts`` to list all users (admin-only), and
``PUT /accounts/{email}/role`` for role assignment (admin-only).

Note: This module is distinct from ``account_list.py`` which handles
*financial* account-list extraction for fraud indicators.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from i4g.api.auth import require_role, require_token
from i4g.api.camel import CamelModel
from i4g.api.scopes import require_internal_session
from i4g.store.account_store import AccountStore
from i4g.store.sql import session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/accounts", tags=["accounts"], dependencies=[Depends(require_internal_session)])


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def get_account_store() -> AccountStore:
    """Dependency injector for AccountStore."""
    return AccountStore(session_factory())


# ---------------------------------------------------------------------------
# Response / Request models
# ---------------------------------------------------------------------------


class AccountResponse(CamelModel):
    """Public account representation."""

    email: str
    role: str
    display_name: str | None = None
    is_active: bool = True


class AccountListResponse(CamelModel):
    """Wrapper for account list."""

    items: list[AccountResponse]
    count: int


class UpdateRoleRequest(BaseModel):
    """Admin request to change a user's role."""

    role: str = Field(..., description="New role value (user, analyst, admin, leo)")


class UpdateRoleResponse(CamelModel):
    """Response after a role change."""

    email: str
    old_role: str
    new_role: str
    updated: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/me", response_model=AccountResponse, summary="Current user identity")
def get_current_user(
    user: dict[str, str] = Depends(require_token),
    store: AccountStore = Depends(get_account_store),
) -> dict[str, Any]:
    """Return the authenticated user's account info including role.

    This is the primary endpoint for the UI to discover the current
    user's identity and permissions.
    """
    email = user["username"]
    account = store.get_or_create_account(email)
    # Use the auth-resolved role (which comes from _resolve_role() in
    # production, or from _LOCAL_USER in local env) rather than the raw
    # DB snapshot, so the UI always sees the effective permission level.
    return {
        "email": account["email"],
        "role": user["role"],
        "display_name": account.get("display_name"),
        "is_active": account.get("is_active", True),
    }


@router.get("", response_model=AccountListResponse, summary="List all accounts (admin)")
def list_accounts(
    active_only: bool = True,
    user: dict[str, str] = Depends(require_role("admin")),
    store: AccountStore = Depends(get_account_store),
) -> dict[str, Any]:
    """Return all user accounts. Requires admin role."""
    accounts = store.list_accounts(active_only=active_only)
    items = [
        {
            "email": a["email"],
            "role": a["role"],
            "display_name": a.get("display_name"),
            "is_active": a.get("is_active", True),
        }
        for a in accounts
    ]
    return {"items": items, "count": len(items)}


@router.put("/{email}/role", response_model=UpdateRoleResponse, summary="Assign role (admin)")
def update_user_role(
    email: str,
    payload: UpdateRoleRequest,
    user: dict[str, str] = Depends(require_role("admin")),
    store: AccountStore = Depends(get_account_store),
) -> dict[str, Any]:
    """Change a user's role. Requires admin role.

    The change is audited in the ``review_actions`` table.

    Args:
        email: Target user's email.
        payload: New role assignment.
        user: The authenticated admin (injected).
        store: Account store instance.

    Returns:
        Confirmation with old and new roles.
    """
    # Prevent self-demotion from admin (safety net).
    if email == user["username"] and payload.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove your own admin role. Ask another admin.",
        )

    existing = store.get_account(email)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account {email!r} not found",
        )

    old_role = existing["role"]
    try:
        updated = store.update_role(email, payload.role, actor=user["username"])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))  # noqa: B904

    if updated is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update role")

    return {
        "email": email,
        "old_role": old_role,
        "new_role": payload.role,
        "updated": True,
    }


@router.put("/{email}/deactivate", summary="Deactivate account (admin)")
def deactivate_account(
    email: str,
    user: dict[str, str] = Depends(require_role("admin")),
    store: AccountStore = Depends(get_account_store),
) -> dict[str, Any]:
    """Deactivate a user account. Requires admin role.

    Deactivated users will receive 403 on subsequent requests.
    """
    if email == user["username"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account.",
        )

    success = store.deactivate_account(email, actor=user["username"])
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Account {email!r} not found")

    return {"email": email, "deactivated": True}


@router.put("/{email}/reactivate", summary="Reactivate account (admin)")
def reactivate_account(
    email: str,
    user: dict[str, str] = Depends(require_role("admin")),
    store: AccountStore = Depends(get_account_store),
) -> dict[str, Any]:
    """Reactivate a previously deactivated user account. Requires admin role."""
    success = store.reactivate_account(email, actor=user["username"])
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Account {email!r} not found")

    return {"email": email, "reactivated": True}
