"""Auth helpers for i4g API.

Local environments (``I4G_ENV=local``) bypass all authentication so
developers can iterate without token overhead.  Non-local environments
(dev, prod) verify Google IAP JWT tokens or fall back to the configured
``settings.api.key`` for service-to-service calls.
"""

from __future__ import annotations

import logging
from typing import Callable

from fastapi import Depends, Header, HTTPException, Request, status

from i4g.settings import get_settings

logger = logging.getLogger(__name__)

_LOCAL_USER: dict[str, str] = {"username": "local-dev", "role": "admin"}

# Cache for the Google public-key verifier (lazy-loaded).
_iap_verify = None


def _verify_iap_jwt(token: str) -> dict[str, str] | None:
    """Verify a Google IAP JWT and return user info, or *None* on failure.

    Uses ``google.oauth2.id_token.verify_token`` which fetches Google's
    public keys and validates signature, audience, issuer and expiry.
    """
    global _iap_verify  # noqa: PLW0603

    settings = get_settings()
    try:
        if _iap_verify is None:
            from google.auth.transport import requests as g_requests  # noqa: I001
            from google.oauth2 import id_token as g_id_token

            _iap_verify = (g_id_token, g_requests.Request())

        id_token_mod, g_request = _iap_verify
        # IAP tokens use the OAuth client-id as audience.
        audience = settings.identity.audience or settings.identity.client_id
        payload = id_token_mod.verify_token(token, g_request, audience=audience)
        email = payload.get("email", "unknown")
        return {"username": email, "role": "admin"}
    except Exception:
        logger.debug("IAP JWT verification failed", exc_info=True)
        return None


def is_valid_api_token(token: str | None) -> bool:
    """Return True when *token* matches the configured API key."""
    if not token:
        return False
    settings = get_settings()
    return token == settings.api.key


def require_token(
    request: Request,
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
) -> dict[str, str]:
    """Validate the request and return user info.

    Authentication strategy (checked in order):

    1. **Auth disabled** (``settings.identity.disable_auth`` /
       ``I4G_ENV=local``): returns a mock admin user.
    2. **IAP JWT** — ``X-Goog-IAP-JWT-Assertion`` header set by
       Google IAP at the load-balancer level. Verified via Google
       public keys.
    3. **Bearer token** — ``Authorization: Bearer <token>`` sent by
       the UI server or other callers with a Google ID token targeting
       the Cloud Run service.
    4. **API key** — ``X-API-KEY`` header matching ``settings.api.key``
       (set via ``I4G_API__KEY`` env var). Used for service-to-service
       calls from Cloud Run jobs.

    All authenticated Cloud users receive full (admin) access as a
    temporary measure until a full RBAC system is built.

    Args:
        request: The incoming FastAPI request.
        x_api_key: Value of the ``X-API-KEY`` header.
        authorization: Value of the ``Authorization`` header.

    Returns:
        User info dict with ``username`` and ``role`` keys.

    Raises:
        HTTPException: 401 if no valid credential is found.
    """
    settings = get_settings()

    # ── 1. Auth disabled (local) ──────────────────────────────────
    if settings.identity.disable_auth:
        return _LOCAL_USER

    # ── 2. IAP JWT (load-balancer path) ───────────────────────────
    iap_jwt = request.headers.get("X-Goog-IAP-JWT-Assertion")
    if iap_jwt:
        user = _verify_iap_jwt(iap_jwt)
        if user:
            return user
        logger.warning("IAP JWT present but verification failed")

    # ── 3. Bearer token (service-to-service via Authorization) ────
    if authorization and authorization.lower().startswith("bearer "):
        bearer_token = authorization.split(" ", 1)[1]
        user = _verify_iap_jwt(bearer_token)
        if user:
            return user

    # ── 4. API key (env-var-configured, for jobs / CLI) ───────────
    if x_api_key and x_api_key == settings.api.key:
        return {"username": "service", "role": "admin"}

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid credentials",
    )


def require_role(required_role: str) -> Callable:
    """Dependency factory that enforces a required role (analyst/admin)."""

    def _checker(user: dict[str, str] = Depends(require_token)) -> dict[str, str]:
        role = user.get("role")
        if role == required_role or role == "admin":
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    return _checker
