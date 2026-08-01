"""Unit tests for OpenAPI schema filtering and internal documentation endpoints."""

from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from i4g.api.app import create_app
from i4g.api.auth import require_token
from i4g.api.scopes import INTERNAL_ONLY_TAGS, PARTNER_ALLOWED_TAGS


@pytest.fixture
def app_client() -> TestClient:
    """Create a TestClient with authentication bypassed (auth_source: local)."""
    app = create_app()

    def mock_require_token() -> dict[str, Any]:
        return {"sub": "test-admin", "role": "admin", "auth_source": "local"}

    app.dependency_overrides[require_token] = mock_require_token
    return TestClient(app)


def test_openapi_schema_filtering(app_client: TestClient) -> None:
    """Test that default GET /openapi.json excludes internal-only endpoints and tags."""
    response = app_client.get("/openapi.json")
    assert response.status_code == status.HTTP_200_OK

    schema = response.json()
    paths = schema.get("paths", {})

    # Verify no paths with ONLY internal tags remain
    for path_str, path_item in paths.items():
        for method, operation in path_item.items():
            if method.lower() in {"get", "post", "put", "delete", "patch"}:
                tags = set(operation.get("tags", []))
                if tags:
                    assert not tags.issubset(
                        INTERNAL_ONLY_TAGS
                    ), f"Path {path_str} {method} has internal-only tags: {tags}"

    # Verify internal tag definitions are removed from schema tags list
    schema_tag_names = {t["name"] for t in schema.get("tags", [])}
    for internal_tag in INTERNAL_ONLY_TAGS:
        assert internal_tag not in schema_tag_names, f"Internal tag {internal_tag} found in openapi.json tags"

    # Verify partner paths are included (e.g. /reviews/search or /partner-feed)
    has_partner_path = False
    for _path_str, path_item in paths.items():
        for method, operation in path_item.items():
            if method.lower() in {"get", "post", "put", "delete", "patch"}:
                tags = set(operation.get("tags", []))
                if tags & PARTNER_ALLOWED_TAGS:
                    has_partner_path = True
                    break

    assert has_partner_path, "Filtered OpenAPI schema contains no partner-allowed paths"


def test_openapi_internal_schema_and_docs(app_client: TestClient) -> None:
    """Test GET /openapi-internal.json and GET /docs/internal return full spec & Swagger UI when authorized."""
    # Test internal openapi json
    resp_schema = app_client.get("/openapi-internal.json")
    assert resp_schema.status_code == status.HTTP_200_OK

    full_schema = resp_schema.json()
    paths = full_schema.get("paths", {})

    # Full schema must contain internal endpoints (e.g. /accounts or /tasks/{task_id})
    internal_found = False
    for _path_str, path_item in paths.items():
        for method, operation in path_item.items():
            if method.lower() in {"get", "post", "put", "delete", "patch"}:
                tags = set(operation.get("tags", []))
                if tags & INTERNAL_ONLY_TAGS:
                    internal_found = True
                    break
    assert internal_found, "Internal OpenAPI schema missing internal-tagged endpoints"

    # Test internal docs UI HTML
    resp_docs = app_client.get("/docs/internal")
    assert resp_docs.status_code == status.HTTP_200_OK
    assert "text/html" in resp_docs.headers.get("content-type", "")
    assert "/openapi-internal.json" in resp_docs.text


def test_openapi_internal_forbidden_for_partner_api_key() -> None:
    """Test GET /openapi-internal.json and GET /docs/internal return 403 for DB API keys without admin:internal."""
    app = create_app()

    def mock_db_api_key_user() -> dict[str, Any]:
        return {
            "sub": "partner-key-123",
            "role": "partner",
            "auth_source": "db_api_key",
            "scopes": ["read:partner"],
        }

    app.dependency_overrides[require_token] = mock_db_api_key_user
    client = TestClient(app)

    resp_json = client.get("/openapi-internal.json")
    assert resp_json.status_code == status.HTTP_403_FORBIDDEN

    resp_docs = client.get("/docs/internal")
    assert resp_docs.status_code == status.HTTP_403_FORBIDDEN
