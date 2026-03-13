"""Tests for the exports API endpoints.

Covers CSV/XLSX entity exports, CSV/XLSX/STIX indicator exports,
indicator masking, unmask role check, and audit logging.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from i4g.api.app import create_app

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_SAMPLE_ENTITIES = [
    {"entity_type": "crypto_wallet", "canonical_value": "0xABC", "case_count": 3, "loss_sum": 50000},
    {"entity_type": "bank_account", "canonical_value": "1234", "case_count": 1, "loss_sum": 10000},
]

_SAMPLE_INDICATORS = [
    {
        "indicator_id": "ind-1",
        "number": "9876543210",
        "item": "Acct-A",
        "type": "financial",
        "category": "bank",
        "case_count": 5,
        "loss_sum": 80000,
        "first_seen_at": "2025-01-01",
    },
    {
        "indicator_id": "ind-2",
        "number": "BTC:abc123",
        "item": "WalletB",
        "type": "crypto",
        "category": "crypto",
        "case_count": 2,
        "loss_sum": 20000,
        "first_seen_at": "2025-02-01",
    },
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_store() -> MagicMock:
    """Create a mock AnalyticsStore for exports."""
    store = MagicMock()
    store.list_entity_stats.return_value = [dict(e) for e in _SAMPLE_ENTITIES]
    store.list_indicator_stats.return_value = [dict(i) for i in _SAMPLE_INDICATORS]
    return store


@pytest.fixture()
def client(mock_store: MagicMock) -> TestClient:
    """Create a TestClient with the analytics store mocked."""
    from i4g.api.exports import _get_analytics_store

    app = create_app()
    app.dependency_overrides[_get_analytics_store] = lambda: mock_store
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Entity CSV export
# ---------------------------------------------------------------------------


def test_export_entities_csv(client: TestClient) -> None:
    """CSV entity export returns valid CSV with headers."""
    resp = client.get("/exports/entities", params={"fmt": "csv"})
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    text = resp.text
    assert "entity_type" in text
    assert "crypto_wallet" in text


def test_export_entities_csv_empty(client: TestClient, mock_store: MagicMock) -> None:
    """Empty result set produces 'No data' CSV response."""
    mock_store.list_entity_stats.return_value = []
    resp = client.get("/exports/entities", params={"fmt": "csv"})
    assert resp.status_code == 200
    assert "No data" in resp.text


# ---------------------------------------------------------------------------
# Entity XLSX export
# ---------------------------------------------------------------------------


def test_export_entities_xlsx(client: TestClient) -> None:
    """XLSX entity export returns a binary spreadsheet (or CSV fallback)."""
    resp = client.get("/exports/entities", params={"fmt": "xlsx"})
    assert resp.status_code == 200
    # Either real xlsx or csv fallback if openpyxl missing
    ct = resp.headers["content-type"]
    assert "spreadsheetml" in ct or "text/csv" in ct


# ---------------------------------------------------------------------------
# Indicator CSV export
# ---------------------------------------------------------------------------


def test_export_indicators_csv(client: TestClient) -> None:
    """CSV indicator export returns valid CSV."""
    resp = client.get("/exports/indicators", params={"fmt": "csv"})
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# Indicator masking
# ---------------------------------------------------------------------------


def test_indicator_masking_bank(client: TestClient) -> None:
    """Bank indicator values are masked to last 4 digits by default."""
    resp = client.get("/exports/indicators", params={"fmt": "csv"})
    text = resp.text
    # "9876543210" should become "****3210"
    assert "****3210" in text
    # Crypto values are not masked
    assert "BTC:abc123" in text


def test_indicator_unmask_analyst(client: TestClient) -> None:
    """Analyst+ can unmask indicator values."""
    # Default local-dev user is admin — should pass unmask check
    resp = client.get("/exports/indicators", params={"fmt": "csv", "unmask": "true"})
    text = resp.text
    assert "9876543210" in text


# ---------------------------------------------------------------------------
# STIX export
# ---------------------------------------------------------------------------


def test_export_stix_bundle(client: TestClient) -> None:
    """STIX export produces a valid STIX 2.1 bundle."""
    resp = client.get("/exports/indicators", params={"fmt": "stix"})
    assert resp.status_code == 200
    bundle = resp.json()
    assert bundle["type"] == "bundle"
    assert len(bundle["objects"]) == 2
    ind = bundle["objects"][0]
    assert ind["type"] == "indicator"
    assert ind["spec_version"] == "2.1"
    assert ind["pattern_type"] == "stix"
    # Bank indicator should have financial-account pattern
    assert "financial-account" in ind["pattern"]


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------


def test_export_audit_log(client: TestClient) -> None:
    """Export endpoints log an audit message."""
    with patch("i4g.api.exports.logger") as mock_logger:
        client.get("/exports/entities", params={"fmt": "csv"})
        mock_logger.info.assert_called()
        log_msg = mock_logger.info.call_args[0][0]
        assert "EXPORT_AUDIT" in log_msg


# ---------------------------------------------------------------------------
# Entity export filter passthrough
# ---------------------------------------------------------------------------


def test_export_entities_type_filter(client: TestClient, mock_store: MagicMock) -> None:
    """Entity type filter is forwarded to the store."""
    client.get("/exports/entities", params={"fmt": "csv", "entity_type": "bank_account"})
    call_kwargs = mock_store.list_entity_stats.call_args.kwargs
    assert call_kwargs["entity_type"] == "bank_account"
