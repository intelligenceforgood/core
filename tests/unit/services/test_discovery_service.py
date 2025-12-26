"""Unit tests for Discovery service helpers."""

import json
from unittest.mock import MagicMock, patch

import pytest
from google.cloud import discoveryengine_v1beta as discoveryengine

from i4g.services.discovery import (
    DiscoverySearchParams,
    get_default_discovery_params,
    run_discovery_search,
)


@pytest.fixture
def mock_settings():
    with patch("i4g.services.discovery.get_settings") as mock:
        mock.return_value.vector.vertex_ai_project = "test-project"
        mock.return_value.vector.vertex_ai_location = "global"
        yield mock


@pytest.fixture
def mock_env():
    with patch.dict(
        "os.environ",
        {
            "I4G_VERTEX_SEARCH_PROJECT": "env-project",
            "I4G_VERTEX_SEARCH_DATA_STORE": "env-store",
        },
    ):
        yield


def test_get_default_discovery_params_uses_env(mock_env, mock_settings):
    """Verify environment variables override settings."""
    params = get_default_discovery_params("test query")
    assert params.project == "env-project"
    assert params.data_store_id == "env-store"
    assert params.query == "test query"


def test_get_default_discovery_params_missing_config(mock_settings):
    """Verify error when config is missing."""
    with patch.dict("os.environ", {}, clear=True):
        mock_settings.return_value.vector.vertex_ai_project = None
        with pytest.raises(RuntimeError, match="Discovery defaults are missing"):
            get_default_discovery_params("test")


@patch("i4g.services.discovery._search_client")
def test_run_discovery_search_pagination(mock_client_factory):
    """Verify pagination parameters are passed to the client."""
    mock_client = MagicMock()
    mock_client.serving_config_path.return_value = "projects/p/locations/l/dataStores/d/servingConfigs/default_search"
    mock_client_factory.return_value = mock_client

    # Mock response
    mock_response = MagicMock()
    mock_response.total_size = 100
    mock_response.next_page_token = "next-token"
    mock_response.__iter__.return_value = []
    mock_client.search.return_value = mock_response

    params = DiscoverySearchParams(
        query="test", project="p", location="l", data_store_id="d", page_size=20, page_token="curr-token", offset=50
    )

    run_discovery_search(params)

    # Verify call args
    call_args = mock_client.search.call_args
    request = call_args.kwargs["request"]

    assert request.page_size == 20
    assert request.page_token == "curr-token"
    assert request.offset == 50
    assert request.query == "test"


@patch("i4g.services.discovery._search_client")
def test_run_discovery_search_results_mapping(mock_client_factory):
    """Verify results are mapped correctly."""
    mock_client = MagicMock()
    mock_client.serving_config_path.return_value = "projects/p/locations/l/dataStores/d/servingConfigs/default_search"
    mock_client_factory.return_value = mock_client

    # Create a mock result
    mock_result = MagicMock()
    mock_result.document.id = "doc-1"
    mock_result.document.name = "Document 1"
    mock_result.document.json_data = json.dumps(
        {"summary": "Test Summary", "title": "Test Title", "source": "Test Source"}
    )
    # Mock protobuf conversion
    mock_result._pb = MagicMock()

    mock_response = MagicMock()
    mock_response.__iter__.return_value = [mock_result]
    mock_client.search.return_value = mock_response

    params = DiscoverySearchParams(query="test", project="p", location="l", data_store_id="d")

    result = run_discovery_search(params)

    assert len(result["results"]) == 1
    item = result["results"][0]
    assert item["document_id"] == "doc-1"
    assert item["summary"] == "Test Summary"
    assert item["source"] == "Test Source"
