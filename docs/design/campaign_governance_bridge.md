# Architecting for Dual-Speed Operations: Campaigns & Governance

> **Status:** Draft / Proposed
> **Related Design:** [Review & Campaign Engine](./review_engine.md), [Fraud Taxonomy TDD](./fraud_taxonomy_tdd.md)

## 1. Design Philosophy

The i4g platform adopts a **Dual-Speed Architecture** to handle the inherent conflict between the rapid evolution of fraud tactics and the need for stable, consistent organizational reporting.

Instead of forcing a single classification system to serve both masters, we proactively implement two distinct but interlinked layers:

1.  **Governance Taxonomy:** The stable, strategic categorization of risk (Policy-driven).
2.  **Active Campaigns:** The agile, tactical clustering of threats (Ops-driven).

This document outlines the **Integration Layer** (the "Golden Thread") that connects these two speeds, allowing the platform to be both agile in detection and consistent in reporting.

### 1.1 The Dual-Speed Model

| Layer                   | Speed         | Owner          | Purpose                                    | Example                       |
| ----------------------- | ------------- | -------------- | ------------------------------------------ | ----------------------------- |
| **Governance Taxonomy** | Slow (Annual) | Policy / Execs | Strategic Reporting, Regulatory Compliance | "Investment Fraud"            |
| **Active Campaigns**    | Fast (Weekly) | Analysts / Ops | Tactical Detection, Immediate Response     | "Crypto Investment Scam 2025" |

This separation protects long-term reporting metrics from the volatility of daily fraud patterns.

## 2. Architecture

### 2.1 The Integration Strategy

We upgrade the `Campaign` concept from a simple "Filter Bucket" into a **Strategic Classifier**.

- **Inputs (Tactical):** The technical detection rules (keywords, regex, AI models) that identify a specific fraud pattern.
- **Outputs (Strategic):** The `associated_taxonomy_ids` field that explicitly maps this tactical pattern to its governing policy category.

This mapping acts as the translation layer between "What is happening now" and "What it means for the organization."

### 2.2 Data Flow

1.  **Ingestion & Classification:** The system observes a case with raw technical signals (e.g., specific pig-butchering script text).
2.  **Tactical Matching:** The `CampaignService` identifies this as part of the "Crypto Pig Butchering" Campaign.
3.  **Strategic Rollup:** Because the Analyst has explicitly linked this Campaign to the `INTENT.INVESTMENT` (Investment) node, the system immediately understands the strategic impact.
4.  **Result:** Operational teams work the "Pig Butchering" queue, while Executive dashboards automatically reflect an increase in "Financial Facilitation" risk.

## 3. Implementation Design

### 3.1 Database Schema State

The design requires extending the `campaigns` persistence model to hold this strategic link.

**Recommended Schema:**
A dedicated `taxonomy_rollup` column ensures this relationship is a first-class citizen in the data model.

```json
{
  "name": "Romance Scam Winter 2025",
  "filters": { "intent": ["romance"], "techniques": ["grooming"] },
  "reporting_categories": ["INTENT.ROMANCE", "INTENT.INVESTMENT"]
}
```

### 3.2 Analyst Workflow

1.  **Creation:** When an Analyst identifies a new threat cluster and creates a Campaign, they define the _tactical_ rules.
2.  **Association:** The interface prompts the Analyst to assign a _strategic_ parent category from the Governance Taxonomy.
3.  **Outcome:** The Analyst essentially "tells" the system: _"This new thing I found (Campaign) is an instance of this known risk (Taxonomy)."_

## 4. Strategic Benefits

1.  **Agility without Chaos:** Operations teams can create hundreds of Campaigns to chase evolving threats without polluting the high-level reporting structure.
2.  **Automated Insight:** Leadership gets real-time visibility into strategic risk categories without manual aggregation of spreadsheets.
3.  **Future-Proofing:** Operational detection methods can change completely (e.g., moving from keywords to vector search) without effective reporting metrics, as long as the Campaign-to-Taxonomy link is maintained.

## 5. Reconciliation with Threat Campaigns (Sprint 6)

Sprint 6 introduced the `threat_campaigns` analytics model (see `src/i4g/store/sql.py`), which provides a complementary statistical view of campaigns. The two models coexist:

| Aspect             | Governance Campaign (this doc)           | Threat Campaign (TIFAP)                                   |
| ------------------ | ---------------------------------------- | --------------------------------------------------------- |
| **Purpose**        | Strategic taxonomy rollup                | Operational analytics aggregation                         |
| **Schema**         | `campaigns` + `campaign_classifications` | `campaign_stats` (materialized aggregates)                |
| **Owner**          | Policy / Executive                       | Operations / Analyst                                      |
| **Update cadence** | Manual (analyst-driven)                  | Automated (aggregation job)                               |
| **Key fields**     | `reporting_categories`, taxonomy IDs     | `case_count`, `indicator_count`, `loss_sum`, `risk_score` |

### Integration points

- The `campaign_stats.campaign_id` foreign key links to the governance `campaigns` table, preserving the "Golden Thread" between tactical detection and strategic reporting.
- The aggregation job (`i4g jobs aggregate`) refreshes `campaign_stats` metrics without altering the governance taxonomy mappings.
- Blockchain enrichment (Sprint 6) adds wallet cluster edges to `GraphService`, enabling graph-based campaign discovery that feeds back into governance campaign creation.
- The partner feed API (`/feeds/indicators`) exports indicators with campaign context, bridging operational data and external consumers.
