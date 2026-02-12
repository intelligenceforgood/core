"""LLM-driven extraction utilities for financial indicators."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable

from langchain_core.messages import HumanMessage, SystemMessage

from i4g.settings import Settings, get_settings

from .models import FinancialIndicator, SourceDocument
from .queries import IndicatorQuery

LOGGER = logging.getLogger(__name__)


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1]).strip()
    return stripped


class AccountEntityExtractor:
    """Execute category prompts using the configured LLM provider."""

    def __init__(self, *, settings: Settings | None = None, max_chars: int = 12000) -> None:
        self.settings = settings or get_settings()
        self.max_chars = max_chars
        self.provider = (self.settings.llm.provider or "ollama").lower()
        self._client = self._build_client()

    def _build_client(self):
        from i4g.llm.client import build_langchain_llm

        if self.provider == "mock":
            return None

        return build_langchain_llm(settings=self.settings)

    def extract_indicators(
        self,
        *,
        query: IndicatorQuery,
        documents: Iterable[SourceDocument],
    ) -> list[FinancialIndicator]:
        doc_list = list(documents)
        if not doc_list:
            return []

        if self.provider == "mock":
            return self._mock_extract(query=query, documents=doc_list)

        context = self._build_context(doc_list)
        human_prompt = f"Retrieved Documents:\n{context}\n\nReturn the JSON list now."
        try:
            response = self._client.invoke(
                [
                    SystemMessage(content=query.system_message),
                    HumanMessage(content=human_prompt),
                ]
            )
        except Exception:  # pragma: no cover - LLM availability
            LOGGER.exception("LLM invocation failed for query %s", query.slug)
            raise

        content = getattr(response, "content", "")
        if not content:
            LOGGER.error("LLM returned empty content for query %s", query.slug)
            return []

        payload = _strip_code_fence(content)
        indicators = self._parse_payload(payload, query)
        return indicators

    def _mock_extract(self, *, query: IndicatorQuery, documents: list[SourceDocument]) -> list[FinancialIndicator]:
        text = "\n".join(doc.content or "" for doc in documents)
        indicators: list[FinancialIndicator] = []
        seen: set[tuple[str, str, str]] = set()

        def _add(item: str, indicator_type: str, number: str) -> None:
            # Clean up inputs
            item = item.strip()
            number = number.strip()
            if not item or not number:
                return

            key = (indicator_type.lower(), item.lower(), number.lower())
            if key in seen:
                return
            seen.add(key)
            indicators.append(
                FinancialIndicator(
                    category=query.slug,
                    item=item,
                    type=indicator_type,
                    number=number,
                    metadata={"source": "mock_extractor"},
                )
            )

        lowered = text.lower()
        if query.slug == "bank":
            # Match "Bank Name: <Name> ... Account number : <Num>" patterns
            simple_bank = re.search(r"bank name\s*[:]\s*([^:]+?)\s+account", lowered)
            simple_acct = re.search(r"account number\s*[:]\s*(\d+)", lowered)

            if simple_bank and simple_acct:
                _add(simple_bank.group(1).title(), "bank_account", simple_acct.group(1))

            # Original stringent regex
            bank_match = re.search(r'"([^"\\]+)"\s+checking', text, re.IGNORECASE)
            account_match = re.search(r"account ending (\d{2,})", lowered)
            routing_match = re.search(r"routing number\s*[:]?\s*(\d{5,})", lowered)

            if bank_match and account_match:
                suffix = account_match.group(1)[-4:]
                _add(bank_match.group(1), "bank_account", f"****{suffix}")
            if routing_match:
                _add("Routing Number", "routing_number", routing_match.group(1))

        elif query.slug == "crypto":
            # Bitcoin (legacy & bech32)
            for match in re.findall(r"\b(bc1|[13])[a-zA-HJ-NP-Z0-9]{25,39}\b", text):
                _add("Bitcoin Wallet", "crypto_wallet", match)
            # Ethereum
            for match in re.findall(r"\b0x[a-fA-F0-9]{40}\b", text):
                _add("Ethereum Wallet", "crypto_wallet", match)

        elif query.slug == "payments":
            for email in re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text):
                # Filter out likely false positives if needed
                label = "PayPal" if "paypal" in email.lower() else "Payment Handle"
                _add(label, "payment_service", email)
            for handle in re.findall(r"\$[A-Za-z0-9]+", text):
                _add("Cash App", "payment_service", handle)

        return indicators

    def _build_context(self, documents: list[SourceDocument]) -> str:
        remaining = self.max_chars
        parts: list[str] = []
        for doc in documents:
            chunk = doc.content.strip()
            if not chunk:
                continue
            if len(chunk) > remaining:
                chunk = chunk[: max(0, remaining - 1)]
            remaining -= len(chunk)
            parts.append(
                f"Case ID: {doc.case_id}\nClassification: {doc.classification or 'unknown'}\nDataset: {doc.dataset or 'unknown'}\nContent:\n{chunk}\n---"
            )
            if remaining <= 0:
                break
        return "\n".join(parts)

    def _parse_payload(self, payload: str, query: IndicatorQuery) -> list[FinancialIndicator]:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            LOGGER.warning("Extractor returned unparseable payload for %s", query.slug)
            return []
        if not isinstance(data, list):
            LOGGER.warning("Extractor payload is not a list for %s", query.slug)
            return []
        indicators: list[FinancialIndicator] = []
        seen: set[tuple[str, str, str]] = set()
        for item in data:
            if not isinstance(item, dict):
                continue
            name = str(item.get("item") or item.get("bank") or item.get("crypto_type") or "").strip()
            number = str(item.get("number") or item.get("account_number") or item.get("wallet_address") or "").strip()
            indicator_type = str(item.get("type") or query.indicator_type).strip() or query.indicator_type
            if not name or not number:
                continue
            key = (indicator_type.lower(), name.lower(), number.lower())
            if key in seen:
                continue
            seen.add(key)
            indicators.append(
                FinancialIndicator(
                    category=query.slug,
                    item=name,
                    type=indicator_type,
                    number=number,
                    metadata={"raw": item},
                )
            )
        return indicators
