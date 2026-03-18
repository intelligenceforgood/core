# Glossary

Common terms and abbreviations across the project. Keep entries short and link to the authoritative doc or schema.

- **Ingestion pipeline** — End-to-end flow from classified payload to structured store, SQL dual-write, and optional vector/Vertex fan-out. See [tdd.md](tdd.md#6-ingestion-flow-canonical) and [architecture.md](../design/architecture.md).
- **Structured store** — SQLite-backed record store used for analyst console reads and worker jobs. See [src/i4g/store/structured.py](src/i4g/store/structured.py).
- **Dual-write (SQL)** — Persistence of cases/entities/documents to SQL tables alongside structured store for hybrid search. See [src/i4g/store/sql.py](src/i4g/store/sql.py).
- **Hybrid search** — Combines vector retrieval with structured filters from SQL entities; powered by `HybridRetriever`. See [tdd.md](tdd.md#7-apis-and-contracts-current-surface) and [architecture.md](../design/architecture.md).
- **Intake encryption** — Fernet encryption of victim contact fields (reporter name, email, phone, handle) on intake write; decrypted on authorized read. See [pii_vault.md](../design/pii_vault.md).
- **Sandbox** — Local dataset + stores used for development and smokes (`data/`, SQLite, Chroma). Rebuild via `i4g bootstrap local reset --report-dir data/reports/local_bootstrap`.
- **Smoke test** — Fast validation of critical paths (ingestion, search, UI) described in [cookbooks/smoke_test.md](cookbooks/smoke_test.md).
- **Dataset** — Logical label on cases/entities indicating source or tenant (e.g., `network_demo`, `dual_demo`); default comes from `ingestion.default_dataset` in settings.
- **Saved search schema** — JSON schema for `/reviews/search` requests stored in the API; refresh via `/reviews/search/schema`. See [docs/runbooks/console/search.md](docs/runbooks/console/search.md#L1).
- **Evidence dossier** — Generated report bundle with manifest and signatures; see [docs/runbooks/console/reports.md](docs/runbooks/console/reports.md#L1) and [reports/](reports/).
- **Vector store** — Embedding backend (default Chroma) holding chunked case texts for semantic search. Configured under `vector.*` settings.
- **Chroma** — Default local vector backend; persisted under `vector.chroma_dir` (e.g., `data/chroma_store`).
- **Fraud type** — Classification label on a case (e.g., `tech_support`, `romance`, `pig_butcher`); stored in structured and SQL tables.
- **Indicator** — Structured signal (bank account, wallet, email, phone, IP) captured in `indicators` table; used for structured filters.
