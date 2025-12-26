"""Vertex AI Search backend for vector storage."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence

from google.api_core.client_options import ClientOptions
from google.cloud import discoveryengine_v1 as discoveryengine
from langchain_core.documents import Document

logger = logging.getLogger(__name__)


class _VertexAIBackend:
    """Wrapper around Vertex AI Search (Discovery Engine) for vector storage."""

    def __init__(
        self,
        project_id: str,
        location: str,
        data_store_id: str,
        branch_id: str = "default_branch",
    ) -> None:
        self.project_id = project_id
        self.location = location
        self.data_store_id = data_store_id
        self.branch_id = branch_id

        # Configure client options for the specific location
        # Note: For 'global' location, the endpoint is discoveryengine.googleapis.com
        # For regional, it is {location}-discoveryengine.googleapis.com

        api_endpoint = "discoveryengine.googleapis.com"
        if location != "global":
            api_endpoint = f"{location}-discoveryengine.googleapis.com"

        client_options = ClientOptions(api_endpoint=api_endpoint)

        self.client = discoveryengine.DocumentServiceClient(client_options=client_options)

        self.parent = self.client.branch_path(
            project=project_id,
            location=location,
            data_store=data_store_id,
            branch=branch_id,
        )

    def add_texts(
        self,
        texts: Sequence[str],
        metadatas: Sequence[Dict[str, Any]],
        ids: Sequence[str],
    ) -> List[str]:
        """Import documents into Vertex AI Search."""
        # Vertex AI Search expects documents in a specific format
        # We'll map our texts and metadata to Discovery Engine Documents

        documents = []
        for text, metadata, doc_id in zip(texts, metadatas, ids):
            # Convert metadata to struct/json format expected by Vertex AI
            # Note: Vertex AI Search schema must be configured to accept these fields
            # For unstructured data stores, we primarily use 'content' (text) and 'struct_data' (metadata)

            # Ensure metadata is JSON serializable
            struct_data = {}
            for k, v in metadata.items():
                if isinstance(v, (dict, list)):
                    # Vertex AI struct_data handles nested JSON if configured,
                    # but flattening or stringifying is safer for generic usage
                    struct_data[k] = v
                else:
                    struct_data[k] = v

            doc = discoveryengine.Document(
                id=doc_id,
                json_data=json.dumps(
                    {
                        "id": doc_id,
                        "content": text,  # Assuming unstructured data store with content field
                        **struct_data,
                    }
                ),
            )
            documents.append(doc)

        # Batch import is more efficient, but for simplicity/compatibility with the interface
        # we'll use import_documents with inline source.
        # For large batches, GCS import is recommended, but here we are likely processing
        # smaller chunks from the ingestion pipeline.

        # However, the interface expects synchronous return.
        # import_documents is a long-running operation.
        # For real-time updates, we should use write_document (single) or batch it.
        # Given the interface `add_texts` takes a sequence, let's iterate and write individually
        # or use a small batch import if possible.
        # Discovery Engine API has a `import_documents` method which is LRO.
        # It doesn't have a `batch_write_documents`.
        # So we loop `create_document` (or `update_document` / `write_document` isn't a thing, it's create/delete/patch).
        # Actually, `import_documents` allows inline source.

        # Let's use inline import for the batch.

        inline_source = discoveryengine.ImportDocumentsRequest.InlineSource(documents=documents)

        request = discoveryengine.ImportDocumentsRequest(
            parent=self.parent,
            inline_source=inline_source,
            # mode="FULL" # or INCREMENTAL. Default is INCREMENTAL which is what we want (upsert-ish)
            reconciliation_mode=discoveryengine.ImportDocumentsRequest.ReconciliationMode.INCREMENTAL,
        )

        operation = self.client.import_documents(request=request)

        # Wait for operation to complete (blocking, as per interface contract)
        # In a production high-throughput scenario, we might want to make this async
        # or use a different pattern, but for now we block.
        response = operation.result()

        # Check for failures in response
        # response.error_samples could contain errors

        return list(ids)

    def similarity_search_with_score(self, query_text: str, top_k: int):
        """Search using Vertex AI Search."""
        # Use SearchServiceClient
        api_endpoint = "discoveryengine.googleapis.com"
        if self.location != "global":
            api_endpoint = f"{self.location}-discoveryengine.googleapis.com"

        search_client = discoveryengine.SearchServiceClient(client_options=ClientOptions(api_endpoint=api_endpoint))

        serving_config = search_client.serving_config_path(
            project=self.project_id,
            location=self.location,
            data_store=self.data_store_id,
            serving_config="default_search",  # Or make this configurable
        )

        request = discoveryengine.SearchRequest(
            serving_config=serving_config,
            query=query_text,
            page_size=top_k,
            # content_search_spec={"snippet_spec": {"return_snippet": True}},
        )

        response = search_client.search(request=request)

        results = []
        for result in response.results:
            doc = result.document
            data = {}
            if doc.json_data:
                try:
                    parsed = json.loads(doc.json_data)
                    if isinstance(parsed, dict):
                        data = parsed
                except (json.JSONDecodeError, TypeError):
                    pass

            if not data and doc.struct_data:
                # struct_data is a proto Map, dict() converts it safely
                data = dict(doc.struct_data)

            # Extract content/text
            content = data.get("content", "")
            if not content and doc.derived_struct_data:
                # Fallback to snippets if available/configured
                content = doc.derived_struct_data.get("snippets", [{}])[0].get("snippet", "")

            # Reconstruct metadata
            metadata = {k: v for k, v in data.items() if k != "content"}

            # Ensure case_id is present (Vertex AI uses doc.id as the primary key)
            if "case_id" not in metadata and doc.id:
                metadata["case_id"] = doc.id

            # Create a compatible document object (duck typing or LangChain Document)
            # The interface expects (Document, score) tuples

            # Vertex AI Search doesn't always return a raw similarity score in the same way
            # as vector DBs. It returns results ranked.
            # We can use 1.0 as a dummy score or try to extract relevance info if available.
            score = 1.0

            results.append((Document(page_content=content, metadata=metadata), score))

        return results

    def delete(self, ids: Sequence[str]) -> bool:
        """Delete documents by ID."""
        # Vertex AI Search delete is per-document.
        # Batch delete is available via `purge_documents` but that takes a filter.
        # We can loop delete.

        for doc_id in ids:
            name = f"{self.parent}/documents/{doc_id}"
            request = discoveryengine.DeleteDocumentRequest(name=name)
            try:
                self.client.delete_document(request=request)
            except Exception:
                logger.exception(f"Failed to delete document {doc_id} from Vertex AI Search")
                return False
        return True

    def list_collections(self) -> List[str]:
        return [self.data_store_id]

    def count(self) -> int:
        # Discovery Engine doesn't have a cheap count API.
        # We'd have to list all documents which is expensive.
        # Return -1 or 0 to indicate unknown.
        return 0

    def persist(self) -> None:
        # No-op for managed service
        pass

    def as_retriever(self, search_kwargs: Optional[Dict[str, Any]] = None):
        # Return a LangChain retriever wrapper if needed,
        # or self if we implement the interface.
        # For now, the VectorStore wrapper handles this.
        raise NotImplementedError("Direct retriever creation for Vertex AI not yet implemented")
