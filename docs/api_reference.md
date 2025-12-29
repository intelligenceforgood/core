# API Reference

The Intelligence for Good (i4g) API is built with FastAPI, which automatically generates interactive API documentation using OpenAPI (Swagger UI) and ReDoc.

## Accessing the Documentation

When the API is running locally (or in a deployed environment), you can access the documentation at the following endpoints:

*   **Swagger UI:** `http://127.0.0.1:8000/docs`
    *   Interactive documentation that allows you to test API endpoints directly from the browser.
*   **ReDoc:** `http://127.0.0.1:8000/redoc`
    *   Alternative documentation viewer, often better for reading complex schemas.

## Authentication

Most endpoints require authentication. In the `local` environment (default), the system uses a mock identity provider.

*   **API Key:** Use the default development key: `dev-analyst-token`
*   **Header:** `Authorization: Bearer dev-analyst-token`

## Key Endpoints

*   `/reviews/search`: Hybrid search across cases.
*   `/reviews/{id}`: Retrieve full case details.
*   `/tasks`: Manage background tasks (report generation, ingestion).
*   `/reports`: Generate and retrieve case reports.

## Generating Client SDKs

The `ui/packages/sdk` package contains a TypeScript client generated from the OpenAPI schema. To regenerate it:

```bash
cd ui
pnpm run generate:api
```
