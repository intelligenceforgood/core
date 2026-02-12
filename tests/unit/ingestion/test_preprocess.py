"""Tests for i4g.ingestion.preprocess — text cleaning and chunking utilities."""

from __future__ import annotations

import pytest

from i4g.ingestion.preprocess import chunk_text, clean_text, prepare_documents


# ---------------------------------------------------------------------------
# clean_text
# ---------------------------------------------------------------------------


class TestCleanText:
    def test_removes_newlines(self):
        assert clean_text("hello\nworld\r\nfoo") == "hello world foo"

    def test_removes_emojis_and_non_ascii(self):
        # Non-ASCII chars are removed, then whitespace is collapsed
        assert clean_text("hello 😂 world 🔥") == "hello world"

    def test_collapses_whitespace(self):
        assert clean_text("hello    world") == "hello world"

    def test_strips_leading_trailing(self):
        assert clean_text("  hello world  ") == "hello world"

    def test_empty_string(self):
        assert clean_text("") == ""

    def test_only_non_ascii(self):
        assert clean_text("😂🔥💯") == ""


# ---------------------------------------------------------------------------
# chunk_text
# ---------------------------------------------------------------------------


class TestChunkText:
    def test_short_text_single_chunk(self):
        text = "one two three"
        chunks = chunk_text(text, chunk_size=500)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_splits_at_chunk_boundary(self):
        words = ["word"] * 10
        text = " ".join(words)
        chunks = chunk_text(text, chunk_size=5)
        assert len(chunks) == 2
        assert chunks[0] == " ".join(["word"] * 5)
        assert chunks[1] == " ".join(["word"] * 5)

    def test_empty_text(self):
        assert chunk_text("") == []

    def test_chunk_size_larger_than_text(self):
        chunks = chunk_text("short", chunk_size=1000)
        assert len(chunks) == 1

    def test_exact_chunk_boundary(self):
        words = ["w"] * 6
        text = " ".join(words)
        chunks = chunk_text(text, chunk_size=3)
        assert len(chunks) == 2


# ---------------------------------------------------------------------------
# prepare_documents
# ---------------------------------------------------------------------------


class TestPrepareDocuments:
    def test_basic_document_preparation(self):
        ocr_results = [{"file": "a.png", "text": "Hello world from OCR."}]
        docs = prepare_documents(ocr_results)
        assert len(docs) >= 1
        assert docs[0]["source"] == "a.png"
        assert "Hello" in docs[0]["content"]

    def test_empty_text_documents_skipped(self):
        ocr_results = [{"file": "blank.png", "text": ""}]
        docs = prepare_documents(ocr_results)
        assert len(docs) == 0

    def test_non_ascii_cleaned(self):
        ocr_results = [{"file": "emoji.png", "text": "Hello 😂 world"}]
        docs = prepare_documents(ocr_results)
        # Non-ASCII is cleaned, but "Hello world" remains
        assert len(docs) >= 1
        assert "Hello" in docs[0]["content"]

    def test_multiple_documents(self):
        ocr_results = [
            {"file": "a.png", "text": "First document"},
            {"file": "b.png", "text": "Second document"},
        ]
        docs = prepare_documents(ocr_results)
        sources = [d["source"] for d in docs]
        assert "a.png" in sources
        assert "b.png" in sources

    def test_long_text_produces_multiple_chunks(self):
        long_text = " ".join(["word"] * 1200)
        ocr_results = [{"file": "long.png", "text": long_text}]
        docs = prepare_documents(ocr_results)
        assert len(docs) > 1
        for doc in docs:
            assert doc["source"] == "long.png"
