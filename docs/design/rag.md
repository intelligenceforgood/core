# RAG Pipeline Architecture

> **Status**: Active (v1.1)
> **Last Updated**: February 8, 2026

This document describes the Retrieval-Augmented Generation (RAG) pipeline used for scam detection and analysis within the I4G platform.

## Overview

The RAG pipeline is designed to assist analysts by automatically evaluating case context against a knowledge base of known scam patterns. It uses a modular architecture based on **LangChain** (v0.2+) and **LangChain Expression Language (LCEL)**.

## Architecture

```mermaid
flowchart LR
    Query[User Query/Context] --> Retriever[Hybrid Retriever]
    Retriever -->|Retrieve Docs| VectorStore[Vector Store]
    VectorStore -->|Relevant Chunks| Context[Context Window]
    Query --> Prompt[Prompt Template]
    Context --> Prompt
    Prompt --> LLM[LLM (Gemini/Ollama)]
    LLM --> Output[Scam Assessment]
```

### Components

1.  **Retriever**:
    *   Uses the `HybridRetriever` (or direct Vector Store access) to fetch relevant documents.
    *   **Search Strategy**: Similarity search (k=4 default).
    *   **Source**: `source_documents` chunks stored in Vertex AI Search (Cloud) or Chroma (Local).

2.  **LLM (Reasoning Engine)**:
    *   **Cloud**: Vertex AI Gemini 2.5 Flash (also used by `classification_sweeper`).
    *   **Local**: Ollama (running `llama3.1` or similar).
    *   **Configuration**: Controlled via `settings.llm.provider`. Note: `pipeline.py` currently hardcodes Ollama (`ChatOllama`). The multi-provider switch is fully implemented in `classifier.py` (Vertex AI, Ollama, mock) but not yet wired into the RAG pipeline.

3.  **Prompt Engineering**:
    *   The system uses a focused prompt template designed to detect crypto and romance scams targeting seniors.
    *   **Template**:
        ```text
        You are a scam detection assistant.
        Given the following chat or message context, decide if it shows signs of a scam.
        Focus on crypto and romance scams targeting seniors.

        Context: {context}

        Question: {question}

        Answer clearly and concisely:
        ```

4.  **Pipeline Construction (LCEL)**:
    *   The pipeline is built using `RunnablePassthrough` for parallel context retrieval and question passing.
    *   Source: `src/i4g/rag/pipeline.py`.

## Usage

The pipeline is exposed via the `build_scam_detection_chain` factory function.

```python
from i4g.rag.pipeline import build_scam_detection_chain
from i4g.store.vector import get_vector_store

vector_store = get_vector_store()
chain = build_scam_detection_chain(vector_store)

result = chain.invoke({"question": "Is this investment platform legit?"})
print(result)
```

## Future Improvements

*   **Guardrails**: Implement output parsers to enforce structured JSON responses (e.g., `{"is_scam": boolean, "confidence": float, "reasoning": str}`).
*   **Few-Shot Learning**: Inject examples of known scams into the prompt context.
*   **Citation**: Require the LLM to cite specific evidence chunks used in the assessment.
