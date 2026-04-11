"""Text chunking for large documents.

Email threads and long complaint narratives can exceed LLM context windows.
This module splits text into manageable chunks on natural boundaries
(email headers, paragraph breaks) and provides offset tracking so that
per-chunk entity spans can be mapped back to the full document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Default max chunk size in characters — roughly 6K tokens at ~1.3 chars/token.
_DEFAULT_MAX_CHUNK_CHARS = 8000

# Overlap between adjacent chunks to avoid splitting entities at boundaries.
_DEFAULT_OVERLAP_CHARS = 200

# Patterns that indicate a message boundary in email thread format.
_EMAIL_BOUNDARY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^-{3,}\s*Original Message\s*-{3,}", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^-{3,}\s*Forwarded Message\s*-{3,}", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^On .+wrote:\s*$", re.MULTILINE),
    re.compile(r"^From:\s+.+\nSent:\s+.+\nTo:\s+", re.MULTILINE),
    re.compile(r"^>{2,}\s*", re.MULTILINE),
]


@dataclass(frozen=True, slots=True)
class TextChunk:
    """A slice of a larger text with its position in the original document."""

    text: str
    """The chunk text."""

    offset: int
    """Character offset of this chunk's start in the original document."""


def chunk_text(
    text: str,
    *,
    max_chars: int = _DEFAULT_MAX_CHUNK_CHARS,
    overlap: int = _DEFAULT_OVERLAP_CHARS,
) -> list[TextChunk]:
    """Split *text* into chunks that fit within *max_chars*.

    Splitting strategy (in priority order):

    1. **Email boundaries** — ``"Original Message"``, ``"On ... wrote:"``, etc.
    2. **Paragraph breaks** — double newlines.
    3. **Single newlines** — fallback for dense text.
    4. **Hard split** — last resort at *max_chars*.

    Each chunk after the first includes an *overlap* of characters from the
    preceding chunk to avoid splitting entities at boundaries.

    Args:
        text: Full document text.
        max_chars: Maximum characters per chunk.
        overlap: Characters of overlap between adjacent chunks.

    Returns:
        List of ``TextChunk`` instances covering the full document.
        Returns a single chunk if the text fits within *max_chars*.
    """
    if len(text) <= max_chars:
        return [TextChunk(text=text, offset=0)]

    # Split on email message boundaries first.
    segments = _split_on_email_boundaries(text)

    # If email splitting didn't help (single segment), fall back to paragraphs.
    if len(segments) == 1:
        segments = _split_on_paragraphs(text)

    # Build chunks by packing segments up to max_chars.
    chunks: list[TextChunk] = []
    current_text = ""
    current_offset = 0

    for seg_text, seg_offset in segments:
        if not current_text:
            current_text = seg_text
            current_offset = seg_offset
            continue

        combined_len = len(current_text) + len(seg_text) + 1  # +1 for separator
        if combined_len <= max_chars:
            current_text += "\n" + seg_text
        else:
            # Emit current chunk.
            chunks.append(TextChunk(text=current_text, offset=current_offset))
            # Start new chunk with overlap from the end of the previous.
            if overlap > 0 and len(current_text) > overlap:
                overlap_text = current_text[-overlap:]
                current_text = overlap_text + "\n" + seg_text
                current_offset = seg_offset - overlap
            else:
                current_text = seg_text
                current_offset = seg_offset

    # Emit final chunk.
    if current_text:
        chunks.append(TextChunk(text=current_text, offset=current_offset))

    # Final pass: hard-split any chunks that still exceed max_chars.
    result: list[TextChunk] = []
    for chunk in chunks:
        if len(chunk.text) <= max_chars:
            result.append(chunk)
        else:
            result.extend(_hard_split(chunk, max_chars=max_chars, overlap=overlap))

    return result


def _split_on_email_boundaries(text: str) -> list[tuple[str, int]]:
    """Split text at email thread boundaries.

    Returns:
        List of ``(segment_text, start_offset)`` tuples.
    """
    split_points: set[int] = set()
    for pattern in _EMAIL_BOUNDARY_PATTERNS:
        for m in pattern.finditer(text):
            split_points.add(m.start())

    if not split_points:
        return [(text, 0)]

    points = sorted(split_points)
    segments: list[tuple[str, int]] = []
    prev = 0
    for point in points:
        if point > prev:
            seg = text[prev:point]
            if seg.strip():
                segments.append((seg, prev))
        prev = point

    # Final segment.
    if prev < len(text):
        seg = text[prev:]
        if seg.strip():
            segments.append((seg, prev))

    return segments if segments else [(text, 0)]


def _split_on_paragraphs(text: str) -> list[tuple[str, int]]:
    """Split text on double-newline paragraph breaks.

    Falls back to single-newline splits if paragraphs are too few.
    """
    # Try double newlines first.
    parts = re.split(r"\n\n+", text)
    if len(parts) > 1:
        segments: list[tuple[str, int]] = []
        offset = 0
        for part in parts:
            idx = text.find(part, offset)
            if idx == -1:
                idx = offset
            if part.strip():
                segments.append((part, idx))
            offset = idx + len(part)
        return segments

    # Fall back to single newlines.
    parts = text.split("\n")
    segments = []
    offset = 0
    for part in parts:
        idx = text.find(part, offset)
        if idx == -1:
            idx = offset
        if part.strip():
            segments.append((part, idx))
        offset = idx + len(part)

    return segments if segments else [(text, 0)]


def _hard_split(
    chunk: TextChunk,
    *,
    max_chars: int,
    overlap: int,
) -> list[TextChunk]:
    """Hard-split an oversized chunk into pieces at max_chars boundaries."""
    text = chunk.text
    base_offset = chunk.offset
    pieces: list[TextChunk] = []
    pos = 0

    while pos < len(text):
        end = min(pos + max_chars, len(text))

        # Try to break at a newline within the last 20% of the chunk.
        if end < len(text):
            search_start = max(pos + int(max_chars * 0.8), pos)
            newline = text.rfind("\n", search_start, end)
            if newline > pos:
                end = newline + 1

        pieces.append(TextChunk(text=text[pos:end], offset=base_offset + pos))

        # Advance with overlap.
        pos = end - overlap if overlap < (end - pos) else end

    return pieces
