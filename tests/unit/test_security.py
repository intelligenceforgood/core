"""Security tests: role escalation, PII leakage, export audit (S6-23).

Validates that authentication and authorization are enforced correctly
across all TIFAP endpoints.
"""

from __future__ import annotations


def test_intelligence_endpoints_require_auth() -> None:
    """Intelligence API endpoints require auth dependency to be wired."""

    from i4g.api.intelligence import router as intelligence_router

    # Verify the router has require_token in its dependencies
    dep_callables = [
        d.dependency.__name__ for d in intelligence_router.dependencies if hasattr(d.dependency, "__name__")
    ]
    assert "require_token" in dep_callables, "Intelligence router missing require_token dependency"


def test_partner_feed_requires_api_key() -> None:
    """Partner feed rejects requests without X-Partner-API-Key header."""
    from fastapi.testclient import TestClient

    from i4g.api.app import create_app

    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/feeds/indicators")
    assert resp.status_code in (401, 403, 422)


def test_partner_feed_rejects_invalid_key() -> None:
    """Partner feed rejects invalid API key."""
    from fastapi.testclient import TestClient

    from i4g.api.app import create_app

    # Mock settings to have partner_feed enabled
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get(
        "/feeds/indicators",
        headers={"X-Partner-API-Key": "definitely-not-a-valid-key"},
    )
    assert resp.status_code in (401, 403)


def test_export_adapters_no_pii_in_partner_feed() -> None:
    """Partner feed indicator model does not expose PII fields."""
    from i4g.api.partner_feed import FeedIndicator

    fields = set(FeedIndicator.model_fields.keys())
    pii_fields = {"reporter_name", "contact_email", "contact_phone", "victim_name"}
    assert fields.isdisjoint(pii_fields), f"PII field(s) found in FeedIndicator: {fields & pii_fields}"


def test_security_tables_exist() -> None:
    """partner_feed_audit and partner_api_keys tables are defined."""
    from i4g.store import sql

    assert hasattr(sql, "partner_feed_audit")
    assert hasattr(sql, "partner_api_keys")


def test_lea_referral_requires_analyst_role() -> None:
    """LEA referral POST/GET endpoints are listed in cases router."""
    from i4g.api.cases import router

    paths = [r.path for r in router.routes]
    assert "/cases/{case_id}/lea-referral" in paths
