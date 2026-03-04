"""SQLAlchemy-backed token store for the PII vault (SQLite + Cloud SQL)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime

import sqlalchemy as sa
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from i4g.store.pii_token_store import StoredToken
from i4g.store.sql import audit_log, dialect_insert, pii_tokens


class SqlAlchemyPiiTokenStore:
    """Unified SQLAlchemy-backed store for tokenized PII (SQLite and PostgreSQL)."""

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
        created_at = datetime.now(UTC)

        with self.session_factory() as session:
            stmt = dialect_insert(session, pii_tokens).values(
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

    def log_access(
        self,
        *,
        actor: str,
        action: str,
        token: str | None = None,
        prefix: str | None = None,
        outcome: str,
        reason: str | None = None,
        case_id: str | None = None,
    ) -> None:
        """Record an audit log entry for a sensitive operation."""

        timestamp = datetime.now(UTC)
        with self.session_factory() as session:
            session.execute(
                sa.insert(audit_log).values(
                    timestamp=timestamp,
                    actor=actor,
                    action=action,
                    token=token,
                    prefix=prefix,
                    outcome=outcome,
                    reason=reason,
                    case_id=case_id,
                )
            )
            session.commit()

    def delete_tokens_for_case(self, case_id: str) -> int:
        """Delete all PII tokens associated with a case and log the action.

        Args:
            case_id: The case whose tokens should be purged.

        Returns:
            Number of tokens deleted.
        """
        with self.session_factory() as session:
            result = session.execute(sa.delete(pii_tokens).where(pii_tokens.c.case_id == case_id))
            deleted = result.rowcount
            session.commit()

        if deleted:
            self.log_access(
                actor="system:retention_purge",
                action="purge_tokens",
                outcome="success",
                reason=f"Retention purge: {deleted} tokens removed",
                case_id=case_id,
            )
        return deleted

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
