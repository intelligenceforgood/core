import sys
import os
from pathlib import Path

# Add src to path
sys.path.append(str(Path.cwd() / "src"))

from i4g.store.vector import VectorStore
from i4g.settings import get_settings

try:
    store = VectorStore()
    backend = store._backend

    # Get the collection
    collection = backend.store._collection

    # Peek at the first few items
    print("Peeking at collection...")
    data = collection.peek(limit=5)

    embeddings = data.get("embeddings")

    has_embeddings = False
    if embeddings is not None:
        if isinstance(embeddings, list) and len(embeddings) > 0:
            has_embeddings = True
        elif hasattr(embeddings, "size") and embeddings.size > 0:
            has_embeddings = True

    if has_embeddings:
        print(f"Type of embeddings: {type(embeddings)}")
        if len(embeddings) > 0:
            print(f"Type of first embedding: {type(embeddings[0])}")

        import numpy as np

        first = np.array(embeddings[0])
        print(f"First embedding (first 5): {first[:5]}")

        all_same = True
        for i in range(1, len(embeddings)):
            curr = np.array(embeddings[i])
            if not np.array_equal(first, curr):
                all_same = False
                break
        print(f"All 5 embeddings identical? {all_same}")

        all_zeros = np.all(first == 0)
        print(f"Embedding is all zeros? {all_zeros}")

    if documents:
        print(f"First document: '{documents[0]}'")

except Exception as e:
    print(f"Error: {e}")
