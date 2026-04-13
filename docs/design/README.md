# Design Docs

Purpose: long-lived architectural references—system topology, IAM/security, and data custody. Use these when making cross-cutting or platform decisions.

## Contents

- System architecture: [architecture.md](architecture.md)
- Data model & ERD: [data_model.md](data_model.md)
- Entity extraction pipeline: [entity_extraction_tdd.md](entity_extraction_tdd.md)
- Fraud taxonomy & classification: [fraud_taxonomy_tdd.md](fraud_taxonomy_tdd.md)
- IAM strategy: [iam.md](iam.md)
- Background jobs & workers: [jobs.md](jobs.md)
- PII protection: [pii_protection.md](pii_protection.md)
- RAG & hybrid search: [rag.md](rag.md)
- Storage architecture: [storage.md](storage.md)
- Threat intelligence & analytics: [threat_intelligence_analytics_tdd.md](threat_intelligence_analytics_tdd.md)

## When to add here

- Architectural decisions, security/identity models, data custody and trust boundaries, or diagrams that outlive a sprint.
- Prefer short pages that link back to the docs hub. For implementation details or how-tos, use [development](../development/README.md) or [cookbooks](../cookbooks/README.md).
