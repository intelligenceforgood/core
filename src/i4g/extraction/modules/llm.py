"""LLM-based extraction module.

Wraps the prompt construction, LLM invocation, and JSON parsing from
``semantic_ner.py`` and ``entity_extract.py`` behind the ``ModuleProtocol``
interface.  Supports both Ollama and Vertex AI via the ``LLMClient``
abstraction from ``i4g.llm.client``.
"""

from __future__ import annotations

import json
import logging
import re

from i4g.extraction.language import build_language_hint, detect_language
from i4g.extraction.types import ScoredEntity
from i4g.llm.client import LLMClient
from i4g.utils.entity_types import normalize_entity_type, normalize_entity_value

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Authority declarations — LLM is the primary source for semantic types.
# ---------------------------------------------------------------------------

_AUTHORITY: dict[str, float] = {
    "person": 0.8,
    "organization": 0.8,
    "scam_indicator": 0.8,
    "wallet_address": 0.7,
    "email_address": 0.7,
    "phone_number": 0.7,
    "url": 0.7,
    "bank_account": 0.7,
    "social_handle": 0.7,
    "location": 0.7,
    "crypto_token": 0.7,
    "domain": 0.7,
}

_LLM_DEFAULT_CONFIDENCE = 0.7

_ENTITY_KEYS = [
    "people",
    "organizations",
    "wallet_addresses",
    "bank_accounts",
    "email_addresses",
    "phone_numbers",
    "urls",
    "domains",
    "social_handles",
    "crypto_assets",
    "locations",
    "scam_indicators",
]

_EXTRACTION_PROMPT = """\
You are an assistant whose only job is to extract structured entities from text for \
the purpose of user support and law enforcement investigation. You must NOT provide \
operational advice or anything that enables wrongdoing.

Return ONLY a JSON object with these exact top-level keys:
{keys}

If a field has no values, return an empty list for that field. Do NOT add extra keys.

Field definitions:
- "people": ACTUAL person names only (first + last or full names)
- "organizations": Company, exchange, or institution names
- "wallet_addresses": Cryptocurrency wallet addresses (0x…, bc1…, etc.)
- "bank_accounts": Bank account numbers, routing numbers, IBANs, SWIFT/BIC codes
- "email_addresses": Email addresses
- "phone_numbers": Phone numbers
- "urls": Full URLs (https://…, http://…)
- "domains": Domain names without protocol (example.com)
- "social_handles": Social media usernames (@user, Telegram handles)
- "crypto_assets": Cryptocurrency names/tickers (Bitcoin, USDT, ETH)
- "locations": Geographic locations (cities, countries, addresses)
- "scam_indicators": Short phrases describing suspicious tactics

IMPORTANT — do NOT extract these as people:
- Field labels: "Account Number", "Bank Name", "Routing Number", "Sort Code"
- Scam type names: "Advance Fee", "Money Mule", "Romance Scam"
- Financial terms: "Wire Transfer", "Gift Card", "Credit Card"
- Generic titles: "Customer Service", "Tech Support"

Example Input: "Hi, I'm Anna from TrustWallet. Send 0xAbC... to verify and pay 50 USDT."
Example Output:
{{"people": ["Anna"], "organizations": ["TrustWallet"], "crypto_assets": ["USDT"], \
"wallet_addresses": ["0xAbC..."], "bank_accounts": [], \
"email_addresses": [], "phone_numbers": [], "urls": [], \
"domains": [], "social_handles": [], "locations": [], \
"scam_indicators": ["verification fee", "send to verify"]}}

Example Input: "Contact james@fraud.com or call +1-555-999-0000. Account number 12345678, routing 021000021."
Example Output:
{{"people": [], "organizations": [], "crypto_assets": [], \
"wallet_addresses": [], "bank_accounts": ["12345678", "021000021"], \
"email_addresses": ["james@fraud.com"], \
"phone_numbers": ["+1-555-999-0000"], "urls": [], \
"domains": ["fraud.com"], "social_handles": [], "locations": [], \
"scam_indicators": []}}

Now analyze the following text and return ONLY the JSON object:

{text}
"""

# Maximum characters from input text sent to the LLM.
_MAX_TEXT_LENGTH = 8000


def _parse_entity_response(response_text: str) -> dict[str, list[str]]:
    """Parse LLM response into an entity dict.

    Tries direct JSON parse, markdown block extraction, and regex fallback.

    Args:
        response_text: Raw LLM output.

    Returns:
        Dict mapping entity keys to lists of string values.
    """
    cleaned = response_text.strip()

    # Try direct parse
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if isinstance(v, list)}
    except json.JSONDecodeError:
        pass

    # Extract JSON from markdown blocks
    if "```json" in cleaned:
        start = cleaned.find("```json") + 7
        end = cleaned.find("```", start)
        if end != -1:
            try:
                data = json.loads(cleaned[start:end].strip())
                if isinstance(data, dict):
                    return {k: v for k, v in data.items() if isinstance(v, list)}
            except json.JSONDecodeError:
                pass

    # Regex fallback for JSON object
    m = re.search(r"\{(?:[^{}]|\{[^{}]*\})*\}", cleaned, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if isinstance(v, list)}
        except json.JSONDecodeError:
            pass

    return {}


class LLMModule:
    """LLM-based extraction module.

    Uses the project's ``LLMClient`` abstraction to support Ollama,
    Vertex AI, and mock backends.

    Args:
        llm_client: A ``LLMClient`` instance.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm = llm_client

    @property
    def name(self) -> str:
        return "llm"

    @property
    def authority(self) -> dict[str, float]:
        return _AUTHORITY

    def extract(self, text: str) -> list[ScoredEntity]:
        """Run LLM extraction on *text*.

        Args:
            text: Input text (truncated to ``_MAX_TEXT_LENGTH`` chars).

        Returns:
            List of scored entities.  Returns an empty list if the LLM
            invocation fails.
        """
        truncated = text[:_MAX_TEXT_LENGTH]
        lang_hint = build_language_hint(detect_language(truncated))

        prompt = lang_hint + _EXTRACTION_PROMPT.format(
            keys=", ".join(_ENTITY_KEYS),
            text=truncated,
        )

        try:
            response = self._llm.generate(prompt)
        except Exception:
            logger.warning("LLM entity extraction failed", exc_info=True)
            return []

        parsed = _parse_entity_response(response)
        if not parsed:
            return []

        results: list[ScoredEntity] = []
        for raw_key, values in parsed.items():
            if not isinstance(values, list):
                continue
            entity_type = normalize_entity_type(raw_key)
            for raw_value in values:
                if not raw_value or isinstance(raw_value, dict):
                    continue
                raw_str = str(raw_value)
                if not raw_str.strip():
                    continue
                canonical = normalize_entity_value(entity_type, raw_str)
                results.append(
                    ScoredEntity(
                        entity_type=entity_type,
                        value=raw_str,
                        canonical_value=canonical,
                        confidence=_LLM_DEFAULT_CONFIDENCE,
                        source_module=self.name,
                    )
                )

        return results
