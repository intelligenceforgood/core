# Core Service — Master Technical Design Document

> **This is the master TDD for `core-svc`.** It scopes the system and links to detailed design documents.
> It is not a monolithic spec — deep implementation detail lives in the linked subsystem docs.
> Read this document first; follow links for the detail you need.
>
> **Version:** 3.1 • **Last Updated:** 2026-03-20 • **Last Verified:** 2026-03-20

For high-level architecture diagrams and deployment topology, start with [architecture.md](../design/architecture.md).
For platform-level context (all services, integration contracts, ADRs), see [system_narrative.md](../../../planning/architecture/system_narrative.md).

**Audience:** Software engineers, DevOps/SRE, security reviewers.

### Quick Navigation

- [System Scope](#1-system-scope)
- [Subsystem Index](#2-subsystem-index)
- [Key Architectural Decisions](#3-key-architectural-decisions)
- [Configuration and Environment](#4-configuration-and-environment)
- [Ingestion Flow](#5-ingestion-flow-canonical)
- [APIs and Contracts](#6-apis-and-contracts-current-surface)
- [Data Model and Schemas](#7-data-model-and-schemas)
- [Reports and Dossiers](#8-reports-and-dossiers)
- [Deployment Profiles](#9-deployment-profiles)
- [Security and Compliance](#10-security-and-compliance)
- [Testing and Validation](#11-testing-and-validation)

---

## 1) System Scope

`core-svc` is the central FastAPI backend for the I4G platform. It owns:

- The full analyst API surface (22 routers: reviews, cases, intakes, reports, analytics, intelligence, campaigns, taxonomy, feeds, etc.)
- The ingestion pipeline: normalization → SQL dual-write → vector indexing → PII encryption
- Report and dossier generation
- TIFAP (Threat Intelligence & Fraud Analytics Platform) — graph service, campaign detection, partner feeds — **internal to core-svc, not a separate service**
- The SSI integration orchestration layer (core is the caller; SSI is a separate Cloud Run service)

**Explicit boundaries** — `core-svc` does NOT:

- Run browser automation or headless Chromium (that is `ssi-svc`)
- Own the analyst console frontend (that is `ui/apps/web/`, a Next.js app on a separate Cloud Run service)
- Run on the same process as SSI; cross-service calls are HTTP with OIDC auth

---

## 2) Subsystem Index

| Subsystem                                          | Brief Description                                                  | Primary Doc                                                                                                                       | Last Verified |
| -------------------------------------------------- | ------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| Ingestion pipeline (ingest-job, intake-job)        | Normalize → encrypt PII → dual-write SQL + vector                  | [jobs.md](../design/jobs.md)                                                                                                      | March 2026    |
| Review/search API (HybridRetriever, ReviewStore)   | Hybrid retrieval, saved searches, analyst queue                    | [rag.md](../design/rag.md)                                                                                                        | March 2026    |
| Analyst console API surface (22 routers)           | Full REST surface for the Next.js console                          | [api_reference.md](../api_reference.md)                                                                                           | March 2026    |
| Report generation (report-job, template system)    | Dossier assembly, LEA handoff, signature manifest                  | [jobs.md](../design/jobs.md)                                                                                                      | March 2026    |
| Fraud taxonomy system (LLM tagging, versioning)    | Classification, tag hierarchy, confidence versioning               | [fraud_taxonomy_tdd.md](../design/fraud_taxonomy_tdd.md)                                                                          | March 2026    |
| Threat Intelligence / TIFAP (campaign detection)   | Graph service, watchlist, partner indicator feeds                  | [threat_intelligence_analytics_tdd.md](../design/threat_intelligence_analytics_tdd.md)                                            | March 2026    |
| Campaign governance bridge                         | Links campaigns to fraud taxonomy classification                   | [campaign_governance_bridge.md](../design/campaign_governance_bridge.md)                                                          | March 2026    |
| PII vault (Fernet encryption, audit-logged access) | Victim contact encryption, key rotation, audit log                 | [pii_vault.md](../design/pii_vault.md)                                                                                            | March 2026    |
| SSI integration (enrichment contracts)             | Core→SSI enrich requests, SSI→Core callbacks                       | [ssi/docs/tdd.md](../../../ssi/docs/tdd.md) + [integration_contracts.md](../../../planning/architecture/integration_contracts.md) | March 2026    |
| Background job system (4 Cloud Run jobs)           | ingest-bootstrap, process-intakes, generate-reports, dossier-queue | [jobs.md](../design/jobs.md)                                                                                                      | March 2026    |
| Data stores (SQL, vector, blob)                    | Cloud SQL / SQLite, Chroma / Vertex AI, GCS                        | [storage.md](../design/storage.md) + [data_model.md](../design/data_model.md)                                                     | March 2026    |
| IAM and authentication                             | IAP, OIDC, service accounts, role matrix                           | [iam.md](../design/iam.md)                                                                                                        | March 2026    |
| Retrieval (RAG, hybrid search)                     | LangChain LCEL, vector + SQL merge, structured filters             | [rag.md](../design/rag.md)                                                                                                        | March 2026    |

> Items marked `?` for Last Verified should be confirmed during the next quarterly doc review (see `copilot/.github/shared/doc-governance.instructions.md`).

---

## 3) Key Architectural Decisions

| Decision                | Choice Made                                           | Key Reason                                                                                                          | ADR                                                                             |
| ----------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| Cloud provider          | GCP (Cloud Run, Cloud SQL, Vertex AI, Secret Manager) | Nonprofit credits, managed serverless                                                                               | [ADR-001](../../../planning/architecture/adr/adr-001-azure-to-gcp-migration.md) |
| API framework           | FastAPI + Pydantic v2                                 | Async-first, automatic schema validation, `alias_generator = to_camel` eliminates manual translation                | [ADR-002](../../../planning/architecture/adr/adr-002-fastapi-pydantic-v2.md)    |
| SSI as separate service | ssi-svc on its own Cloud Run instance                 | Browser automation isolation; Chromium can't share a container with the API under Cloud Run constraints             | [ADR-003](../../../planning/architecture/adr/adr-003-ssi-separate-service.md)   |
| PII encryption          | Fernet (symmetric, audited)                           | Key-per-tenant not yet needed; Fernet is well-audited, fast for field-level encryption, and supports key rotation   | [ADR-004](../../../planning/architecture/adr/adr-004-pii-vault-fernet.md)       |
| Vector store            | Chroma (local) / Vertex AI Search (cloud)             | Chroma for frictionless local dev; Vertex AI Search in production for managed scaling                               | [ADR-005](../../../planning/architecture/adr/adr-005-chroma-vs-pgvector.md)     |
| Task status             | In-memory `TASK_STATUS` dict                          | Simplest implementation for single-instance dev; known limitation for multi-instance prod (Redis migration planned) | —                                                                               |
| Settings pattern        | `I4G_*` env vars with `__` nesting                    | Pydantic BaseSettings with TOML defaults gives deterministic override chain without custom parsing                  | [config docs](../config/)                                                       |

---

## 4) Configuration and Environment

## 4) Configuration and Environment

- Load settings via `i4g.settings.get_settings()`; overrides: `config/settings.*.toml` → `.env.local` → `I4G_*` env vars (double underscores for nesting).
- Key toggles (ingestion):
  - `ingestion.enable_sql` (dual-write tables)
  - `ingestion.enable_vector_store`
  - `ingestion.enable_vertex`
  - `ingestion.default_dataset`
- Paths: `storage.sqlite_path`, `vector.chroma_dir`, `ingestion.dataset_path`, `data/` assets seeded via `i4g bootstrap local reset --report-dir data/reports/local_bootstrap`.
- Secrets: prefer Secret Manager in managed envs; local `.env.local` for the Fernet key (`I4G_CRYPTO__PII_KEY`).
- For adding a new setting: (a) add under the appropriate section in `config/settings.default.toml`, (b) add coverage under `tests/unit/settings/`, (c) refresh `docs/config/` env-var table + YAML manifest via `scripts/export_settings_manifest.py`.

### Data Stores (quick reference)

See [storage.md](../design/storage.md) and the Subsystem Index for full detail.

---

## 5) Ingestion Flow (canonical)

1. **Input normalization**: `prepare_ingest_payload()` merges text, entities, structured fields, network entities, metadata, dataset.
2. **Intake encryption**: `IntakeStore.create()` encrypts victim contact fields (reporter_name, contact_email, contact_phone, contact_handle) with Fernet before the database write.
3. **Structured write**: `StructuredStore.upsert_record()` persists the `ScamRecord` for console reads.
4. **Case bundle build**: `build_case_bundle()` assembles `CasePayload`, `SourceDocumentPayload`, `EntityPayload` from classification result and metadata.
5. **SQL dual-write**: `SqlWriter.persist_case_bundle()` writes cases/entities/documents; controlled by `enable_sql`.
6. **Vector write**: `vector_store.add_records()` writes embeddings when vector enabled; Vertex writer optional.
7. **Optional fan-out**: Vertex fan-out gated by settings and env (and builder availability).
8. **Retry**: ingestion retry queue (SQL table) for downstream fan-out errors.

## 7) APIs and Contracts (current surface)

- **Search/Reviews**
  - `POST /reviews/search` and `GET /reviews/search/schema`; payload matches `HybridSearchRequest` (text + vector/structured filters).
  - `GET /reviews/{id}` returns case/review details with entity annotations; aligns with SQL + structured store schema.
  - Saved searches: stored per owner/shared; schema driven by `search.saved_search` settings; admin CLI `i4g-admin export/import`.
- **Tasks/Status**
  - `GET /tasks/{task_id}` for job state (ingestion/report jobs); used by UI for progress.
- **Intake API**
  - `POST /intakes/` creates a new intake record (contact fields encrypted at rest).
  - `GET /intakes/{id}/contact` returns decrypted contact fields with audit logging.
- **Reports/Dossiers**
  - Report generation entrypoints map to worker tasks; dossiers produced by queue jobs and surfaced in console.
- **Ingestion jobs**
  - CLI/Cloud Run jobs (`i4g jobs ingest`, `i4g jobs intake`) consume normalized ingestion payloads (`prepare_ingest_payload` contract).

## 8) Data Model and Schemas

- **Structured store record** (`ScamRecord`): `case_id`, `text`, `entities{type:[value]}`, `classification`, `confidence`, `metadata`.
- **SQL dual-write tables** (see `src/i4g/store/sql.py`):
  - `cases`: dataset, classification, confidence, raw_text_sha256, status, metadata.
  - `entities`: entity_type, canonical_value, raw_value, confidence (unique per case/type/value).
  - `source_documents`: text chunks, mime, source_url, chunk_index/count.
  - `indicators`: structured signals (email/phone/ip/crypto/wallet/etc.).
  - `ingestion_runs`: run metadata and counts; `ingestion_retry_queue`: fan-out retries.
- **Vector store payload**: chunked text with case_id/document_id; embeddings stored in Chroma by default.
- **Intake encryption**: `intake_records` table stores Fernet-encrypted contact fields; decrypted on authorized read.
- **Saved search schema**: JSON schema at `/reviews/search/schema`; snapshot at `docs/examples/reviews_search_schema.json`.

## 9) Reports and Dossiers

- **Generation**: `generate_report_for_case` and dossier queue workers produce manifests and signed bundles.
- **Signatures**: manifests hashed and signed; verification helper in `src/i4g/reports/dossier_signatures.py`.
- **Handoff**: runbooks in `docs/runbooks/console/reports.md` and `docs/runbooks/dossiers_subpoena_handoff.md`.

## 10) Deployment Profiles

- **Managed (Cloud Run/GCP)**: Cloud SQL/Cloud Storage, Secret Manager, Vertex optional; Workload Identity; IAP for portals.
- **Local**: SQLite + Chroma, mock identity, `.env.local` secrets, scheduled jobs off; run via `uvicorn i4g.api.app:app --reload` and cookbooks in `docs/cookbooks/`.
- Settings remain identical across profiles; swapping is env + config only.

## 11) Security & Privacy

- Victim contact fields encrypted at intake via Fernet; investigation entities stored in cleartext.
- Access control: Identity Platform/IAP (managed), mock tokens (local). Audit logging via store log actions.
- Secrets management: Secret Manager in managed envs; avoid embedding secrets in code/docs.
- Data residency: artifacts under `data/` locally; buckets per env.

## 12) Testing & Quality

- Unit/contract tests in `tests/unit/`; settings/env overrides covered in `tests/unit/settings/`.
- Smokes and recipes: `docs/cookbooks/smoke_test.md`, `docs/cookbooks/bootstrap_environments.md`.
- Runbooks: `docs/runbooks/` for operational checks; Playwright smokes in `ui/` for console.
- Before releases: follow `docs/release/README.md` checklist; regenerate settings manifests when toggles change (`scripts/export_settings_manifest.py`).

## 13) Open Follow-Ups

- Add pgvector/Vertex AI vector backends to parity with Chroma in factories.
- Refresh saved-search schema snapshot and ensure UI fixtures stay aligned.
- Expand TDD API section with up-to-date request/response samples for search/tasks/intake once stabilized.

---

**Last Updated**: 2026-03-20<br/>
**Last Verified**: 2026-03-20<br/>
**Next Review**: 2026-06-20
