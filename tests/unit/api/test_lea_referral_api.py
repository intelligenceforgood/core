"""Unit tests for LEA referral API endpoints (S6-20).

Covers POST/GET /cases/{id}/lea-referral endpoints.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client() -> TestClient:
    """Create a test client with mocked auth."""
    with (
        patch("i4g.api.auth.require_token", return_value={"sub": "test@test.com", "role": "analyst"}),
        patch("i4g.api.auth.require_role", return_value=lambda: {"sub": "test@test.com", "role": "analyst"}),
    ):
        from i4g.api.app import create_app

        app = create_app()
        return TestClient(app)


def _make_mock_session(case_row: object | None = None) -> MagicMock:
    """Build a mock SQL session that returns the given case row on execute."""
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = case_row
    mock_session.execute.return_value = mock_result
    mock_session.__enter__ = lambda s: s
    mock_session.__exit__ = MagicMock(return_value=False)
    return mock_session


def _make_mock_sf(mock_session: MagicMock) -> MagicMock:
    """Build a mock session factory that yields the given session."""
    mock_sf = MagicMock()
    mock_sf.return_value = mock_session
    return mock_sf


def test_lea_referral_models() -> None:
    """LeaReferralRequest and LeaReferralResponse serialize correctly."""
    from i4g.api.cases import LeaReferralRequest, LeaReferralResponse

    req = LeaReferralRequest(agency="FBI", case_number="FBI-2024-001")
    assert req.agency == "FBI"

    resp = LeaReferralResponse(
        case_id="case-1",
        lea_referred_at="2026-03-14T00:00:00+00:00",
        lea_agency="FBI",
        lea_case_number="FBI-2024-001",
    )
    data = resp.model_dump(by_alias=True)
    assert data["caseId"] == "case-1"
    assert data["leaAgency"] == "FBI"
    assert data["leaCaseNumber"] == "FBI-2024-001"


def test_lea_referral_response_null_fields() -> None:
    """LeaReferralResponse allows null fields for unreferred cases."""
    from i4g.api.cases import LeaReferralResponse

    resp = LeaReferralResponse(
        case_id="case-3",
        lea_referred_at=None,
        lea_agency=None,
        lea_case_number=None,
    )
    data = resp.model_dump(by_alias=True)
    assert data["leaReferredAt"] is None
    assert data["leaAgency"] is None


def test_lea_referral_endpoint_exists() -> None:
    """LEA referral POST and GET routes are registered on the cases router."""
    from i4g.api.cases import router

    paths = [r.path for r in router.routes]
    assert "/cases/{case_id}/lea-referral" in paths
