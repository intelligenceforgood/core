"""Tests for i4g.extraction.chunking — text chunking for large documents."""

from __future__ import annotations

from i4g.extraction.chunking import chunk_text


class TestChunkTextSmall:
    """Short texts should return a single chunk."""

    def test_short_text_single_chunk(self):
        text = "Short text."
        chunks = chunk_text(text)
        assert len(chunks) == 1
        assert chunks[0].text == text
        assert chunks[0].offset == 0

    def test_empty_text_single_chunk(self):
        chunks = chunk_text("")
        assert len(chunks) == 1
        assert chunks[0].text == ""


class TestChunkTextLarge:
    """Texts exceeding max_chars should be split."""

    def test_paragraph_split(self):
        para1 = "A" * 100
        para2 = "B" * 100
        text = para1 + "\n\n" + para2
        chunks = chunk_text(text, max_chars=150)
        assert len(chunks) >= 2
        # Both paragraphs should be covered.
        all_text = " ".join(c.text for c in chunks)
        assert "A" * 50 in all_text
        assert "B" * 50 in all_text

    def test_email_boundary_split(self):
        msg1 = "First message content here with details about the scam.\n"
        boundary = "--- Original Message ---\n"
        msg2 = "Earlier email content about the case.\n"
        text = msg1 + boundary + msg2
        chunks = chunk_text(text, max_chars=60)
        assert len(chunks) >= 2

    def test_hard_split_no_newlines(self):
        # Dense text with no natural break points.
        text = "X" * 500
        chunks = chunk_text(text, max_chars=200, overlap=20)
        assert len(chunks) >= 2
        # All chars should be covered.
        for chunk in chunks:
            assert len(chunk.text) <= 200

    def test_offset_tracking(self):
        text = "Part one.\n\nPart two.\n\nPart three."
        chunks = chunk_text(text, max_chars=15, overlap=0)
        assert len(chunks) >= 2
        # First chunk should start at offset 0.
        assert chunks[0].offset == 0

    def test_overlap_included(self):
        para1 = "A" * 200
        para2 = "B" * 200
        text = para1 + "\n\n" + para2
        chunks = chunk_text(text, max_chars=250, overlap=50)
        assert len(chunks) >= 2
        # Second chunk should contain some overlap from first.
        if len(chunks) > 1:
            assert chunks[1].offset < len(para1) + 2  # Overlap pulls offset back

    def test_no_empty_chunks(self):
        text = "Hello\n\n\n\nWorld\n\n\n\nTest"
        chunks = chunk_text(text, max_chars=10, overlap=0)
        for chunk in chunks:
            assert chunk.text.strip() != ""


class TestChunkTextEmailThread:
    """Real-world email thread patterns."""

    def test_forwarded_message_split(self):
        text = (
            "Subject: Fraud Report\n"
            "Victim reports losing $5000 to scam.\n"
            "--- Forwarded Message ---\n"
            "Original scam email content here.\n"
        )
        chunks = chunk_text(text, max_chars=50)
        assert len(chunks) >= 2

    def test_on_wrote_split(self):
        text = "I agree this is suspicious.\n" "On Mon, Jan 1, 2026, Alice wrote:\n" "Can you look into this for me?\n"
        chunks = chunk_text(text, max_chars=50)
        assert len(chunks) >= 2
