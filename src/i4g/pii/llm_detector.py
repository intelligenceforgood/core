"""LLM-assisted PII detection for contextual patterns.

The hybrid tokenization pipeline runs regex detectors first (cheap, fast).
When text remains that could contain *contextual* PII — patterns too nuanced
for regex (e.g. "my social is nine one two …", "born on the fourth of July
nineteen ninety") — this module sends a targeted LLM prompt to extract them.

**Provider routing:**
- ``local`` / ``mock``:  Ollama (or skip if mock)
- ``dev`` / ``prod``:    Vertex AI (Gemini)

The provider is selected automatically via ``settings.llm.provider``.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import ClassVar

from i4g.pii.detectors import PiiMatch
from i4g.settings import Settings, get_settings

LOGGER = logging.getLogger(__name__)

# Module-level circuit breaker: once the LLM call fails, stop retrying for
# the remainder of the process lifetime.  This avoids hammering a broken
# Ollama/Vertex endpoint once per ingested case.
_circuit_open = False
_circuit_lock = threading.Lock()

# Prompt that instructs the LLM to return structured JSON with any PII it finds
# that might not be caught by simple regex.
_DETECTION_PROMPT = """\
You are a PII detection assistant. Analyse the following text and identify any \
personally identifiable information (PII) that may be expressed in natural \
language rather than in a standard format. Examples:

- "my social security number is nine one two thirty four five six seven eight"
- "I was born on the fourth of July, 1990"
- "call me at five five five oh one hundred"
- "I live at one twenty-three Main Street"

Return ONLY a JSON array (no markdown fences). Each element must be an object \
with these fields:
  "value"  — the PII value normalised to its canonical form (digits for SSN, \
E.164 for phone, ISO date for DOB, etc.)
  "raw"    — the exact substring as it appeared in the text
  "type"   — one of: "ssn", "phone", "credit_card", "dob", "address", "email", "name"

If no contextual PII is found, return an empty array: []

TEXT:
{text}
"""


@dataclass
class LlmPiiDetector:
    """Detect contextual PII using an LLM call.

    The detector is deliberately lightweight: it receives only the *residual*
    text (spans not already claimed by regex detectors) so that LLM cost stays
    low.

    Attributes:
        settings: Application settings (controls provider selection).
    """

    settings: Settings = field(default_factory=get_settings)
    _llm_client: object | None = field(default=None, init=False, repr=False)

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def detect(self, text: str, *, already_detected_spans: list[tuple[int, int]] | None = None) -> list[PiiMatch]:
        """Return contextual PII matches found by the LLM.

        Args:
            text: Full original text.
            already_detected_spans: ``(start, end)`` pairs already claimed by
                regex detectors. The detector builds a *residual* string
                masking those spans so the LLM doesn't re-detect them.

        Returns:
            A list of ``PiiMatch`` objects with ``detector="llm"``.
        """
        global _circuit_open  # noqa: PLW0603

        provider = self.settings.llm.provider
        if provider == "mock":
            LOGGER.debug("LLM PII detection skipped (mock provider).")
            return []

        # Circuit breaker: if a previous call failed, skip silently.
        if _circuit_open:
            return []

        residual = self._build_residual(text, already_detected_spans or [])
        if not residual or not residual.strip():
            return []

        try:
            raw_response = self._call_llm(residual)
        except Exception:
            with _circuit_lock:
                if not _circuit_open:
                    LOGGER.warning(
                        "LLM PII detection failed (provider=%s); disabling for remaining cases. "
                        "Regex-only PII detection will continue.",
                        provider,
                    )
                    _circuit_open = True
            return []

        return self._parse_response(raw_response, text)

    # -----------------------------------------------------------------
    # LLM interaction
    # -----------------------------------------------------------------

    def _get_llm_client(self) -> object:
        """Lazy-initialise and cache the ``LLMClient``."""
        if self._llm_client is None:
            from i4g.llm.client import build_llm_client

            self._llm_client = build_llm_client(settings=self.settings)
        return self._llm_client

    def _call_llm(self, residual_text: str) -> str:
        """Send the detection prompt and return the raw response string."""
        prompt = _DETECTION_PROMPT.format(text=residual_text)
        client = self._get_llm_client()
        return client.generate(prompt)

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _build_residual(text: str, spans: list[tuple[int, int]]) -> str:
        """Replace already-detected spans with whitespace to avoid re-detection."""
        chars = list(text)
        for start, end in spans:
            for i in range(start, min(end, len(chars))):
                chars[i] = " "
        return "".join(chars)

    _TYPE_TO_PREFIX: ClassVar[dict[str, str]] = {
        "ssn": "TIN",
        "phone": "PHN",
        "credit_card": "CCN",
        "dob": "DOB",
        "address": "ADR",
        "email": "EID",
        "name": "NAM",
    }

    def _parse_response(self, raw: str, original_text: str) -> list[PiiMatch]:
        """Parse the LLM JSON response into ``PiiMatch`` objects."""
        # Strip markdown code fences if the LLM ignores instructions
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        cleaned = re.sub(r"```\s*$", "", cleaned).strip()

        try:
            items = json.loads(cleaned)
        except json.JSONDecodeError:
            LOGGER.warning("LLM returned non-JSON response; discarding. First 200 chars: %s", raw[:200])
            return []

        if not isinstance(items, list):
            LOGGER.warning("LLM returned non-array JSON; discarding.")
            return []

        matches: list[PiiMatch] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            pii_type = item.get("type", "").lower()
            prefix = self._TYPE_TO_PREFIX.get(pii_type)
            if not prefix:
                continue
            value = item.get("value", "")
            raw_text = item.get("raw", "")
            if not value:
                continue

            # Try to locate the raw substring in original text for span info
            start = original_text.find(raw_text) if raw_text else -1
            end = start + len(raw_text) if start >= 0 else -1

            matches.append(
                PiiMatch(
                    value=value,
                    prefix=prefix,
                    start=max(start, 0),
                    end=max(end, 0),
                    detector="llm",
                    confidence=0.7,  # LLM detections get lower default confidence
                )
            )

        return matches


__all__ = ["LlmPiiDetector", "reset_circuit_breaker"]


def reset_circuit_breaker() -> None:
    """Reset the module-level circuit breaker (for tests)."""
    global _circuit_open  # noqa: PLW0603
    with _circuit_lock:
        _circuit_open = False
