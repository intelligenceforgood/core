"""Tests for i4g.embedding.embedder — embedding generation via Ollama."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestGetEmbedder:
    @patch("i4g.embedding.embedder.OllamaEmbeddings")
    def test_returns_ollama_instance(self, mock_cls):
        from i4g.embedding.embedder import get_embedder

        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        result = get_embedder()
        mock_cls.assert_called_once_with(model="mxbai-embed-large")
        assert result is mock_instance

    @patch("i4g.embedding.embedder.OllamaEmbeddings")
    def test_custom_model_name(self, mock_cls):
        from i4g.embedding.embedder import get_embedder

        get_embedder(model_name="all-minilm")
        mock_cls.assert_called_once_with(model="all-minilm")


class TestEmbedDocuments:
    def test_calls_embed_documents_on_embedder(self):
        from i4g.embedding.embedder import embed_documents

        mock_embedder = MagicMock()
        mock_embedder.embed_documents.return_value = [[0.1, 0.2], [0.3, 0.4]]

        texts = ["hello", "world"]
        result = embed_documents(mock_embedder, texts)

        mock_embedder.embed_documents.assert_called_once_with(texts)
        assert result == [[0.1, 0.2], [0.3, 0.4]]

    def test_empty_list(self):
        from i4g.embedding.embedder import embed_documents

        mock_embedder = MagicMock()
        mock_embedder.embed_documents.return_value = []

        result = embed_documents(mock_embedder, [])
        assert result == []
