"""SQLite-backed token store for canonical PII values."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from cryptography.fernet import Fernet, InvalidToken

from i4g.settings import get_settings


@dataclass(slots=True)
class StoredToken:
    """Represents a token row persisted in the vault store."""

    token: str
    prefix: str
    normalized_value: str
    canonical_value: str | None
    pepper_version: str
    detector: str | None
    case_id: str | None
    created_at: str


class PiiTokenStore:
    """Lightweight SQLite-backed store for tokenized PII."""

    def __init__(self, db_path: Path | str | None = None, *, fernet: Fernet | None = None) -> None:
        settings = get_settings()
        resolved = Path(db_path) if db_path else Path(settings.storage.sqlite_path)
        if not resolved.is_absolute():
            resolved = (Path(settings.project_root) / resolved).resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = resolved
        self.fernet = fernet
        self._init_tables()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upsert_token(
        self,
        *,
        token: str,
        prefix: str,
        digest: str,
        normalized_value: str,
        canonical_value: str,
        pepper_version: str,
        detector: str | None = None,
        case_id: str | None = None,
    ) -> None:
        """Insert the token row if not already present."""

        encrypted_value = self._encrypt(canonical_value)
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pii_tokens (
                    token,
                    prefix,
                    digest,
                    normalized_value,
                    canonical_value,
                    encrypted_value,
                    pepper_version,
                    detector,
                    case_id,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(token) DO UPDATE SET
                    detector=excluded.detector,
                    case_id=excluded.case_id
                """,
                (
                    token,
                    prefix,
                    digest,
                    normalized_value,
                    None if encrypted_value is not None else canonical_value,
                    encrypted_value,
                    pepper_version,
                    detector,
                    case_id,
                    created_at,
                ),
            )

    def fetch(self, token: str) -> StoredToken | None:
        """Return stored token metadata, including decrypted canonical value when possible."""

        with self._connect() as conn:
            row = conn.execute(
                "SELECT token, prefix, normalized_value, canonical_value, encrypted_value, pepper_version, detector, case_id, created_at FROM pii_tokens WHERE token = ?",
                (token,),
            ).fetchone()
        if not row:
            return None
        canonical_value = row["canonical_value"]
        encrypted_value = row["encrypted_value"]
        if canonical_value is None and encrypted_value is not None:
            canonical_value = self._decrypt(encrypted_value)
        return StoredToken(
            token=row["token"],
            prefix=row["prefix"],
            normalized_value=row["normalized_value"],
            canonical_value=canonical_value,
            pepper_version=row["pepper_version"],
            detector=row["detector"],
            case_id=row["case_id"],
            created_at=row["created_at"],
        )

    def list_tokens(self, *, prefixes: Iterable[str] | None = None) -> list[StoredToken]:
        """Enumerate stored tokens (dev/test helper)."""

        query = "SELECT token, prefix, normalized_value, canonical_value, encrypted_value, pepper_version, detector, case_id, created_at FROM pii_tokens"
        params: list[Any] = []
        if prefixes:
            prefix_list = list(prefixes)
            if prefix_list:
                query += " WHERE prefix IN ({})".format(",".join(["?"] * len(prefix_list)))
                params.extend(prefix_list)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        tokens: list[StoredToken] = []
        for row in rows:
            canonical_value = row["canonical_value"]
            encrypted_value = row["encrypted_value"]
            if canonical_value is None and encrypted_value is not None:
                canonical_value = self._decrypt(encrypted_value)
            tokens.append(
                StoredToken(
                    token=row["token"],
                    prefix=row["prefix"],
                    normalized_value=row["normalized_value"],
                    canonical_value=canonical_value,
                    pepper_version=row["pepper_version"],
                    detector=row["detector"],
                    case_id=row["case_id"],
                    created_at=row["created_at"],
                )
            )
        return tokens

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pii_tokens (
                    token TEXT PRIMARY KEY,
                    prefix TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    normalized_value TEXT NOT NULL,
                    canonical_value TEXT,
                    encrypted_value BLOB,
                    pepper_version TEXT NOT NULL,
                    detector TEXT,
                    case_id TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pii_tokens_prefix ON pii_tokens(prefix)")

    def _encrypt(self, value: str) -> bytes | None:
        if self.fernet is None:
            return None
        try:
            return self.fernet.encrypt(value.encode("utf-8"))
        except Exception:
            return None

    def _decrypt(self, blob: bytes) -> str | None:
        if self.fernet is None:
            return None
        try:
            return self.fernet.decrypt(blob).decode("utf-8")
        except (InvalidToken, TypeError, ValueError):
            return None


__all__ = ["PiiTokenStore", "StoredToken"]
