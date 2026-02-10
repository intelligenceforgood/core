"""Token-based auth helpers for i4g API.

Local environments (``I4G_ENV=local``) bypass all authentication so
developers can iterate without token overhead.  Non-local environments
(dev, prod) require a valid ``X-API-KEY`` header.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, Optional

from fastapi import Depends, Header, HTTPException, status

from i4g.settings import get_settings

logger = logging.getLogger(__name__)

# Minimal token -> user mapping for prototype.
# In production, use a proper identity provider.
_API_TOKENS: Dict[str, Dict[str, str]] = {
    "dev-analyst-token": {"username": "analyst_1", "role": "analyst"},
    "dev-admin-token": {"username": "admin", "role": "admin"},
}

_LOCAL_USER: Dict[str, str] = {"username": "local-dev", "role": "admin"}


def is_valid_api_token(token: Optional[str]) -> bool:
    """Return True when the provided API key resolves to a known user."""

    return bool(token and token in _API_TOKENS)


def require_token(x_api_key: Optional[str] = Header(None)) -> Dict[str, str]:
    """Validate API key header and return user info.

    When ``settings.identity.disable_auth`` is ``True`` (always the case
    for ``I4G_ENV=local``), authentication is bypassed and a mock admin
    user is returned.

    Args:
        x_api_key: Value of the ``X-API-KEY`` header.

    Returns:
        User info dict with ``username`` and ``role`` keys.

    Raises:
        HTTPException: 401 if header is missing; 403 if token is invalid.
    """
    settings = get_settings()
    if settings.identity.disable_auth:
        # Auth is disabled (local env).  Still honour an explicit token so
        # that automated tests and local tooling that sends a token get the
        # correct user identity back.
        if x_api_key:
            user = _API_TOKENS.get(x_api_key)
            if user:
                return user
        return _LOCAL_USER

    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-API-KEY")
    user = _API_TOKENS.get(x_api_key)
    if not user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")
    return user


def require_role(required_role: str) -> Callable:
    """Dependency factory that enforces a required role (analyst/admin)."""

    def _checker(user: Dict[str, str] = Depends(require_token)) -> Dict[str, str]:
        role = user.get("role")
        if role == required_role or role == "admin":
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    return _checker
