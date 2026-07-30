"""Scope enforcement middleware/dependency for i4g API."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException, status

from i4g.api.auth import require_token
from i4g.api.roles import Role

logger = logging.getLogger(__name__)


def require_scope(*required_scopes: str) -> Callable:
    """Dependency factory enforcing required scopes for API keys/tokens.

    Admin role automatically bypasses scope requirements.

    Args:
        *required_scopes: Scopes required to access the endpoint.

    Returns:
        A FastAPI dependency function that validates user scopes.
    """

    def _checker(user: dict[str, Any] = Depends(require_token)) -> dict[str, Any]:
        user_role = user.get("role", "")
        if user_role in (Role.ADMIN.value, "admin"):
            return user

        user_scopes = set(user.get("scopes") or [])
        if "*" in user_scopes:
            return user

        missing_scopes = [s for s in required_scopes if s not in user_scopes]
        if missing_scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient scope: missing {', '.join(missing_scopes)}",
            )
        return user

    return _checker
