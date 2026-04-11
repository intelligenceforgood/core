"""Language detection and routing for multi-language extraction.

Non-English scam texts get routed to the LLM module with language-aware
prompts.  Technical extractors (regex) continue to work regardless of
language since patterns like wallet addresses and emails are language-agnostic.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Minimum text length to attempt detection — shorter texts are unreliable.
_MIN_DETECT_LENGTH = 20


def detect_language(text: str) -> str:
    """Detect the primary language of *text*.

    Args:
        text: Input text.

    Returns:
        ISO 639-1 language code (e.g. ``"en"``, ``"zh-cn"``, ``"es"``).
        Returns ``"en"`` if detection fails or text is too short.
    """
    if len(text.strip()) < _MIN_DETECT_LENGTH:
        return "en"

    try:
        from langdetect import detect

        return detect(text)
    except Exception:
        logger.debug("Language detection failed; defaulting to 'en'", exc_info=True)
        return "en"


def build_language_hint(lang_code: str) -> str:
    """Return a prompt hint for the LLM when text is non-English.

    Args:
        lang_code: ISO 639-1 code from :func:`detect_language`.

    Returns:
        A string to prepend to the LLM extraction prompt, or empty
        string if the text is English.
    """
    if lang_code.startswith("en"):
        return ""

    lang_name = _LANGUAGE_NAMES.get(lang_code, lang_code.upper())
    return (
        f"IMPORTANT: The following text is in {lang_name}. "
        f"Extract entities in their original language form, but normalize "
        f"technical identifiers (wallets, emails, URLs) to standard format. "
        f"Translate person/organization names to their most common English "
        f"transliteration if applicable.\n\n"
    )


_LANGUAGE_NAMES: dict[str, str] = {
    "zh-cn": "Chinese (Simplified)",
    "zh-tw": "Chinese (Traditional)",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "ja": "Japanese",
    "ko": "Korean",
    "pt": "Portuguese",
    "ru": "Russian",
    "ar": "Arabic",
    "hi": "Hindi",
    "th": "Thai",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "ms": "Malay",
    "tl": "Filipino",
    "tr": "Turkish",
}
