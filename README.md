# 🧠 i4g — Intelligence for Good

> *Empowering digital safety through AI-driven scam intelligence.*

---

## 🌍 Overview

**i4g** (Intelligence for Good) is an experimental AI platform designed to detect, analyze, and classify online scams — especially **crypto** and **romance scams targeting seniors**.

It integrates **OCR, LLMs, retrieval-augmented generation (RAG), and structured data pipelines** to transform unstructured chat histories into actionable intelligence for fraud prevention and law enforcement support.

---

## 🎯 Project Vision

The i4g platform aspires to build a complete intelligence lifecycle that:

1. **Analyzes** scam-related communications (chats, screenshots, messages)
2. **Extracts and classifies** key entities, scam types, and patterns
3. **Builds knowledge bases** for analysts and automated systems
4. **Generates structured reports** suitable for law enforcement submission

---


> This repository (proto) contains the canonical architecture, production PRD, and technical design documents for i4g.
> Planning artifacts (prototypes, milestones, and experimental PRDs) are stored in the separate `planning/` workspace.

---

## 📚 Documentation

### Key Docs (Quick Links)
- 📋 **Production PRD** — `proto/docs/prd_production.md` (Product & deployment requirements)
- 🏗️ **Architecture** — `proto/docs/architecture.md` (High-level system design, data flow)
- 🔧 **Technical Design (TDD)** — `proto/docs/tdd.md` (API contracts, schemas, runtime requirements)
- 💻 **Developer Guide** — `proto/docs/dev_guide.md` (Local setup, bootstrapping, dev workflow)
- 🧭 **Runbooks & Playbooks** — `proto/docs/runbooks/analyst_runbook.md` (Analyst index + console runbooks)
- 🧪 **Smoke & Tests** — `proto/docs/smoke_test.md` (Verification scripts and verification playbooks)
- ☁️ **Infrastructure Ops** — `infra/` (Terraform modules, deploy notes)

Other helpful docs:
- 🔐 **Identity & IAM** — `proto/docs/iam.md`
- 🔍 **Hybrid Search Deployment Checklist** — `proto/docs/hybrid_search_deployment_checklist.md`
- 📦 **Retrieval / Vertex guide** — `proto/docs/retrieval_gcp_guide.md`
 - 🖼️ **Diagrams** — `proto/docs/diagrams/` (High-level Draw.io exports & copies)
 - 🧪 **Examples** — `proto/docs/examples/` (test data, example cases)
 - ⚙️ **Config Recipes** — `proto/docs/config/` (Settings and TOML examples)

 - Planning, milestone tracking, and prototype artifacts are maintained in the separate `planning/` workspace.

### Technical Documentation
- 🏗️ **[System Architecture](./docs/architecture.md)** - High-level system design, deployment, and data flow
- 🔧 **[Technical Design Document](./docs/tdd.md)** - Detailed implementation specs, APIs, and security design
- 💻 **[Developer Guide](./docs/dev_guide.md)** - Setup instructions, development workflow
- ☁️ **[Infrastructure Operations](../infra/README.md)** - Terraform workflow, environment bootstrap, and GCP prerequisites

### Governance & Compliance
- 🔒 **[Data Compliance Guide](./docs/compliance.md)** - PII handling, FERPA/GDPR compliance, incident response
 - 📜 **[Confidentiality Agreement](./docs/confidentiality_agreement.md)**
 - 🤝 **Contribution guide** — `./docs/contributing.md` and `./docs/contributors.md`

---

## 📄 License

Licensed under the **MIT License**.
All AI-generated components are for educational and research use only.
