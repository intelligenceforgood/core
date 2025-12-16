"""Index-building helpers previously under scripts/build_index.py."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from i4g.ingestion.preprocess import prepare_documents
from i4g.store.vector import VectorStore


def build_ids(sources: List[str]) -> List[str]:
    """Generate deterministic IDs for source chunks."""

    counts: dict[str, int] = {}
    ids: list[str] = []
    for src in sources:
        counts[src] = counts.get(src, 0) + 1
        ids.append(f"{src}::chunk{counts[src]}")
    return ids


def build_index(args: object) -> int:
    """Build a local vector index from OCR output."""

    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"OCR output not found at {input_path}. Run i4g extract ocr first.")

    ocr_results = json.loads(input_path.read_text(encoding="utf-8"))

    docs = prepare_documents(ocr_results)
    if not docs:
        print("⚠️ No OCR documents available. Nothing to index.")
        return 0

    texts = [d["content"] for d in docs]
    sources = [d["source"] for d in docs]
    metadatas = [{"source": src} for src in sources]
    ids = build_ids(sources)

    store = VectorStore(
        backend=args.backend,
        persist_dir=args.persist_dir,
        embedding_model=args.model,
        reset=args.reset,
    )
    store.add_texts(texts, metadatas=metadatas, ids=ids)
    store.persist()

    print(f"✅ {args.backend.upper()} index built and saved to {store.persist_dir}.")
    return 0


__all__ = ["build_index"]
