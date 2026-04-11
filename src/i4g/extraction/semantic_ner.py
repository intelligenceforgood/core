"""
Semantic Named Entity Extraction (chat-style) using a local Ollama LLM via LangChain.

- Uses chat-like System / User framing to reduce LLM refusals.
- Extracts structured entities from scam-related text (crypto, romance, etc.)
- If the model returns non-JSON or refuses, falls back to rule-based extraction (ner_rules).
- Merges results with confidence scoring for future ML calibration.
"""

import json
import re
from typing import Any

from langchain_ollama import OllamaLLM

from i4g.extraction.ner_rules import extract_entities as rule_extract_entities

# ------------------------------
# PROMPTS
# ------------------------------

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
_EMPTY_JSON_OUTPUT_TEMPLATE = json.dumps({key: [] for key in _ENTITY_KEYS}, indent=2)

_SYSTEM_PROMPT = """
You are an assistant whose only job is to *extract structured entities* from text for
the purpose of user support and law enforcement investigation. You must NOT provide
operational advice or anything that enables wrongdoing.

Return ONLY a JSON object with the exact top-level keys listed in the examples.
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
"""

# Few-shot examples for better entity grouping and consistency
_FEW_SHOT_EXAMPLES = [
    {
        "input": "Hi, I'm Anna from TrustWallet. Send 0xAbC... to verify and pay 50 USDT.",
        "output": {
            "people": ["Anna"],
            "organizations": ["TrustWallet"],
            "crypto_assets": ["USDT"],
            "wallet_addresses": ["0xAbC..."],
            "bank_accounts": [],
            "email_addresses": [],
            "phone_numbers": [],
            "urls": [],
            "domains": [],
            "social_handles": [],
            "locations": [],
            "scam_indicators": ["verification fee", "send to verify"],
        },
    },
    {
        "input": "Dear John, I love you. Please send $200 in Bitcoin to 1FzWL... so we can meet soon.",
        "output": {
            "people": ["John"],
            "organizations": [],
            "crypto_assets": ["Bitcoin"],
            "wallet_addresses": ["1FzWL..."],
            "bank_accounts": [],
            "email_addresses": [],
            "phone_numbers": [],
            "urls": [],
            "domains": [],
            "social_handles": [],
            "locations": [],
            "scam_indicators": ["romance scam", "money request to meet"],
        },
    },
    {
        "input": "The New Jersey Devils investment club guarantees double profit. Contact us at @devilsprofit on Telegram.",  # noqa: E501
        "output": {
            "people": [],
            "organizations": ["The New Jersey Devils investment club"],
            "crypto_assets": [],
            "wallet_addresses": [],
            "bank_accounts": [],
            "email_addresses": [],
            "phone_numbers": [],
            "urls": [],
            "domains": [],
            "social_handles": ["@devilsprofit"],
            "locations": ["New Jersey"],
            "scam_indicators": ["investment guarantee"],
        },
    },
    {
        "input": "Contact james@fraud.com or call +1-555-999-0000. Account number 12345678, routing 021000021.",  # noqa: E501
        "output": {
            "people": [],
            "organizations": [],
            "crypto_assets": [],
            "wallet_addresses": [],
            "bank_accounts": ["12345678", "021000021"],
            "email_addresses": ["james@fraud.com"],
            "phone_numbers": ["+1-555-999-0000"],
            "urls": [],
            "domains": ["fraud.com"],
            "social_handles": [],
            "locations": [],
            "scam_indicators": [],
        },
    },
]

_HUMAN_TEMPLATE = """
Text:
{text}

Return a JSON object with these exact fields: {output_template}

Rules:
- Group multi-word names (e.g., "The New Jersey Devils") as a single entity.
- Include exchange names, wallet references, suspicious URLs or usernames.
- "scam_indicators" lists short phrases like "verification fee", "investment guarantee".
- Do NOT include instructions or steps. If you detect explicit solicitation or instruction,
  still extract the entities but do not restate the instructions; instead include the phrase
  in "scam_indicators".
Examples:
{few_shots}

Now analyze the Text above and return only the JSON.
"""


# ------------------------------
# LLM Helper Functions
# ------------------------------


def build_llm(model: str = "llama3.1", base_url: str | None = None) -> OllamaLLM:
    """
    Initialize an OllamaLLM instance.

    Args:
        model: The name of the Ollama model to use (e.g., "llama3.1").
        base_url: The base URL of the Ollama API, if not the default.

    Returns:
        An instance of langchain_ollama.OllamaLLM.
    """
    kwargs = {"model": model}
    if base_url:
        kwargs["base_url"] = base_url
    return OllamaLLM(**kwargs)


def _format_few_shots() -> str:
    """
    Format few-shot examples as human-readable JSON blocks.

    Returns:
        A single string containing all few-shot examples, formatted for
        inclusion in the main prompt.
    """
    formatted = []
    for ex in _FEW_SHOT_EXAMPLES:
        formatted.append(f"Example Input: {ex['input']}\nExample Output:\n{json.dumps(ex['output'], indent=2)}")
    return "\n\n".join(formatted)


def _format_chat_prompt(text: str) -> str:
    """
    Build the complete prompt string for the LLM.

    This function assembles the system prompt, few-shot examples, and the user's
    input text into a single, coherent prompt.

    Args:
        text: The user-provided text to be analyzed.

    Returns:
        The fully formatted prompt string.
    """
    few_shots = _format_few_shots()
    human_prompt = _HUMAN_TEMPLATE.format(text=text, output_template=_EMPTY_JSON_OUTPUT_TEMPLATE, few_shots=few_shots)

    prompt = f"{_SYSTEM_PROMPT.strip()}\n\n{human_prompt.strip()}"
    return prompt


def _safe_parse_json(resp_text: str) -> dict[str, Any]:
    """
    Safely parse a JSON object from a string that may contain other text.

    It first tries to parse the whole string. If that fails, it uses a regex
    to find the first valid JSON object within the string.

    Args:
        resp_text: The string response from the LLM.

    Returns:
        A dictionary parsed from the JSON, or a dictionary with a `raw_output`
        key containing the original text if parsing fails.
    """
    try:
        return json.loads(resp_text)
    except json.JSONDecodeError:
        m = re.search(r"\{(?:[^{}]|\{[^{}]*\})*\}", resp_text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return {"raw_output": resp_text}
        else:
            return {"raw_output": resp_text}


def _merge_results(llm_result: dict[str, Any], rule_result: dict[str, Any]) -> dict[str, Any]:
    """Merge entities from LLM and rule-based results.

    .. deprecated::
        Use :func:`i4g.extraction.extract_entities` instead. This function
        exists only for backward compatibility and will be removed.
    """
    import warnings

    warnings.warn(
        "semantic_ner._merge_results is deprecated. Use i4g.extraction.extract_entities.",
        DeprecationWarning,
        stacklevel=2,
    )
    merged = {}
    for key in _ENTITY_KEYS:
        llm_items = set(llm_result.get(key, [])) if isinstance(llm_result.get(key), list) else set()
        rule_items = set(rule_result.get(key, [])) if isinstance(rule_result.get(key), list) else set()
        merged[key] = sorted(list(llm_items.union(rule_items)))
    return merged


def _add_confidence_scores(result: dict[str, Any], base_score: float = 0.7) -> dict[str, Any]:
    """Transform a dictionary of entity lists into a list of scored objects.

    .. deprecated::
        Use :func:`i4g.extraction.extract_entities` instead. This function
        exists only for backward compatibility and will be removed.
    """
    import warnings

    warnings.warn(
        "semantic_ner._add_confidence_scores is deprecated. Use i4g.extraction.extract_entities.",
        DeprecationWarning,
        stacklevel=2,
    )
    scored = {}
    for key, vals in result.items():
        if isinstance(vals, list):
            scored[key] = [{"value": v, "confidence": base_score} for v in vals]
        else:
            scored[key] = vals
    return scored


# ------------------------------
# MAIN ENTRYPOINT
# ------------------------------


def extract_semantic_entities(text: str, llm: OllamaLLM) -> dict[str, Any]:
    """
    Extract structured entities from text using an LLM with a rule-based fallback.

    This function orchestrates the entire extraction process:
    1. It invokes an LLM to perform semantic entity extraction.
    2. It runs a rule-based extractor to catch common patterns.
    3. It merges the results from both, removing duplicates.
    4. It adds a confidence score to each extracted entity.
    5. If the LLM fails, it includes fallback information in the final output.

    Args:
        text: The input text from which to extract entities.
        llm: An initialized `OllamaLLM` instance to use for the extraction.

    Returns:
        A dictionary containing the scored entities and any fallback information.
    """
    prompt = _format_chat_prompt(text)
    llm_result = {}
    parsed: dict[str, Any] = {}
    fallback_reason = None

    try:
        resp = llm.invoke(prompt)
        parsed = _safe_parse_json(resp)

        if parsed.get("raw_output"):
            # This covers both non-JSON and refusal cases
            fallback_reason = "llm_did_not_return_valid_json"
            if "cannot provide" in parsed["raw_output"].lower():
                fallback_reason = "llm_refused_to_answer"
        else:
            llm_result = parsed

    except Exception as e:
        fallback_reason = f"llm_invocation_error: {e}"

    # Always run rule-based extraction to supplement the LLM and serve as a fallback.
    rule_result = rule_extract_entities(text)
    merged = _merge_results(llm_result, rule_result)
    scored = _add_confidence_scores(merged)

    if fallback_reason:
        scored["fallback_info"] = {
            "reason": fallback_reason,
            "raw_output": parsed.get("raw_output"),
        }

    return scored
