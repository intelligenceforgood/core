# API Reference

_Last Updated: 2026-03-19 | Last Verified: March 2026_

The I4G Core API is built with FastAPI. The complete interactive OpenAPI specification is auto-generated and served at runtime.

## Accessing the Documentation

- **Swagger UI:** `http://127.0.0.1:8000/docs` — interactive endpoint testing
- **ReDoc:** `http://127.0.0.1:8000/redoc` — readable reference format
- **OpenAPI JSON:** `http://127.0.0.1:8000/openapi.json`

## Authentication

| Environment            | Mechanism                          | Header                                    |
| ---------------------- | ---------------------------------- | ----------------------------------------- |
| `local`                | Mock identity (no signature check) | `Authorization: Bearer dev-analyst-token` |
| `i4g-dev` / `i4g-prod` | IAP + OIDC service token           | Injected by Next.js proxy                 |

All endpoints require a valid token. Role-based access is enforced per endpoint (roles: `researcher`, `user`, `analyst`, `leo`, `admin`).

---

## Router Summary

| Prefix                | Source File                                                               | Purpose                                                 |
| --------------------- | ------------------------------------------------------------------------- | ------------------------------------------------------- |
| `/reviews`            | `review.py` + `review_search.py` + `review_detail.py` + `review_queue.py` | Core case/review CRUD and hybrid search                 |
| `/accounts`           | `accounts.py`                                                             | User identity and account management                    |
| `/analytics`          | `analytics.py`                                                            | Pre-computed analytics aggregations                     |
| `/cases`              | `cases.py`                                                                | Case management (create, update, query, activity)       |
| `/campaigns`          | `campaigns.py`                                                            | Campaign CRUD (threat actor clusters)                   |
| `/dashboard`          | `dashboard.py`                                                            | Dashboard widget data                                   |
| `/discovery`          | `discovery.py`                                                            | Entity discovery search                                 |
| `/evidence`           | `evidence.py`                                                             | Evidence attachment and retrieval                       |
| `/exports`            | `exports.py`                                                              | CSV/XLSX/STIX entity exports                            |
| `/feedback`           | `feedback.py`                                                             | Analyst feedback submission                             |
| `/impact`             | `impact.py`                                                               | Impact analytics (loss, detection velocity, geography)  |
| `/intakes`            | `intake.py`                                                               | Victim intake submission and processing                 |
| `/intelligence`       | `intelligence.py`                                                         | Entity and indicator intelligence                       |
| `/investigations/ssi` | `ssi_investigations.py` + `ssi_evidence.py` + `ssi_wallets.py`            | SSI investigation results and evidence                  |
| `/investigations`     | `investigations.py`                                                       | Cross-service investigation orchestration (trigger SSI) |
| `/events/ssi`         | `ssi_events.py`                                                           | SSI live event stream (SSE + WebSocket)                 |
| `/playbooks/ssi`      | `ssi_playbooks.py`                                                        | SSI playbook CRUD                                       |
| `/reports`            | `reports.py`                                                              | Report generation and dossier management                |
| `/taxonomy`           | `taxonomy.py`                                                             | Fraud taxonomy tree                                     |
| `/feeds`              | `partner_feed.py`                                                         | Partner indicator feeds                                 |
| `/tasks`              | `app.py`                                                                  | Background task status                                  |

---

## Endpoint Reference

### Reviews / Cases (`/reviews`)

| Method | Path                         | Description                                  |
| ------ | ---------------------------- | -------------------------------------------- |
| POST   | `/reviews/search`            | Hybrid search with filters, sort, pagination |
| GET    | `/reviews/search/history`    | Saved search history                         |
| GET    | `/reviews/search/schema`     | Current saved-search JSON schema             |
| POST   | `/reviews/search/saved`      | Create a saved search                        |
| GET    | `/reviews/search/saved`      | List saved searches                          |
| GET    | `/reviews/search/saved/{id}` | Get saved search                             |
| PUT    | `/reviews/search/saved/{id}` | Update saved search                          |
| DELETE | `/reviews/search/saved/{id}` | Delete saved search                          |
| GET    | `/reviews/{id}`              | Full case detail                             |
| POST   | `/reviews/{id}/feedback`     | Submit analyst classification feedback       |
| GET    | `/reviews/queue`             | Pending review queue                         |

### Accounts (`/accounts`)

| Method | Path                           | Description                  |
| ------ | ------------------------------ | ---------------------------- |
| GET    | `/accounts/me`                 | Current user identity + role |
| GET    | `/accounts`                    | List all accounts (admin)    |
| PUT    | `/accounts/{email}/role`       | Assign role (admin)          |
| PUT    | `/accounts/{email}/deactivate` | Deactivate account (admin)   |
| PUT    | `/accounts/{email}/reactivate` | Reactivate account (admin)   |

### Cases (`/cases`)

| Method | Path                        | Description            |
| ------ | --------------------------- | ---------------------- |
| GET    | `/cases`                    | List active cases      |
| POST   | `/cases`                    | Create a new case      |
| GET    | `/cases/{case_id}`          | Get case details       |
| PATCH  | `/cases/{case_id}`          | Update case fields     |
| GET    | `/cases/{case_id}/activity` | Case activity timeline |

### Intakes (`/intakes`)

| Method | Path                           | Description                                                         |
| ------ | ------------------------------ | ------------------------------------------------------------------- |
| POST   | `/intakes/`                    | Submit a new victim intake (contact fields encrypted via PII vault) |
| GET    | `/intakes/`                    | List recent intakes                                                 |
| GET    | `/intakes/{intake_id}`         | Fetch intake details                                                |
| GET    | `/intakes/{intake_id}/contact` | Fetch decrypted victim contact info (authorized read)               |
| POST   | `/intakes/{intake_id}/status`  | Update intake status                                                |
| POST   | `/intakes/{intake_id}/case`    | Attach case metadata to intake                                      |
| GET    | `/intakes/jobs/{job_id}`       | Fetch intake job status                                             |
| POST   | `/intakes/jobs/{job_id}`       | Update intake job status                                            |

### Intelligence (`/intelligence`)

| Method | Path                                              | Description                                   |
| ------ | ------------------------------------------------- | --------------------------------------------- |
| GET    | `/intelligence/entities`                          | List threat entities with filters and sorting |
| GET    | `/intelligence/entities/{type}/{value}`           | Entity detail with aggregate stats            |
| GET    | `/intelligence/entities/{type}/{value}/activity`  | Activity sparkline                            |
| GET    | `/intelligence/entities/{type}/{value}/neighbors` | 1-hop co-occurrence graph                     |
| GET    | `/intelligence/indicators`                        | List indicators with category filter          |
| GET    | `/intelligence/indicators/{id}`                   | Indicator detail                              |
| GET    | `/intelligence/dashboard`                         | Dashboard widget data                         |
| GET    | `/intelligence/search/facets`                     | Search facet options                          |

### Impact Analytics (`/impact`)

| Method | Path                            | Description                                   |
| ------ | ------------------------------- | --------------------------------------------- |
| GET    | `/impact/dashboard`             | KPI cards and overview metrics                |
| GET    | `/impact/loss-by-taxonomy`      | Loss breakdown by taxonomy axis               |
| GET    | `/impact/detection-velocity`    | Proactive vs reactive detection rate (weekly) |
| GET    | `/impact/pipeline-funnel`       | Intake → case → report conversion funnel      |
| GET    | `/impact/cumulative-indicators` | Cumulative indicator growth over time         |
| GET    | `/impact/taxonomy/sankey`       | Taxonomy co-occurrence Sankey diagram         |
| GET    | `/impact/taxonomy/heatmap`      | Taxonomy axis heatmap                         |
| GET    | `/impact/taxonomy/trend`        | Taxonomy label trend over time                |
| GET    | `/impact/geography`             | Loss and case count by country                |
| GET    | `/impact/geography/{country}`   | Country-level detail                          |

### Campaigns (`/campaigns`)

| Method | Path                       | Description     |
| ------ | -------------------------- | --------------- |
| GET    | `/campaigns`               | List campaigns  |
| GET    | `/campaigns/{campaign_id}` | Campaign detail |
| POST   | `/campaigns`               | Create campaign |
| PATCH  | `/campaigns/{campaign_id}` | Update campaign |

### Reports (`/reports`)

| Method | Path                                              | Description                          |
| ------ | ------------------------------------------------- | ------------------------------------ |
| POST   | `/reports/generate`                               | Trigger report generation for a case |
| GET    | `/reports/library`                                | List generated reports               |
| GET    | `/reports/{report_id}/download`                   | Download report artifact             |
| GET    | `/reports/dossiers`                               | List evidence dossiers               |
| POST   | `/reports/dossiers/{plan_id}/verify`              | Verify dossier integrity             |
| GET    | `/reports/dossiers/{plan_id}/drive_acl`           | Get Drive ACL for dossier            |
| GET    | `/reports/dossiers/{plan_id}/signature_manifest`  | Dossier signature manifest           |
| GET    | `/reports/dossiers/{plan_id}/download/{artifact}` | Download dossier artifact            |
| POST   | `/reports/schedules`                              | Create a scheduled report            |

### SSI Investigations (`/investigations/ssi`)

| Method | Path                                     | Description                                                           |
| ------ | ---------------------------------------- | --------------------------------------------------------------------- |
| POST   | `/investigations/ssi`                    | Trigger an SSI investigation (core orchestrates dedup + SSI dispatch) |
| GET    | `/investigations/ssi/history`            | Investigation history list                                            |
| GET    | `/investigations/ssi/active`             | Currently active investigations                                       |
| GET    | `/investigations/ssi/{scan_id}`          | Investigation detail + result                                         |
| PATCH  | `/investigations/ssi/{scan_id}`          | Update investigation fields                                           |
| GET    | `/investigations/ssi/wallets`            | Wallet entities from SSI investigations                               |
| GET    | `/investigations/ssi/{scan_id}/evidence` | Evidence files for an investigation                                   |
| GET    | `/investigations/ssi/{scan_id}/report`   | Investigation intelligence report                                     |

### SSI Live Events (`/events/ssi`)

| Method    | Path                             | Description                                |
| --------- | -------------------------------- | ------------------------------------------ |
| GET       | `/events/ssi/{scan_id}`          | Poll SSI investigation events (JSON array) |
| POST      | `/events/ssi/{scan_id}`          | Publish investigation event (internal use) |
| GET       | `/events/ssi/{scan_id}/guidance` | Guidance events for an investigation       |
| WebSocket | `/events/ssi/{scan_id}/ws`       | Live WebSocket event stream                |

### SSI Playbooks (`/playbooks/ssi`)

| Method | Path                           | Description                      |
| ------ | ------------------------------ | -------------------------------- |
| GET    | `/playbooks/ssi`               | List playbooks                   |
| GET    | `/playbooks/ssi/{playbook_id}` | Playbook detail                  |
| POST   | `/playbooks/ssi`               | Create playbook                  |
| PUT    | `/playbooks/ssi/{playbook_id}` | Update playbook                  |
| DELETE | `/playbooks/ssi/{playbook_id}` | Delete playbook                  |
| POST   | `/playbooks/ssi/test-match`    | Test if a URL matches a playbook |

### Taxonomy (`/taxonomy`)

| Method | Path        | Description                                      |
| ------ | ----------- | ------------------------------------------------ |
| GET    | `/taxonomy` | Return the full fraud taxonomy tree (all 5 axes) |

### Discovery (`/discovery`)

| Method | Path                | Description             |
| ------ | ------------------- | ----------------------- |
| GET    | `/discovery/search` | Entity discovery search |

### Exports (`/exports`)

| Method | Path                  | Description                                        |
| ------ | --------------------- | -------------------------------------------------- |
| GET    | `/exports/entities`   | Export entities as CSV or XLSX                     |
| GET    | `/exports/indicators` | Export indicators as CSV, XLSX, or STIX 2.1 bundle |

### Feedback (`/feedback`)

| Method | Path        | Description             |
| ------ | ----------- | ----------------------- |
| POST   | `/feedback` | Submit analyst feedback |

### Partner Feeds (`/feeds`)

| Method | Path                | Description                            |
| ------ | ------------------- | -------------------------------------- |
| GET    | `/feeds/indicators` | Retrieve indicators from partner feeds |

### Background Tasks (`/tasks`)

| Method | Path               | Description                                                |
| ------ | ------------------ | ---------------------------------------------------------- |
| GET    | `/tasks/{task_id}` | Poll background task status (report generation, ingestion) |

---

## Generating Client SDKs

The `ui/packages/sdk` package contains a TypeScript client generated from the OpenAPI schema. To regenerate:

```bash
cd ui
pnpm run schema:sync
```

Run `pnpm run schema:check` in CI or pre-commit to verify the snapshot is current.
