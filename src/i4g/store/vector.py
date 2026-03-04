"""Vector storage and retrieval for i4g.

Supports pluggable backends so developers can toggle between Chroma (default)
for lightweight local prototyping and FAISS for larger-scale or offline search.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_chroma import Chroma
from langchain_community.vectorstores import FAISS
from langchain_ollama import OllamaEmbeddings

from i4g.settings import get_settings
from i4g.store.schema import ScamRecord


def _default_backend() -> str:
    """Return the configured vector backend or fall back to Chroma."""
    backend = get_settings().vector.backend.lower()
    if backend not in {"chroma", "faiss", "vertex_ai"}:
        return "chroma"
    return backend


def _sanitize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Ensure metadata is JSON-safe for vector backends."""
    sanitized: dict[str, Any] = {}
    if not metadata:
        return sanitized
    for key, value in metadata.items():
        if isinstance(value, (dict, list)):
            sanitized[key] = json.dumps(value)
        elif value is None or isinstance(value, (str, int, float, bool)):
            sanitized[key] = value
        else:
            sanitized[key] = str(value)
    return sanitized


class _ChromaBackend:
    """Wrapper around Chroma vector store."""

    def __init__(self, persist_dir: str, embeddings: OllamaEmbeddings, collection_name: str) -> None:
        os.makedirs(persist_dir, exist_ok=True)
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self.store = Chroma(
            collection_name=collection_name,
            embedding_function=embeddings,
            persist_directory=persist_dir,
        )

    def add_texts(
        self,
        texts: Sequence[str],
        metadatas: Sequence[dict[str, Any]],
        ids: Sequence[str],
    ) -> list[str]:
        self.store.add_texts(texts=texts, metadatas=metadatas, ids=ids)
        self.persist()
        return list(ids)

    def similarity_search_with_score(self, query_text: str, top_k: int):
        return self.store.similarity_search_with_score(query_text, k=top_k)

    def delete(self, ids: Sequence[str]) -> bool:
        self.store.delete(ids=list(ids))
        self.persist()
        return True

    def list_collections(self) -> list[str]:
        return [self.collection_name]

    def count(self) -> int:
        try:
            return self.store._collection.count()
        except Exception:
            return 0

    def persist(self) -> None:
        if hasattr(self.store, "persist"):
            self.store.persist()

    def as_retriever(self, search_kwargs: dict[str, Any] | None = None):
        return self.store.as_retriever(search_kwargs=search_kwargs)


class _FaissBackend:
    """Wrapper around FAISS vector store for LangChain."""

    def __init__(self, persist_dir: str, embeddings: OllamaEmbeddings) -> None:
        self.persist_dir = Path(persist_dir)
        self.embeddings = embeddings
        self.store: FAISS | None = None

        os.makedirs(self.persist_dir, exist_ok=True)
        self._load_if_available()

    def _load_if_available(self) -> None:
        index_file = self.persist_dir / "index.faiss"
        if index_file.exists():
            self.store = FAISS.load_local(
                folder_path=str(self.persist_dir),
                embeddings=self.embeddings,
                allow_dangerous_deserialization=True,
            )

    def add_texts(
        self,
        texts: Sequence[str],
        metadatas: Sequence[dict[str, Any]],
        ids: Sequence[str],
    ) -> list[str]:
        if not texts:
            return []
        if self.store is None:
            self.store = FAISS.from_texts(
                texts=list(texts),
                embedding=self.embeddings,
                metadatas=list(metadatas),
                ids=list(ids),
            )
        else:
            self.store.add_texts(texts=list(texts), metadatas=list(metadatas), ids=list(ids))
        self.persist()
        return list(ids)

    def similarity_search_with_score(self, query_text: str, top_k: int):
        if not self.store:
            return []
        return self.store.similarity_search_with_score(query_text, k=top_k)

    def delete(self, ids: Sequence[str]) -> bool:
        if not self.store:
            return False
        self.store.delete(ids=list(ids))
        self.persist()
        return True

    def list_collections(self) -> list[str]:
        return ["faiss_index"]

    def count(self) -> int:
        if not self.store:
            return 0
        return getattr(self.store.index, "ntotal", 0)

    def persist(self) -> None:
        if self.store:
            self.store.save_local(str(self.persist_dir))

    def as_retriever(self, search_kwargs: dict[str, Any] | None = None):
        if not self.store:
            raise ValueError("FAISS store is empty; add documents before creating a retriever.")
        return self.store.as_retriever(search_kwargs=search_kwargs)


class VectorStore:
    """Abstraction layer for vector storage and retrieval."""

    def __init__(
        self,
        persist_dir: str | None = None,
        embedding_model: str | None = None,
        backend: str | None = None,
        collection_name: str | None = None,
        reset: bool = False,
    ) -> None:
        """Initialize the vector store.

        Args:
            persist_dir: Directory where the backend persists data.
            embedding_model: Model name used for embedding generation.
            backend: "chroma" (default) or "faiss". Overrides env if provided.
            collection_name: Chroma collection name (ignored for FAISS).
            reset: If True, remove any existing persisted data before init.
        """
        settings = get_settings()
        backend_name = (backend or _default_backend()).lower()
        if backend_name not in {"chroma", "faiss", "vertex_ai"}:
            raise ValueError(f"Unsupported vector backend '{backend_name}'")

        resolved_model = embedding_model or settings.vector.embedding_model
        resolved_collection = collection_name or settings.vector.collection

        self.backend_name = backend_name
        self.embedding_model_name = resolved_model

        # Only initialize Ollama embeddings if using a local backend
        if backend_name in {"chroma", "faiss"}:
            self.embeddings = OllamaEmbeddings(model=resolved_model)
        else:
            self.embeddings = None

        default_dir = str(settings.vector.chroma_dir) if backend_name == "chroma" else str(settings.vector.faiss_dir)
        self.persist_dir = persist_dir or default_dir

        if reset:
            shutil.rmtree(self.persist_dir, ignore_errors=True)

        if backend_name == "chroma":
            self._backend = _ChromaBackend(self.persist_dir, self.embeddings, resolved_collection)
        elif backend_name == "vertex_ai":
            from i4g.store.vertex_vector import _VertexAIBackend

            self._backend = _VertexAIBackend(
                project_id=settings.vector.vertex_ai_project,
                location=settings.vector.vertex_ai_location,
                data_store_id=settings.vector.vertex_ai_data_store,
                branch_id=settings.vector.vertex_ai_branch,
            )
        else:
            self._backend = _FaissBackend(self.persist_dir, self.embeddings)

    # ------------------------------------------------------------------
    # Core CRUD methods
    # ------------------------------------------------------------------

    def add_records(self, records: Sequence[ScamRecord]) -> list[str]:
        """Add ScamRecord objects and their embeddings to the vector store."""
        if not records:
            return []

        texts: list[str] = []
        metadatas: list[dict[str, Any]] = []
        ids: list[str] = []

        for record in records:
            texts.append(record.text)
            metadatas.append(_sanitize_metadata(record.to_dict()))
            ids.append(record.case_id or str(uuid4()))

        return self.add_texts(texts, metadatas=metadatas, ids=ids)

    def add_texts(
        self,
        texts: Sequence[str],
        metadatas: Sequence[dict[str, Any] | None] | None = None,
        ids: Sequence[str] | None = None,
    ) -> list[str]:
        """Add raw texts with metadata (used by CLI tooling)."""
        if not texts:
            return []

        ids = list(ids) if ids is not None else [str(uuid4()) for _ in texts]
        if len(ids) != len(texts):
            raise ValueError("Length of ids must match length of texts")

        metadatas = list(metadatas) if metadatas is not None else [{} for _ in texts]
        if len(metadatas) != len(texts):
            raise ValueError("Length of metadatas must match length of texts")

        sanitized = [_sanitize_metadata(meta) for meta in metadatas]

        # Truncate texts to avoid context length errors.
        # Some models (e.g. mxbai-embed-large) have small context windows (512 tokens).
        # Using 1000 chars as a safe upper bound (approx 250 tokens).
        truncated_texts = [t[:1000] for t in texts]

        return self._backend.add_texts(texts=truncated_texts, metadatas=sanitized, ids=ids)

    def query_similar(self, query_text: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Perform semantic similarity search."""
        results = self._backend.similarity_search_with_score(query_text, top_k)
        formatted: list[dict[str, Any]] = []
        for doc, score in results:
            meta = doc.metadata or {}

            entities_raw = meta.get("entities")
            entities: dict[str, Any] = {}
            if isinstance(entities_raw, str):
                try:
                    parsed = json.loads(entities_raw)
                    if isinstance(parsed, dict):
                        entities = parsed
                except Exception:
                    entities = {}
            elif isinstance(entities_raw, dict):
                entities = entities_raw

            metadata_raw = meta.get("metadata")
            metadata = metadata_raw
            if isinstance(metadata_raw, str):
                try:
                    metadata = json.loads(metadata_raw)
                except Exception:
                    metadata = metadata_raw

            confidence = meta.get("confidence")
            try:
                confidence_value = float(confidence) if confidence is not None else None
            except (TypeError, ValueError):
                confidence_value = confidence

            formatted.append(
                {
                    "case_id": meta.get("case_id"),
                    "score": float(score),
                    "distance": float(score),
                    "classification": meta.get("classification"),
                    "confidence": confidence_value,
                    "text": doc.page_content,
                    "entities": entities,
                    "metadata": metadata,
                }
            )

        return formatted

    def delete_record(self, case_id: str) -> bool:
        """Delete a record by ID from the vector store."""
        try:
            return self._backend.delete([case_id])
        except Exception:
            return False

    def list_collections(self) -> list[str]:
        """Return list of available vector collections or indexes."""
        return self._backend.list_collections()

    def count(self) -> int:
        """Return the number of stored embeddings."""
        return self._backend.count()

    def as_retriever(self, search_kwargs: dict[str, Any] | None = None):
        """Return a retriever object for the vector store."""
        return self._backend.as_retriever(search_kwargs=search_kwargs)

    def persist(self) -> None:
        """Flush backend state to disk (a no-op for Chroma which auto-persists)."""
        self._backend.persist()
