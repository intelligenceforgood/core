"""Scope registry and endpoint access restrictions for the i4g API.

Defines authentication sources, allowed tag sets for partner versus internal API
endpoints, and dependencies for enforcing internal session restrictions.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from fastapi import Depends, HTTPException, status

from i4g.api.auth import require_token


class AuthSource(StrEnum):
    """Authentication sources for API requests."""

    LOCAL = "local"
    STATIC_KEY = "static_key"
    DB_API_KEY = "db_api_key"
    IAP = "iap"
    BEARER = "bearer"


#: Tags representing endpoints allowed for external partner integrations.
PARTNER_ALLOWED_TAGS: set[str] = {
    "partner-feeds",
    "cases",
    "evidence",
    "reviews",
    "analytics",
    "discovery",
    "intelligence",
    "investigations",
    "ssi",
    "exports",
    "taxonomy",
}

#: Tags representing endpoints restricted to internal sessions / Web UI / Mobile.
INTERNAL_ONLY_TAGS: set[str] = {
    "accounts",
    "api-keys",
    "tasks",
    "dashboard",
    "engagements",
    "campaigns",
    "impact",
    "feedback",
    "intakes",
    "playbooks",
    "actors",
    "discoveries",
    "ssi-events",
    "wallets",
    "reports",
    "health",
}


def require_internal_session(
    user: dict[str, Any] = Depends(require_token),
) -> dict[str, Any]:
    """Dependency enforcing that an endpoint is accessed via an internal session.

    Programmatic DB-backed API keys are blocked unless they explicitly possess
    the ``admin:internal`` scope. All other authentication sources (local dev,
    static API key, IAP, Bearer tokens) pass through without restriction.

    Args:
        user: Authenticated user dictionary from ``require_token``.

    Returns:
        The validated user dictionary.

    Raises:
        HTTPException: 403 Forbidden if a DB-backed API key lacks ``admin:internal``.
    """
    auth_source = user.get("auth_source")
    if auth_source == AuthSource.DB_API_KEY:
        scopes = user.get("scopes") or []
        if "admin:internal" not in scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API key access not permitted for this endpoint",
            )
    return user
