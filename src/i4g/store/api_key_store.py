"""API Key Store — CRUD and validation operations for the ``api_keys`` table.

This store manages database-backed API keys (partner, user self-service, and service keys),
providing key generation, hashing, lookup, validation, revocation, and lifecycle operations.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa

from i4g.store import sql as sql_schema

logger = logging.getLogger(__name__)


class ApiKeyStore:
    """Manages API key records in the ``api_keys`` table."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_key(key_type: str) -> tuple[str, str, str]:
        """Generate a random raw key, prefix, and type code.

        Args:
            key_type: One of "partner", "user", "service".

        Returns:
            Tuple of (type_code, key_prefix, raw_key).
        """
        type_codes = {
            "partner": "pk",
            "user": "uk",
            "service": "sk",
        }
        code = type_codes.get(key_type.lower(), "uk")
        random_hex = secrets.token_hex(16)  # 32 characters
        raw_key = f"i4g_{code}_{random_hex}"
        prefix = f"i4g_{code}_{random_hex[:8]}"
        return code, prefix, raw_key

    @staticmethod
    def _hash_key(raw_key: str) -> str:
        """Hash a raw key using SHA-256 hex digest.

        Args:
            raw_key: Unhashed raw key string.

        Returns:
            SHA-256 hex string.
        """
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # CRUD Operations
    # ------------------------------------------------------------------

    def create_key(
        self,
        owner_email: str | None = None,
        key_type: str = "user",
        description: str | None = None,
        partner_name: str | None = None,
        scopes: list[str] | None = None,
        expires_in_days: int | None = None,
        rate_limit_per_minute: int = 60,
        created_by: str = "system",
    ) -> tuple[str, dict[str, Any]]:
        """Create a new API key record.

        Args:
            owner_email: Email address of the key owner.
            key_type: Discriminator ("user", "partner", "service").
            description: Optional human-readable description.
            partner_name: Optional partner organization name.
            scopes: List of scope strings granted to key.
            expires_in_days: Days until expiration (None for perpetual).
            rate_limit_per_minute: Per-minute rate limit.
            created_by: Email or identifier of creator.

        Returns:
            Tuple of (raw_key, key_record_dict). Raw key is returned ONLY here.
        """
        code, prefix, raw_key = self._generate_key(key_type)
        key_hash = self._hash_key(raw_key)
        key_id = f"apk_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC)
        expires_at = now + timedelta(days=expires_in_days) if expires_in_days is not None else None

        values = {
            "key_id": key_id,
            "key_type": key_type,
            "description": description,
            "owner_email": owner_email,
            "partner_name": partner_name,
            "key_hash": key_hash,
            "key_prefix": prefix,
            "scopes": scopes or [],
            "rate_limit_per_minute": rate_limit_per_minute,
            "is_active": True,
            "created_by": created_by,
            "last_used_at": None,
            "expires_at": expires_at,
            "created_at": now,
        }

        with self._session_factory() as session:
            session.execute(sa.insert(sql_schema.api_keys).values(**values))
            session.commit()

        # Return dict representation without sensitive fields if needed, but key_hash is present
        record = dict(values)
        return raw_key, record

    def validate_key(self, raw_key: str) -> dict[str, Any] | None:
        """Validate a raw API key and update its last_used_at timestamp.

        Args:
            raw_key: Unhashed key provided in request header.

        Returns:
            Key record dict if valid and non-expired; None otherwise.
        """
        if not raw_key or not isinstance(raw_key, str):
            return None

        key_hash = self._hash_key(raw_key)
        now = datetime.now(UTC)

        with self._session_factory() as session:
            row = session.execute(
                sa.select(sql_schema.api_keys).where(
                    sql_schema.api_keys.c.key_hash == key_hash,
                    sql_schema.api_keys.c.is_active.is_(True),
                )
            ).first()

            if row is None:
                return None

            record = dict(row._mapping)

            # Check expiration
            expires_at = record.get("expires_at")
            if expires_at is not None:
                if isinstance(expires_at, str):
                    expires_at = datetime.fromisoformat(expires_at)
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                if expires_at <= now:
                    return None

            # Update last_used_at timestamp atomically
            session.execute(
                sa.update(sql_schema.api_keys)
                .where(sql_schema.api_keys.c.key_id == record["key_id"])
                .values(last_used_at=now)
            )
            session.commit()
            record["last_used_at"] = now
            return record

    def list_keys_for_owner(self, owner_email: str, key_type: str | None = None) -> list[dict[str, Any]]:
        """List all API keys owned by a given user email.

        Args:
            owner_email: Email address of the key owner.
            key_type: Optional filter by key_type.

        Returns:
            List of key record dicts (ordered newest first).
        """
        with self._session_factory() as session:
            query = sa.select(sql_schema.api_keys).where(sql_schema.api_keys.c.owner_email == owner_email)
            if key_type:
                query = query.where(sql_schema.api_keys.c.key_type == key_type)

            rows = session.execute(query.order_by(sql_schema.api_keys.c.created_at.desc())).all()
            return [dict(r._mapping) for r in rows]

    def list_all_keys(self, key_type: str | None = None, active_only: bool = False) -> list[dict[str, Any]]:
        """List all API keys in system (admin view).

        Args:
            key_type: Optional filter by key_type.
            active_only: If True, returns only active keys.

        Returns:
            List of key record dicts (ordered newest first).
        """
        with self._session_factory() as session:
            query = sa.select(sql_schema.api_keys)
            if key_type:
                query = query.where(sql_schema.api_keys.c.key_type == key_type)
            if active_only:
                query = query.where(sql_schema.api_keys.c.is_active.is_(True))

            rows = session.execute(query.order_by(sql_schema.api_keys.c.created_at.desc())).all()
            return [dict(r._mapping) for r in rows]

    def revoke_key(self, key_id: str, owner_email: str | None = None) -> bool:
        """Revoke an API key by setting is_active = False.

        Args:
            key_id: ID of the key to revoke.
            owner_email: Optional owner email constraint for non-admin revocation.

        Returns:
            True if a key was updated, False if key was not found or ownership mismatched.
        """
        with self._session_factory() as session:
            query = sa.update(sql_schema.api_keys).where(
                sql_schema.api_keys.c.key_id == key_id,
                sql_schema.api_keys.c.is_active.is_(True),
            )
            if owner_email:
                query = query.where(sql_schema.api_keys.c.owner_email == owner_email)

            result = session.execute(query.values(is_active=False))
            session.commit()
            return result.rowcount > 0

    def delete_key(self, key_id: str, owner_email: str | None = None) -> bool:
        """Hard delete an API key record.

        Args:
            key_id: ID of the key to delete.
            owner_email: Optional owner email constraint.

        Returns:
            True if key was deleted, False if not found.
        """
        with self._session_factory() as session:
            query = sa.delete(sql_schema.api_keys).where(sql_schema.api_keys.c.key_id == key_id)
            if owner_email:
                query = query.where(sql_schema.api_keys.c.owner_email == owner_email)

            result = session.execute(query)
            session.commit()
            return result.rowcount > 0
