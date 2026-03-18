# Architecture Cheat Sheet

Dense reference for the i4g multi-root workspace. Absorb before every coding session to avoid wrong assumptions about routing, auth, data flow, and storage.

---

## 1. Request Routing (UI → Core → SSI)

### Three-layer proxy chain

```
Browser (port 3000)
  ↓  href="/api/..."  or  SDK fetch("/api/...")
Next.js (App Router, port 3000)
  ↓  server-side fetch to I4G_API_URL (default http://127.0.0.1:8000)
Core FastAPI (port 8000)
  ↓  (for SSI) HTTP POST to SSI Cloud Run Service
SSI FastAPI (port 8100 locally; deployed as Cloud Run Service `ssi-svc` in cloud)
```

### Next.js API routes — two patterns

| Pattern              | Location                                                               | Purpose                                                                                                                             |
| -------------------- | ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| **Dedicated routes** | `ui/apps/web/src/app/api/ssi/*`, `api/search/*`, `api/reviews/*`, etc. | Custom proxy logic (request normalization, response shaping, error handling). Always preferred when they exist.                     |
| **Catch-all proxy**  | `ui/apps/web/src/app/api/[...path]/route.ts`                           | Generic pass-through to core API. Forwards any `GET/POST/PUT/DELETE/PATCH` to `{I4G_API_URL}/{path}`. No special response handling. |

### Critical URL rule for browser-facing links

**Core API returns API-relative paths** (e.g., `/cases/{id}/evidence/{doc_id}`).
**Browser links MUST be prefixed with `/api`** so they route through the Next.js proxy.
Never generate absolute `http://localhost:8000/...` URLs in API responses — the browser cannot reach the core API directly in cloud.

```
Core returns:  url="/cases/{id}/evidence/{doc_id}"
UI renders:    href="/api/cases/{id}/evidence/{doc_id}"
                     ^^^^  ← prefix added by UI
Browser hits:  localhost:3000/api/cases/{id}/evidence/{doc_id}
Proxy routes:  → localhost:8000/cases/{id}/evidence/{doc_id}
```

### SDK client URL resolution

| Context                    | baseUrl                                                   | Mechanism                                       |
| -------------------------- | --------------------------------------------------------- | ----------------------------------------------- |
| Server component (SSR)     | `process.env.I4G_API_URL` (e.g., `http://127.0.0.1:8000`) | Direct to core — no proxy needed                |
| Client component (browser) | `"/api"`                                                  | Relative — goes through Next.js catch-all proxy |

Source: `ui/apps/web/src/lib/i4g-client.ts` → `resolveClient()`.

### SSI-specific Next.js API routes

| Browser path                   | Next.js route file                     | Proxies to (core API)                                      | Notes                                               |
| ------------------------------ | -------------------------------------- | ---------------------------------------------------------- | --------------------------------------------------- |
| `/api/ssi/investigate`         | `api/ssi/investigate/route.ts`         | Core `POST /investigations/ssi`                            | Core orchestrates; triggers SSI service              |
| `/api/ssi/investigate/{id}`    | `api/ssi/investigate/[id]/route.ts`    | Core `GET /tasks/{id}`                                     | Core is single source of truth for task status       |
| `/api/ssi/report/{id}`         | `api/ssi/report/[id]/route.ts`         | Core `GET /investigations/ssi/{id}/report.pdf`                         | Handles GCS 307 redirects, sets Content-Disposition |
| `/api/ssi/investigations`      | `api/ssi/investigations/route.ts`      | Core `GET /investigations/ssi/history`                                 | Passes query params                                 |
| `/api/ssi/investigations/{id}` | `api/ssi/investigations/[id]/route.ts` | Core `GET /investigations/ssi/{id}`                                    | Direct proxy                                        |
| `/api/ssi/wallets`             | `api/ssi/wallets/route.ts`             | Core `GET /investigations/ssi/wallets`                                 | Direct proxy                                        |

### eCX proxy routes (direct to SSI — require `SSI_API_URL`)

The eCX proxy routes forward **directly to ssi-svc** (not through core). They use `resolveSsiUrl()` from `ui/apps/web/src/lib/server/ssi-proxy.ts`, which reads `SSI_API_URL`. In cloud, this env var is injected via Terraform (`module.run_ssi_service[0].uri`). Auth is handled by `ssiHeaders()` (OIDC identity token with ssi-svc URL as audience).

| Browser path                          | Next.js route file                                    | Proxies to (SSI)                       |
| ------------------------------------- | ----------------------------------------------------- | -------------------------------------- |
| `/api/ssi/ecx/feed`                   | `api/ssi/ecx/feed/route.ts`                           | SSI `GET /ecx/feed`                    |
| `/api/ssi/ecx/polling-status`         | `api/ssi/ecx/polling-status/route.ts`                 | SSI `GET /ecx/polling-status`          |
| `/api/ssi/ecx/submissions`            | `api/ssi/ecx/submissions/route.ts`                    | SSI `GET /ecx/submissions`             |
| `/api/ssi/ecx/submissions/{id}/approve` | `api/ssi/ecx/submissions/[id]/approve/route.ts`     | SSI `POST /ecx/submissions/{id}/approve` |
| `/api/ssi/ecx/submissions/{id}/reject`  | `api/ssi/ecx/submissions/[id]/reject/route.ts`      | SSI `POST /ecx/submissions/{id}/reject`  |
| `/api/ssi/ecx/submissions/{id}/retract` | `api/ssi/ecx/submissions/[id]/retract/route.ts`     | SSI `POST /ecx/submissions/{id}/retract` |
| `/api/ssi/ecx/investigate/{id}`       | `api/ssi/ecx/investigate/[id]/route.ts`               | SSI `POST /ecx/investigate/{id}`       |
| `/api/ssi/ecx/stats/*`                | `api/ssi/ecx/stats/*/route.ts`                        | SSI `GET /ecx/stats/*`                 |

### Core API router mounts (prefix map)

| Prefix                 | Router file             | Key endpoints                                                             |
| ---------------------- | ----------------------- | ------------------------------------------------------------------------- |
| `/cases`               | `cases.py`              | CRUD, timeline, detail                                                    |
| `/cases/{id}/evidence` | `evidence.py`           | Upload, list, download evidence files                                     |
| `/investigations/ssi`  | `ssi_investigations.py` | `/history`, `/active`, `/{scan_id}`                                       |
| `/investigations/ssi`  | `ssi_evidence.py`       | `/{scan_id}/report.pdf`, `/evidence-bundle`, `/lea-package`               |
| `/investigations/ssi`  | `ssi_wallets.py`        | `/wallets`, `/{scan_id}/wallets.csv`, `/{scan_id}/wallets.xlsx`           |
| `/investigations/ssi`  | `ssi_playbooks.py`      | Playbook CRUD (prefix: `/playbooks/ssi`)                                  |
| `/investigations`      | `investigations.py`     | `POST /investigations/ssi` (trigger), `GET /investigations/ssi/{task_id}` |
| `/reviews`             | `review.py`             | Search, history, saved searches, case actions                             |
| `/tasks`               | `tasks.py`              | `GET /tasks/{task_id}` — poll background task status                      |
| `/taxonomy`            | `taxonomy.py`           | Fraud taxonomy CRUD                                                       |

**Registration order matters** — SSI wallets/evidence routers are registered before `ssi_investigations` to prevent the `/{scan_id}` catch-all from swallowing `/wallets`, etc.

---

## 2. Auth Model

### Local environment (`I4G_ENV=local`)

**All auth is bypassed.** `require_token()` returns `{"username": "local-dev", "role": "admin"}` without checking any header. No API key, no JWT, no IAP. Do NOT debug 404s or 500s as auth issues in local env.

### Cloud environment (`I4G_ENV=dev` or `prod`)

- **IAP (Identity-Aware Proxy)**: Fronts Cloud Run services. Browser → IAP → Cloud Run.
- **API Key**: `X-API-KEY` header validated by `require_token()`.
- **JWT**: Google Identity Platform OIDC tokens validated by `require_token()`.
- **Next.js**: Server-side API routes inject IAP headers via `getIapHeaders()` before proxying to core.

### Key rule

**Never assume auth is the cause of errors in local dev.** If a request returns 404 or 500 locally, the issue is routing, missing data, or code bugs — not authentication.

---

## 3. Storage & Evidence

### Storage backends by environment

| Category      | Local                        | Cloud                |
| ------------- | ---------------------------- | -------------------- |
| Relational    | SQLite (`data/i4g_store.db`) | Cloud SQL PostgreSQL |
| Vector        | Chroma (`data/chroma_store`) | Vertex AI Search     |
| Blob/evidence | Local FS (`data/evidence/`)  | GCS buckets          |
| SSI scans     | Same shared DB (`i4g_store.db`) | Same Cloud SQL instance |

### Evidence file flow

```
SSI orchestrator → writes to data/evidence/{case_id}/
  ├── report.pdf, investigation.json, screenshots, etc.
  └── Updates site_scans.evidence_path = local path or gs:// URI

Core evidence endpoints:
  GET /investigations/ssi/{scan_id}/report.pdf
    → Local: serves from evidence_path/report.pdf
    → Cloud: 307 redirect to GCS signed URL

  GET /cases/{case_id}/evidence/{doc_id}
    → Serves from EvidenceStorage (abstracts FS vs GCS)
    → Requires source_documents row with matching doc_id
```

### SSI evidence storage layout

```
data/evidence/{case_id}/
  ├── investigation.json, report.md, report.pdf
  ├── stix_bundle.json, wallet_manifest.json, evidence.zip
  ├── passive/ (screenshot.png, dom.html, network.har, whois.json, etc.)
  └── active/  (session_log.json, screenshots/, wallets/)
```

---

## 4. SSI ↔ Core Integration

### Direct Database Writes (`ssi/src/ssi/store/scan_store.py`)

SSI writes investigation results directly to the shared database via `ScanStore.create_case_record()`:

```
create_case_record(scan_id, result, dataset)
  ├── INSERT cases            (case record + dedup via content hash)
  ├── INSERT scam_records     (dashboard join)
  ├── INSERT review_queue     (analyst queue entry)
  ├── _insert_timeline_events()   (review_actions rows)
  ├── _insert_evidence_documents() (source_documents rows)
  └── UPDATE site_scans       (link scan → case)
```

### Case metadata from SSI

When `ScanStore` creates a case, it stores `ssi_investigation_id` in case metadata:

```python
"metadata": {
    "ssi_investigation_id": str(scan_id),
    "scan_type": result.scan_type,
    ...
}
```

This ID links the case back to SSI's `site_scans` table and is used to construct evidence download URLs.

### SSI investigation routing (unified — all environments)

Investigation lifecycle routes **always** go through Core, regardless of environment.
Core is the orchestrator: it creates task records, performs dedup, triggers SSI, and tracks status.
This ensures manual (UI) and automated (case-intake) triggers share one code path.

| Operation               | Flow                                                                                                             | Notes                                                                     |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Investigation trigger   | UI → Next.js `/api/ssi/investigate` → Core `POST /investigations/ssi` → SSI Service `POST /trigger/investigate`  | Core creates task, runs dedup, dispatches to SSI                          |
| Status polling          | UI → Next.js `/api/ssi/investigate/{id}` → Core `GET /tasks/{id}`                                                | SSI pushes updates via `TaskStatusReporter`; Core is single status source |
| Evidence download       | UI → Next.js `/api/ssi/report/{id}` → Core `GET /investigations/ssi/{id}/report.pdf`                             | Local: serves from FS; Cloud: 307 → GCS signed URL                       |
| Automated trigger       | Core case-processing → Core `POST /investigations/ssi` → SSI Service                                             | Same endpoint, no UI involvement                                          |

**Local dev requirement:** Core must have `I4G_SSI__SERVICE_URL=http://localhost:8100` so it can reach the SSI service.

---

## 5. Database Schema (Key Tables)

### Core tables (`src/i4g/store/sql.py`, METADATA)

- `cases` — Central entity, one per scam report. PK: `case_id`. Carries classification, status, tags, metadata JSON.
- `source_documents` — Evidence chunks. FK: `case_id`. Has `document_id` (UUID), `title`, `mime_type`, `source_url`.
- `review_queue` — Analyst work queue. Links to `case_id`. Has priority, status, assignment, classification results.
- `review_actions` — Audit log. FK: `review_id`. Stores `actor`, `action`, `payload` (JSON), `created_at`.
- `indicators` — Fraud indicators (wallets, phones, URLs). FK: `case_id`. Typed with confidence scores.
- `entities` — Extracted entities (persons, emails). FK: `case_id`.
- `saved_searches` — Persisted analyst queries.
- `dossier_queue` — Report generation tasks.
- `intake_records/attachments/jobs` — Victim submission pipeline.

### SSI tables (shared DB — defined in both `core/src/i4g/store/sql.py` and `ssi/src/ssi/store/sql.py`)

- `site_scans` — Investigation metadata. PK: `scan_id`. Has `case_id` FK, `evidence_path`, `scan_status`, `risk_score`, `classification` JSON.
- `harvested_wallets` — Wallet addresses. FKs: `case_id`, `scan_id`.
- `agent_sessions` — Per-action audit trail for browser agent.
- `pii_exposures` — What PII the scam site collects.

### Key relationships

```
cases ──1:N──▶ source_documents (evidence files)
cases ──1:N──▶ indicators (wallets, IPs, etc.)
cases ──1:N──▶ entities (persons, emails)
review_queue ──1:N──▶ review_actions (timeline)
cases ──1:1──▶ site_scans (SSI investigation)
site_scans ──1:N──▶ harvested_wallets
```

---

## 6. Common Pitfalls (Do NOT Repeat)

1. **404 on artifact links** — Core returns `/cases/{id}/evidence/{doc_id}`. UI must prefix with `/api` for browser-facing `<a href>`. Without `/api`, the browser hits a nonexistent Next.js page route.

2. **Assuming auth issues locally** — `I4G_ENV=local` bypasses ALL auth. A 404 or 500 is never an auth problem locally. Check: route existence, data existence, correct URL path.

3. **Duplicate PDF URLs** — SSI PDF report has TWO paths that reach the same core endpoint:
   - Dedicated: `/api/ssi/report/{scan_id}` (preferred — handles GCS redirects, sets Content-Disposition)
   - Catch-all: `/api/investigations/ssi/{scan_id}/report.pdf` (also works but less robust)
     Always use the dedicated route for consistency.

4. **SSI investigation routes always go through Core** — Investigation trigger and status polling are always proxied via Core API, not direct to SSI. This applies to both local and cloud. Core orchestrates the workflow (task creation, dedup, dispatch, status tracking). Only eCX routes go direct to SSI. If adding new SSI investigation endpoints, route them through Core.

5. **Router registration order** — SSI routers with specific paths (wallets, evidence) must be registered before the `/{scan_id}` catch-all. Changing order in `app.py` can break routing.

6. **Server vs client component data** — Server components fetch from `I4G_API_URL` directly. Client components fetch from `/api/*` (proxied). URLs returned by the API are meant for the API, not the browser. When rendering links in server components, add the `/api` prefix.

7. **Evidence storage abstraction** — `EvidenceStorage` abstracts local FS vs GCS. In local mode it uses `data/evidence/`. In cloud it uses GCS buckets with signed URLs. Never hardcode file paths — use the `EvidenceStorage` interface.

8. **Case ≠ Review** — `case_id` and `review_id` are different. `review_queue.review_id` references `scam_records` (legacy RAG pipeline). `cases.case_id` is the modern entity. Both exist in parallel. Timeline events (`review_actions`) are keyed by `review_id`, not `case_id`. The `get_extended_case()` method joins them.
