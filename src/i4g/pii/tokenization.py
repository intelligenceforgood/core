"""Deterministic tokenization utilities backed by the PII vault store."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Tuple

from cryptography.fernet import Fernet, InvalidToken

from i4g.pii.normalization import normalize
from i4g.pii.observability import PiiVaultObservability
from i4g.settings import Settings, get_settings
from i4g.store.pii_token_store import PiiTokenStore, StoredToken

_TOKEN_PATTERN = re.compile(r"[A-Z]{3}-[0-9A-F]{8}")


@dataclass(slots=True)
class TokenizedValue:
    """Represents a single tokenization result."""

    token: str
    prefix: str
    digest: str
    normalized_value: str
    pepper_version: str


class TokenizationService:
    """Generate deterministic tokens and persist canonical PII for detokenization."""

    _ENTITY_PREFIX_MAP: Dict[str, str] = {
        "email": "EID",
        "phone": "PHN",
        "ip_address": "IPA",
        "asn": "ASN",
        "bank_account": "BAN",
        "crypto_wallet": "WLT",
        "wallet": "WLT",
        "url": "DOC",
        "browser_agent": "BFP",
        "name": "NAM",
        "address": "ADR",
        "dob": "DOB",
    }

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        store: PiiTokenStore | None = None,
        observability: PiiVaultObservability | None = None,
        pepper: str | None = None,
        encryption_key: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        token_settings = self.settings.pii
        self.pepper = (pepper or token_settings.pepper or "").strip()
        self.pepper_version = token_settings.pepper_version.strip() or "v1"
        self.require_pepper = bool(token_settings.require_pepper)
        if self.require_pepper and not self.pepper:
            raise ValueError("Tokenization pepper is required but missing.")
        self._pepper_bytes = self.pepper.encode("utf-8") if self.pepper else b""
        self._fernet = self._build_fernet(encryption_key or self.settings.crypto.pii_key)
        self.store = store or PiiTokenStore(fernet=self._fernet)
        self.observability = observability or PiiVaultObservability.build(settings=self.settings)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def tokenize(
        self, value: str, prefix: str, *, detector: str | None = None, case_id: str | None = None
    ) -> TokenizedValue:
        """Tokenize a single value using the configured pepper."""

        if not value or not isinstance(value, str):
            raise ValueError("Tokenization requires a non-empty string value.")
        normalized = self._normalize(prefix, value)
        digest = self._hmac_digest(prefix, normalized)
        token = f"{prefix}-{digest[:8].upper()}"
        self.store.upsert_token(
            token=token,
            prefix=prefix,
            digest=digest,
            normalized_value=normalized,
            canonical_value=value,
            pepper_version=self.pepper_version,
            detector=detector,
            case_id=case_id,
        )
        self.observability.record_tokenization(
            token_count=1,
            field_count=1,
            raw_bytes=len(value.encode("utf-8")),
            source="tokenize",
            detector=detector,
            prefix=prefix,
            case_id=case_id,
        )
        return TokenizedValue(
            token=token,
            prefix=prefix,
            digest=digest,
            normalized_value=normalized,
            pepper_version=self.pepper_version,
        )

    def tokenize_entities(
        self,
        entities: Mapping[str, Any] | None,
        *,
        detector: str | None = None,
        case_id: str | None = None,
    ) -> Dict[str, list[Dict[str, Any]]]:
        """Tokenize a mapping of entity lists, returning a token-only structure."""

        if not entities:
            return {}
        tokenized: Dict[str, list[Dict[str, Any]]] = {}
        for entity_type, values in entities.items():
            if not isinstance(values, Iterable):
                continue
            prefix = self._prefix_for_entity(entity_type)
            tokens: list[Dict[str, Any]] = []
            for raw in values:
                value = self._extract_value(raw)
                if not value:
                    continue
                token_result = self.tokenize(value, prefix, detector=detector, case_id=case_id)
                tokens.append(
                    {
                        "token": token_result.token,
                        "value": token_result.token,
                        "prefix": token_result.prefix,
                        "pepper_version": token_result.pepper_version,
                    }
                )
            if tokens:
                tokenized[entity_type] = tokens
        return tokenized

    def tokenize_text_content(
        self,
        text: str,
        *,
        detector: str | None = None,
        case_id: str | None = None,
    ) -> str:
        """Scan text for PII patterns and replace with tokens."""
        if not text:
            return text

        # Email
        # Simple regex, can be improved
        text = re.sub(
            r"[\w\.-]+@[\w\.-]+\.\w+",
            lambda m: self.tokenize(m.group(0), "EID", detector=detector, case_id=case_id).token,
            text
        )

        # IPv4
        text = re.sub(
            r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
            lambda m: self.tokenize(m.group(0), "IPA", detector=detector, case_id=case_id).token,
            text
        )

        return text

    def tokenize_tree(
        self,
        data: Any,
        *,
        detector: str | None = None,
        case_id: str | None = None,
    ) -> Any:
        """Recursively walk a structure and tokenize values where keys match PII types."""
        if isinstance(data, dict):
            return {
                k: self._tokenize_value_if_pii(k, v, detector=detector, case_id=case_id)
                for k, v in data.items()
            }
        if isinstance(data, list):
            return [self.tokenize_tree(item, detector=detector, case_id=case_id) for item in data]
        return data

    def _tokenize_value_if_pii(
        self, key: str, value: Any, *, detector: str | None = None, case_id: str | None = None
    ) -> Any:
        # If value is complex, recurse
        if isinstance(value, (dict, list)):
            return self.tokenize_tree(value, detector=detector, case_id=case_id)

        # If value is string, check if key implies PII
        if isinstance(value, str) and value:
            prefix = self._infer_prefix(key)
            if prefix != "UNK":
                # Tokenize!
                return self.tokenize(value, prefix, detector=detector, case_id=case_id).token

        return value

    def _infer_prefix(self, key: str) -> str:
        key_lower = key.lower()
        # Exact match
        if key_lower in self._ENTITY_PREFIX_MAP:
            return self._ENTITY_PREFIX_MAP[key_lower]

        # Common variations
        if "email" in key_lower:
            return "EID"
        if "phone" in key_lower or "mobile" in key_lower:
            return "PHN"
        if "ip_address" in key_lower or key_lower == "ip" or key_lower.endswith("_ip"):
            return "IPA"
        if "wallet" in key_lower:
            return "WLT"
        if "dob" in key_lower or "birth" in key_lower:
            return "DOB"
        if "ssn" in key_lower or "tax_id" in key_lower:
            return "TIN"

        return "UNK"

    def resolve_prefix(self, entity_type: str | None) -> str:
        """Return a prefix code for the provided entity type."""

        if not entity_type:
            return "UNK"
        return self._prefix_for_entity(entity_type)

    def detokenize(self, token: str, *, actor: str | None = None, case_id: str | None = None) -> StoredToken | None:
        """Return the stored token record, recording observability for audit."""

        actor_name = actor or "unknown"
        stored = self.store.fetch(token)
        outcome = "success" if stored and stored.canonical_value else "not_found"
        
        self.observability.record_detokenization_attempt(
            actor=actor_name,
            prefix=stored.prefix if stored else None,
            outcome=outcome,
            reason=None if stored else "missing",
            case_id=case_id,
        )
        
        self.store.log_access(
            actor=actor_name,
            action="detokenize",
            token=token,
            prefix=stored.prefix if stored else None,
            outcome=outcome,
            reason=None if stored else "missing",
            case_id=case_id,
        )
        
        return stored

    @staticmethod
    def is_token(value: str) -> bool:
        return bool(value and isinstance(value, str) and _TOKEN_PATTERN.fullmatch(value.strip()))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _hmac_digest(self, prefix: str, normalized_value: str) -> str:
        # Design: HMAC-SHA256(value || prefix || version)
        # We use a separator for safety against concatenation collisions, though design implies concatenation.
        # Using concatenation as per design doc: value + prefix + version
        message = f"{normalized_value}{prefix}{self.pepper_version}".encode("utf-8")
        return hmac.new(self._pepper_bytes, message, hashlib.sha256).hexdigest()

    def _normalize(self, prefix: str, value: str) -> str:
        return normalize(prefix, value)

    def _prefix_for_entity(self, entity_type: str) -> str:
        normalized = (entity_type or "").strip().lower()
        return self._ENTITY_PREFIX_MAP.get(normalized, "UNK")

    @staticmethod
    def _extract_value(raw: Any) -> str | None:
        if isinstance(raw, str):
            return raw.strip()
        if isinstance(raw, dict):
            for key in ("value", "canonical", "raw", "token"):
                candidate = raw.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
        return None

    @staticmethod
    def _build_fernet(raw_key: str | None) -> Fernet | None:
        if not raw_key:
            return None
        candidate = raw_key.strip()
        try:
            key_bytes = candidate.encode("utf-8")
            # Allow raw bytes or already-base64 keys
            if len(candidate) != 44:
                key_bytes = base64.urlsafe_b64encode(candidate.encode("utf-8"))
            return Fernet(key_bytes)
        except (ValueError, InvalidToken):
            return None


__all__ = ["TokenizationService", "TokenizedValue"]
