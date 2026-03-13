# API Reference

The Intelligence for Good (i4g) API is built with FastAPI, which automatically generates interactive API documentation using OpenAPI (Swagger UI) and ReDoc.

## Accessing the Documentation

When the API is running locally (or in a deployed environment), you can access the documentation at the following endpoints:

- **Swagger UI:** `http://127.0.0.1:8000/docs`
  - Interactive documentation that allows you to test API endpoints directly from the browser.
- **ReDoc:** `http://127.0.0.1:8000/redoc`
  - Alternative documentation viewer, often better for reading complex schemas.

## Authentication

Most endpoints require authentication. In the `local` environment (default), the system uses a mock identity provider.

- **API Key:** Use the default development key: `dev-analyst-token`
- **Header:** `Authorization: Bearer dev-analyst-token`

## Key Endpoints

- `/reviews/search`: Hybrid search across cases.
- `/reviews/{id}`: Retrieve full case details.
- `/tasks`: Manage background tasks (report generation, ingestion).
- `/reports`: Generate and retrieve case reports.

### Intelligence (Sprint 2)

- `GET /intelligence/entities`: List threat entities with filters and sorting.
- `GET /intelligence/entities/{type}/{value}`: Entity detail with aggregate stats.
- `GET /intelligence/entities/{type}/{value}/activity`: Activity sparkline.
- `GET /intelligence/entities/{type}/{value}/neighbors`: 1-hop co-occurrence graph.
- `GET /intelligence/indicators`: List indicators with category filter.
- `GET /intelligence/indicators/{id}`: Indicator detail.
- `GET /intelligence/dashboard`: Dashboard widget data (entities, indicators, campaigns, KPIs).
- `GET /intelligence/search/facets`: Search facet options.

### Exports (Sprint 2)

- `GET /exports/entities`: Export entities as CSV or XLSX.
- `GET /exports/indicators`: Export indicators as CSV, XLSX, or STIX 2.1 bundle.

## Generating Client SDKs

The `ui/packages/sdk` package contains a TypeScript client generated from the OpenAPI schema. To regenerate it:

```bash
cd ui
pnpm run generate:api
```
