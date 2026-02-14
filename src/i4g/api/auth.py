"""Auth helpers for i4g API.

Local environments (``I4G_ENV=local``) bypass all authentication so
developers can iterate without token overhead.  Non-local environments
(dev, prod) verify Google IAP JWT tokens or fall back to the configured
``settings.api.key`` for service-to-service calls.

**RBAC (WS-5):**  After authentication, the user's role is resolved from
the ``accounts`` table via ``AccountStore.get_or_create_account()``.
First-time users are auto-provisioned with ``DEFAULT_ROLE`` (user).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import Depends, Header, HTTPException, Request, status

from i4g.api.roles import Role, has_role
from i4g.settings import get_settings

logger = logging.getLogger(__name__)

_LOCAL_USER: dict[str, str] = {"username": "local-dev", "role": "admin"}

# Cache for the Google public-key verifier (lazy-loaded).
_iap_verify = None

# Lazy-loaded account store (avoids import-time DB initialization).
_account_store = None

# IAP assertions use a dedicated signing-key endpoint — separate from
# the standard OIDC certs used for regular Google ID tokens.
_IAP_CERTS_URL = "https://www.gstatic.com/iap/verify/public_key-jwk"


def _get_account_store():
    """Return a lazily initialized ``AccountStore``."""
    global _account_store  # noqa: PLW0603
    if _account_store is None:
        from i4g.store.account_store import AccountStore
        from i4g.store.sql import session_factory

        _account_store = AccountStore(session_factory())
    return _account_store


def _resolve_role(email: str) -> str:
    """Look up the role for *email* from the accounts table.

    Auto-provisions the account with the default role on first login.

    Args:
        email: The authenticated user's email.

    Returns:
        The role string from the ``accounts`` table.
    """
    try:
        store = _get_account_store()
        account = store.get_or_create_account(email)
        if account and not account.get("is_active", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account deactivated",
            )
        return account["role"] if account else Role.ANALYST.value
    except HTTPException:
        raise
    except Exception:
        logger.warning("Failed to resolve role for %s, defaulting to analyst", email, exc_info=True)
        return Role.ANALYST.value


def _verify_iap_jwt(token: str, *, is_iap_assertion: bool = False) -> dict[str, str] | None:
    """Verify a Google IAP JWT and return user info, or *None* on failure.

    Uses ``google.oauth2.id_token.verify_token`` which fetches Google's
    public keys and validates signature, audience, issuer and expiry.
    The role is resolved from the ``accounts`` table (not hardcoded).

    Args:
        token: The JWT string to verify.
        is_iap_assertion: When *True*, use the IAP-specific signing-key
            endpoint (``_IAP_CERTS_URL``).  Standard Google ID tokens
            (Bearer path) should leave this *False* so the default OIDC
            certificates are used.
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
        verify_kwargs: dict[str, str] = {}
        if is_iap_assertion:
            verify_kwargs["certs_url"] = _IAP_CERTS_URL
        payload = id_token_mod.verify_token(
            token, g_request, audience=audience, **verify_kwargs
        )
        email = payload.get("email", "unknown")
        role = _resolve_role(email)
        return {"username": email, "role": role}
    except HTTPException:
        raise
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
    """Validate the request and return user info with DB-resolved role.

    Authentication strategy (checked in order):

    1. **Auth disabled** (``settings.identity.disable_auth`` /
       ``I4G_ENV=local``): returns a mock admin user.
    2. **IAP JWT** — ``X-Goog-IAP-JWT-Assertion`` header set by
       Google IAP at the load-balancer level. Verified via Google
       public keys. Role resolved from ``accounts`` table.
    3. **Bearer token** — ``Authorization: Bearer <token>`` sent by
       the UI server or other callers with a Google ID token.
       Role resolved from ``accounts`` table.
    4. **API key** — ``X-API-KEY`` header matching ``settings.api.key``
       (set via ``I4G_API__KEY`` env var). Used for service-to-service
       calls from Cloud Run jobs and CLI.

    For checks 3 and 4 (service credentials), the caller may include
    ``X-I4G-Forwarded-User`` with the real browser user's email.
    This header is set by the Next.js SSR layer after reading the
    incoming IAP assertion from the load balancer.  When present,
    the forwarded email is used as the principal instead of the
    service identity.

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
    # The assertion may arrive directly from IAP (Cloud Run behind LB)
    # or forwarded by the Next.js SSR layer via getIapHeaders().
    iap_jwt = request.headers.get("X-Goog-IAP-JWT-Assertion")
    if iap_jwt:
        user = _verify_iap_jwt(iap_jwt, is_iap_assertion=True)
        if user:
            # If the IAP JWT verified as a service account and the
            # caller forwarded the real user, prefer the forwarded user.
            return _maybe_resolve_forwarded_user(request, user)
        logger.warning("IAP JWT present but verification failed")

    # ── 3. Bearer token (service-to-service via Authorization) ────
    if authorization and authorization.lower().startswith("bearer "):
        bearer_token = authorization.split(" ", 1)[1]
        user = _verify_iap_jwt(bearer_token)
        if user:
            return _maybe_resolve_forwarded_user(request, user)

    # ── 4. API key (env-var-configured, for jobs / CLI) ───────────
    if x_api_key and x_api_key == settings.api.key:
        forwarded = request.headers.get("X-I4G-Forwarded-User")
        if forwarded:
            role = _resolve_role(forwarded)
            return {"username": forwarded, "role": role}
        return {"username": "service", "role": "admin"}

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid credentials",
    )


def _maybe_resolve_forwarded_user(
    request: Request,
    service_user: dict[str, str],
) -> dict[str, str]:
    """Swap the service identity for the forwarded browser user if present.

    The ``X-I4G-Forwarded-User`` header is set by the Next.js SSR layer
    after extracting the email from the incoming IAP assertion.  We trust
    it here because it can only reach the API via an already-authenticated
    service credential (IAP JWT or API key).

    If the header is absent, the *service_user* is returned unchanged.
    """
    forwarded = request.headers.get("X-I4G-Forwarded-User")
    if not forwarded:
        return service_user
    # Only override when the authenticated identity is a service account
    # (not an end-user who is directly hitting the API).
    username = service_user.get("username", "")
    if username and "@" in username and not username.endswith(".iam.gserviceaccount.com"):
        return service_user
    role = _resolve_role(forwarded)
    return {"username": forwarded, "role": role}


def require_role(required_role: str) -> Callable:
    """Dependency factory that enforces a minimum role.

    Uses the role hierarchy so that ``admin`` always satisfies any
    requirement, and ``leo`` satisfies ``analyst`` requirements, etc.

    Args:
        required_role: Minimum role required (e.g. ``"admin"``).

    Returns:
        A FastAPI dependency that validates the user's role.
    """

    def _checker(user: dict[str, str] = Depends(require_token)) -> dict[str, str]:
        user_role = user.get("role", "")
        if has_role(user_role, required_role):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient role: requires {required_role}",
        )

    return _checker


def reset_auth_state() -> None:
    """Reset cached auth state — used in tests to avoid cross-contamination."""
    global _account_store, _iap_verify  # noqa: PLW0603
    _account_store = None
    _iap_verify = None
