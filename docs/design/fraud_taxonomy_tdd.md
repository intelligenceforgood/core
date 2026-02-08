# Technical Design: Fraud Taxonomy & Classification System

**Status:** Active (v1.1)
**Owner:** IntelligenceForGood
**Related PRD:** [planning/fraud_taxonomy_prd.md](../../../../planning/fraud_taxonomy_prd.md)

## 1. Overview
This document outlines the technical implementation of the Fraud Taxonomy system, including data structures, storage, AI classification strategy, and tooling for managing the taxonomy as code.

## 2. Taxonomy Architecture
The system uses a multi-axis classification model. Each submission is scored independently across five axes.

### 2.1 Classification Axes
1. **Scam Intent** (Primary Fraud Type) - e.g., Imposter, Investment, Romance.
2. **Delivery Channel** - e.g., SMS, Email, WhatsApp.
3. **Social Engineering Technique** - e.g., Urgency, Authority, Trust Building.
4. **Requested Action** - e.g., Send Money, Buy Gift Cards.
5. **Claimed Persona** - e.g., Government, Bank, Tech Support.

### 2.2 Single Source of Truth (SSOT)
To ensure consistency across Python (Backend), TypeScript (Frontend), and Documentation, the taxonomy is defined in a language-agnostic YAML file.

**File Location:** `core/src/i4g/taxonomy/definitions.yaml`

**Schema:**
```yaml
intents:
  - code: "INTENT.IMPOSTER"
    label: "Imposter Scam"
    description: "Pretending to be a trusted entity"
    version_added: "1.0"
channels:
  - code: "CHANNEL.SMS"
    label: "SMS / Smishing"
    ...
```

**Generation Pipeline:**
A build script (`i4g taxonomy refresh`) consumes this YAML to generate:
- **Backend Data:** `core/src/i4g/taxonomy/data.py` containing the full taxonomy tree as a Python dictionary (`TAXONOMY_DEFINITIONS`).
- **Frontend Types:** `ui/packages/types/src/taxonomy.ts` containing TypeScript **Interfaces** only (`TaxonomyAxis`, `TaxonomyItem`).
- **Documentation:** `docs/taxonomy_reference.md` (Auto-generated documentation).

**Dynamic Loading Architecture:**
Unlike traditional builds that compile enumerations into the frontend bundle, this system uses a **runtime fetch model**:
1. **Backend:** The API loads `TAXONOMY_DEFINITIONS` from `data.py` and serves it via `GET /taxonomy`.
2. **Frontend:** The UI fetches this endpoint on load to populate tooltips, search filters, and badges.
3. **Benefits:** Descriptions, labels, and even new categories can be updated in the backend (or via OTA updates) without requiring a UI rebuild.

## 3. Data Model & Schema

### 3.1 Output Schema
The classification engine returns a structured JSON object.

```json
{
  "intent": [{"label": "INTENT.INVESTMENT", "confidence": 0.92}],
  "channel": [{"label": "CHANNEL.CHAT", "confidence": 0.88}],
  "techniques": [
    {"label": "SE.TRUST_BUILDING", "confidence": 0.76}
  ],
  "actions": [{"label": "ACTION.CRYPTO", "confidence": 0.91}],
  "persona": [{"label": "PERSONA.ROMANTIC", "confidence": 0.85}],
  "taxonomy_version": "1.0"
}
```

### 3.2 Pydantic Models
Strict validation is enforced via Pydantic models in `core/src/i4g/taxonomy/models.py`.

```python
class ScoredLabel(BaseModel):
    label: str
    confidence: float = Field(ge=0.0, le=1.0)

class ClassificationResult(BaseModel):
    intent: List[ScoredLabel]
    channel: List[ScoredLabel]
    # ... other axes
    taxonomy_version: str
```

## 4. Storage Strategy

### 4.1 Database Schema
Results are stored in the primary database (PostgreSQL) attached to the `Review` or `Case` object.

- **Field:** `classification_result`
- **Type:** `JSONB` (PostgreSQL)
- **Versioning:** The `taxonomy_version` field is mandatory to support future migrations.

### 4.2 Indexing
To enable efficient filtering (e.g., "Find all Romance Scams"), high-confidence labels (confidence > 0.85) are promoted to a top-level array field.

- **Field:** `tags`
- **Value:** `["INTENT.ROMANCE", "CHANNEL.SMS", "ACTION.CRYPTO"]`

## 5. AI Classification Strategy

### 5.1 Model Approach
We utilize a **Few-Shot Learning** approach with a Large Language Model (LLM).

### 5.2 Golden Dataset
A curated dataset of examples is maintained in `core/data/taxonomy/golden_examples.json`.
- **Purpose:**
  1. **Prompt Injection:** Relevant examples are dynamically inserted into the LLM prompt to guide classification.
  2. **Evaluation:** Used as a regression test suite to measure Precision/Recall before taxonomy updates.

### 5.3 Prompt Engineering
The prompt is constructed dynamically:
1. **Role:** Expert Fraud Analyst.
2. **Definitions:** Injected from `definitions.yaml`.
3. **Examples:** Injected from `golden_examples.json`.
4. **Input:** The victim's narrative or message content.
5. **Output Constraint:** Strict JSON format matching the schema.

## 6. Confidence, Risk Scoring & Calibration

### 6.1 Confidence Scores
- **Raw Scores:** Derived from LLM self-reported confidence (0.0 - 1.0).
- **Thresholds:**
  - **High (>0.85):** Displayed prominently, used for indexing.
  - **Medium (0.60 - 0.85):** Displayed with "Low Confidence" warning.
  - **Low (<0.60):** Discarded or logged for review.

### 6.2 Risk Scoring
To prioritize analyst reviews, a scalar `risk_score` (0-100) is calculated for each classification.

- **Risk Weights:** Each taxonomy definition (Intent, Technique, Action) is assigned a `risk_weight` (1-10) in `definitions.yaml`.
  - *High (8-10):* Extortion, Crypto Transfer, Urgency.
  - *Medium (4-7):* Romance, Imposter, Grooming.
  - *Low (1-3):* Generic spam.

- **Calculation Formula:**
  The score is a weighted sum of all detected labels, scaled and capped.

  $$ \text{Score} = \min\left(100.0, \left(\sum (\text{confidence} \times \text{weight})\right) \times 2.5\right) $$

  *Note: The 2.5 multiplier scales the raw weighted sum (typically ~20-40 for a strong signal) to the 0-100 range.*

## 7. Governance & Evolution

### 7.1 Versioning
The taxonomy follows semantic versioning (e.g., `v1.0`, `v1.1`).
- **Non-breaking:** Adding a new label.
- **Breaking:** Renaming or removing a label (requires migration).

### 7.2 Analyst Feedback
Analyst overrides in the UI are captured via the API and used to improve the system.

- **Endpoint:** `POST /reviews/{review_id}/feedback`
- **Payload:** `AnalystFeedbackRequest` (contains corrected classification)
- **Outcome:**
  1. Updates the specific case in the store.
  2. Logs the feedback event for offline analysis.
  3. Flags the example for potential inclusion in the **Golden Dataset**.
