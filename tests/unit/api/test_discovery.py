"""Unit tests for Discovery API endpoints."""

import base64
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from i4g.api.app import app
from i4g.services.discovery import DiscoverySearchParams

client = TestClient(app)


@pytest.fixture
def mock_settings():
    with patch("i4g.api.discovery.SETTINGS") as mock:
        mock.is_local = True
        yield mock


@patch("i4g.api.discovery.run_discovery_search")
@patch("i4g.api.discovery.get_default_discovery_params")
def test_discovery_search_pagination_wiring(mock_get_params, mock_run_search, mock_settings):
    """Verify API parameters are correctly wired to the service."""
    mock_settings.is_local = False
    
    # Mock successful params creation
    mock_params = MagicMock(spec=DiscoverySearchParams)
    mock_get_params.return_value = mock_params
    
    # Mock successful search
    mock_run_search.return_value = {"results": [], "total_size": 0}

    # Create a page token that decodes to offset 20
    page_token = base64.urlsafe_b64encode(b"20").decode()

    response = client.get(
        "/discovery/search",
        params={
            "query": "test",
            "page_size": 15,
            "page_token": page_token,
            "offset": 0  # Should be overridden by token
        }
    )

    assert response.status_code == 200
    
    # Verify get_default_discovery_params called with decoded offset
    mock_get_params.assert_called_once()
    call_kwargs = mock_get_params.call_args.kwargs
    assert call_kwargs["page_size"] == 15
    assert call_kwargs["page_token"] == page_token
    assert call_kwargs["offset"] == 20


@patch("i4g.api.discovery._local_discovery_search")
@patch("i4g.api.discovery.run_discovery_search")
@patch("i4g.api.discovery.get_default_discovery_params")
def test_discovery_search_fallback_on_config_error(mock_get_params, mock_run_search, mock_local_search, mock_settings):
    """Verify fallback to local search when config is missing in local mode."""
    mock_settings.is_local = True
    mock_get_params.side_effect = RuntimeError("Config missing")
    
    mock_local_search.return_value = {"results": ["local"], "total_size": 1}

    response = client.get("/discovery/search", params={"query": "test"})

    assert response.status_code == 200
    assert response.json() == {"results": ["local"], "total_size": 1}
    mock_local_search.assert_called_once()


@patch("i4g.api.discovery._local_discovery_search")
@patch("i4g.api.discovery.run_discovery_search")
@patch("i4g.api.discovery.get_default_discovery_params")
def test_discovery_search_fallback_on_runtime_error(mock_get_params, mock_run_search, mock_local_search, mock_settings):
    """Verify fallback to local search when runtime search fails in local mode."""
    mock_settings.is_local = True
    mock_get_params.return_value = MagicMock()
    mock_run_search.side_effect = RuntimeError("Search failed")
    
    mock_local_search.return_value = {"results": ["local"], "total_size": 1}

    response = client.get("/discovery/search", params={"query": "test"})

    assert response.status_code == 200
    assert response.json() == {"results": ["local"], "total_size": 1}
    mock_local_search.assert_called_once()


@patch("i4g.api.discovery.HybridSearchService")
def test_local_discovery_search_snippet_mapping(mock_service_cls):
    """Verify snippet extraction from various fields in local search."""
    from i4g.api.discovery import _local_discovery_search
    
    mock_service = mock_service_cls.return_value
    mock_service.search.return_value = {
        "results": [
            {
                "case_id": "1",
                "metadata": {"summary": "Metadata Summary"},
                "merged_score": 0.9
            },
            {
                "case_id": "2",
                "metadata": {},
                "vector": {"text": "Vector Text"},
                "merged_score": 0.8
            },
            {
                "case_id": "3",
                "metadata": {},
                "record": {"text": "Record Text"},
                "merged_score": 0.7
            }
        ],
        "total": 3
    }

    result = _local_discovery_search("test", 10)
    
    results = result["results"]
    assert len(results) == 3
    assert results[0]["struct"]["summary"] == "Metadata Summary"
    assert results[1]["struct"]["summary"] == "Vector Text"
    assert results[2]["struct"]["summary"] == "Record Text"
