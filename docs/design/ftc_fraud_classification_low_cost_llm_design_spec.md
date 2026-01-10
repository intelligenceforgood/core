# Design Specification: FTC Consumer Fraud Classification System (Low-Cost, No-Fine-Tuning)

## 1. Purpose

Design and implement a **low-cost, fast, and scalable fraud classification system** that assigns **FTC Consumer Fraud Categories and Subcategories** to unstructured text (SMS, emails, complaints, call summaries, etc.) using **hosted LLM inference only**.

This system is optimized for:
- No labeled training corpus
- No GPU access
- Non-profit / limited budget constraints
- Both real-time and batch inference (≈10K cases)

---

## 2. Non-Goals

The system will **not**:
- Train or fine-tune any model
- Host or deploy open-source LLMs
- Perform fraud detection as a binary classification problem
- Replace downstream human review in high-risk cases

---

## 3. Key Constraints

| Constraint | Impact |
|----------|--------|
| No labeled data | Rules out supervised ML / fine-tuning |
| No GPUs | Rules out local LLM hosting |
| Low cost | Requires batching, caching, and token minimization |
| Fast response | Requires instruction-following models with structured output |
| 10K batch inference | Requires request batching and async execution |

---

## 4. High-Level Architecture

```
Input Text
   ↓
Preprocessing & Normalization
   ↓
Rule-Based Short-Circuit (Optional)
   ↓
LLM Classification (Batched)
   ↓
Structured JSON Output
   ↓
Post-Processing & Storage
```

---

## 5. FTC Taxonomy Handling

### 5.1 Canonical Taxonomy Definition

The system utilizes the shared workspace taxonomy as the **Canonical Source of Truth**. This is defined in `core/data/taxonomy/definitions.yaml` and loaded into the Python runtime as a dictionary (`TAXONOMY_DEFINITIONS`).

```yaml
# From core/data/taxonomy/definitions.yaml
intents:
  - code: "INTENT.IMPOSTER"
    label: "Imposter Scams"
    description: "Scams where the fraudster pretends to be someone else."
    children:
      - "Government Imposter"
      - "Business Imposter"
```

This data structure is:
- **Loaded into prompt context** dynamically during inference.
- **Cached in application memory** (via `i4g.taxonomy.data`).
- **Unified** with the Frontend and API, ensuring the LLM classifies using the exact same definitions that users see in the UI.

---

## 6. Prompting Strategy (Core of the System)

### 6.1 Prompt Structure

Each LLM request consists of:
1. **System instruction** (classification task + constraints)
2. **FTC taxonomy summary** (compressed definitions)
3. **Output schema contract** (strict JSON)
4. **Batched input cases**

---

## 6A. Reference Prompt Template (Authoritative)

This is the **canonical prompt template** to be used for all LLM calls. It is designed to be:
- Deterministic
- Token-efficient
- Strictly structured
- Easy to maintain

### 6A.1 System Prompt

```
You are an expert fraud analyst.

Your task is to classify consumer fraud reports into FTC Consumer Fraud Categories and Subcategories.

Rules:
- Use ONLY the provided FTC taxonomy.
- Choose the single best primary category.
- Choose the most specific subcategory when applicable.
- If the case is unclear, set `ambiguous = true`.
- Do NOT invent new categories.
- Do NOT include explanations outside the JSON.
- Output MUST be valid JSON and MUST match the schema exactly.
```

---

### 6A.2 FTC Taxonomy Context (Compressed)

```
FTC Consumer Fraud Categories (summary):

Imposter Scams:
- Government Imposter: Claims to be a government agency (IRS, SSA, police, courts).
- Business Imposter: Pretends to be a legitimate company or service.
- Tech Support Imposter: Fake technical support or security alerts.

Investment Scams:
- Cryptocurrency: Crypto-based or blockchain investment schemes.
- Stocks & Bonds: Traditional securities fraud.
- Real Estate: Property or land investment scams.

Online Shopping:
- Non-delivery: Goods paid for but never received.
- Counterfeit: Fake or misrepresented goods.

Prizes, Lotteries, and Sweepstakes:
- Claims of winnings requiring payment or personal info.

Payment Methods (signals only, not primary categories):
- Gift cards, wire transfers, crypto, prepaid cards.
```

---

### 6A.3 Output Schema Contract

```
Return a JSON array. Each element MUST follow this schema:

{
  "id": "string",
  "primary_category": "string",
  "subcategory": "string | null",
  "confidence": number,
  "signals": ["string"],
  "ambiguous": boolean
}
```

Constraints:
- confidence must be between 0.0 and 1.0
- signals must be short phrases from the text

---

### 6A.4 Batched Input Cases

```
Classify the following cases:

[
  {"id": "{{CASE_ID_1}}", "text": "{{NORMALIZED_TEXT_1}}"},
  {"id": "{{CASE_ID_2}}", "text": "{{NORMALIZED_TEXT_2}}"}
]
```

---

### 6A.5 Expected Model Output (Example)

```
[
  {
    "id": "c1",
    "primary_category": "Imposter Scams",
    "subcategory": "Government Imposter",
    "confidence": 0.95,
    "signals": ["IRS", "gift cards", "arrest threat"],
    "ambiguous": false
  },
  {
    "id": "c2",
    "primary_category": "Investment Scams",
    "subcategory": "Cryptocurrency",
    "confidence": 0.92,
    "signals": ["guaranteed returns", "WhatsApp", "crypto"],
    "ambiguous": false
  }
]
```

---

### 6A.6 Notes for Implementation

- This prompt should be **assembled programmatically**.
- The taxonomy section should be loaded from the versioned taxonomy file.
- Keep taxonomy definitions concise to minimize token usage.
- Do not include examples in production unless debugging.

---


## 7. Batching Strategy (Critical for Cost)

### 7.1 Batch Size

- **10–25 cases per request**
- Each case has a stable `id`

### 7.2 Batched Input Example

```json
[
  {"id": "c1", "text": "Caller claims to be IRS demanding gift cards."},
  {"id": "c2", "text": "Guaranteed crypto returns via WhatsApp."}
]
```

### 7.3 Batched Output Example

```json
[
  {"id": "c1", "primary_category": "Imposter Scams", "subcategory": "Government Imposter", "confidence": 0.95, "signals": ["IRS", "gift cards", "threat"], "ambiguous": false},
  {"id": "c2", "primary_category": "Investment Scams", "subcategory": "Cryptocurrency", "confidence": 0.92, "signals": ["guaranteed returns", "crypto"], "ambiguous": false}
]
```

---

## 8. Cost Control Mechanisms

### 8.1 Input Normalization

Before LLM call:
- Strip signatures, disclaimers, HTML
- Truncate to max N tokens (e.g., 1–2K chars)
- Normalize phone numbers, URLs, amounts

### 8.2 Caching

- Hash normalized input text
- Cache LLM results (Redis / in-memory)
- Reuse results for duplicates or near-duplicates

### 8.3 Rule-Based Short-Circuit (Optional)

Examples:
- `IRS` + `gift card` → Government Imposter
- `crypto` + `guaranteed` → Investment Scam

Rules bypass LLM entirely.

---

## 9. Batch Inference Workflow (10K Cases)

1. Normalize all inputs
2. Deduplicate via hash
3. Apply rules
4. Chunk remaining cases into batches
5. Async LLM calls (rate-limited)
6. Merge results
7. Persist outputs

Expected runtime: **minutes, not hours**

---

## 10. Error Handling & Reliability

- Validate JSON strictly
- Retry once on malformed output
- Fallback label:
  - `primary_category = "Unknown"`
  - `ambiguous = true`

---

## 11. Confidence Calibration & Decision Policy

### 11.1 Purpose

Confidence scores emitted by LLMs are **not statistically calibrated probabilities**. They are best treated as **relative certainty indicators**. This policy defines how confidence values are interpreted and acted upon consistently.

---

### 11.2 Confidence Bands

| Confidence Range | Interpretation | Action |
|------------------|----------------|--------|
| **≥ 0.90** | Very high confidence | Accept label automatically |
| **0.75 – 0.89** | High confidence | Accept label; eligible for analytics |
| **0.60 – 0.74** | Medium confidence | Accept label but mark `review_optional = true` |
| **0.40 – 0.59** | Low confidence | Mark `ambiguous = true`; queue for secondary handling |
| **< 0.40** | Very low confidence | Assign `Unknown`; require fallback logic |

---

### 11.3 Ambiguity Handling

Set `ambiguous = true` when:
- Multiple FTC categories plausibly apply
- Text lacks sufficient context
- Signals contradict each other (e.g., payment scam vs shopping scam)

Ambiguous cases:
- Are excluded from automated reporting
- Can be routed to human review or reprocessed later

---

### 11.4 Secondary Handling for Low Confidence Cases

For cases with confidence < 0.75:

Optional strategies (ordered by cost):
1. **Re-run with expanded context** (less truncation)
2. **Re-run with smaller batch size** (more attention per case)
3. **Apply deterministic rules** (if signals match)
4. **Human review** (if available)

---

### 11.5 Drift Monitoring

Continuously monitor:
- Mean confidence per category
- % of ambiguous cases over time
- Sudden confidence drops after taxonomy changes

Alerts should trigger when:
- Ambiguous rate increases > X% week-over-week
- A category’s mean confidence drops below historical baseline

---

### 11.6 Optional Lightweight Calibration (Future)

If historical labeled samples become available:
- Apply simple post-hoc calibration (e.g., isotonic or Platt scaling)
- Calibration applies **after inference**, no retraining required

---

## 12. Metrics & Monitoring

Track:
- Category distribution drift
- % ambiguous cases
- Average confidence
- Cost per 1K cases
- Cache hit rate

---


## 12. Future Extensions (Optional)

- Human-in-the-loop review for ambiguous cases
- Use LLM-labeled data to fine-tune later (if resources allow)
- Trend analysis & scam evolution tracking

---

## 13. Summary

This design:
- Requires **no labeled data**
- Requires **no GPUs**
- Scales to **10K+ cases**
- Aligns naturally with **FTC taxonomy**
- Is cheap, fast, and maintainable

This is the recommended production architecture under current constraints.

