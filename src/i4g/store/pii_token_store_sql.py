"""SQLAlchemy-backed token store for Cloud SQL (PostgreSQL)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Iterable

import sqlalchemy as sa
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from i4g.store.pii_token_store import StoredToken
from i4g.store.sql import pii_tokens


class SqlAlchemyPiiTokenStore:
    """PostgreSQL-backed store for tokenized PII using SQLAlchemy Core/ORM."""

    def __init__(self, session_factory: Callable[[], Session], *, fernet: Fernet | None = None) -> None:
        self.session_factory = session_factory
        self.fernet = fernet

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
        created_at = datetime.now(timezone.utc)

        stmt = sa.dialects.postgresql.insert(pii_tokens).values(
            token=token,
            prefix=prefix,
            digest=digest,
            normalized_value=normalized_value,
            canonical_value=None if encrypted_value is not None else canonical_value,
            encrypted_value=encrypted_value,
            pepper_version=pepper_version,
            detector=detector,
            case_id=case_id,
            created_at=created_at,
        )
        
        # On conflict, update mutable fields
        stmt = stmt.on_conflict_do_update(
            index_elements=[pii_tokens.c.token],
            set_={
                "detector": stmt.excluded.detector,
                "case_id": stmt.excluded.case_id,
            },
        )

        with self.session_factory() as session:
            session.execute(stmt)
            session.commit()

    def fetch(self, token: str) -> StoredToken | None:
        """Return stored token metadata, including decrypted canonical value when possible."""

        stmt = sa.select(pii_tokens).where(pii_tokens.c.token == token)
        with self.session_factory() as session:
            row = session.execute(stmt).fetchone()
            if not row:
                return None
            
            # row is a Row object, access by index or attribute if mapped, but here it's Core table
            # row._mapping provides dict-like access
            data = row._mapping
            
            canonical_value = data["canonical_value"]
            encrypted_value = data["encrypted_value"]
            
            if canonical_value is None and encrypted_value is not None:
                canonical_value = self._decrypt(encrypted_value)
                
            return StoredToken(
                token=data["token"],
                prefix=data["prefix"],
                normalized_value=data["normalized_value"],
                canonical_value=canonical_value,
                pepper_version=data["pepper_version"],
                detector=data["detector"],
                case_id=data["case_id"],
                created_at=data["created_at"].isoformat() if data["created_at"] else None,
            )

    def list_tokens(self, *, prefixes: Iterable[str] | None = None) -> list[StoredToken]:
        """Enumerate stored tokens."""
        
        stmt = sa.select(pii_tokens)
        if prefixes:
            stmt = stmt.where(pii_tokens.c.prefix.in_(prefixes))
            
        with self.session_factory() as session:
            rows = session.execute(stmt).fetchall()
            
        tokens: list[StoredToken] = []
        for row in rows:
            data = row._mapping
            canonical_value = data["canonical_value"]
            encrypted_value = data["encrypted_value"]
            
            if canonical_value is None and encrypted_value is not None:
                canonical_value = self._decrypt(encrypted_value)
                
            tokens.append(
                StoredToken(
                    token=data["token"],
                    prefix=data["prefix"],
                    normalized_value=data["normalized_value"],
                    canonical_value=canonical_value,
                    pepper_version=data["pepper_version"],
                    detector=data["detector"],
                    case_id=data["case_id"],
                    created_at=data["created_at"].isoformat() if data["created_at"] else None,
                )
            )
        return tokens

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
