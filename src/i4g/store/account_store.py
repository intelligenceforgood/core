"""Account store — CRUD operations for the ``accounts`` table.

This store manages user account records (role, display name, active status)
and provides the per-request role lookup used by ``auth.py``.

Design decision (F31): role is looked up from the ``accounts`` table on
every request.  The account is auto-provisioned with ``DEFAULT_ROLE`` on
first authentication (``user`` — minimal privilege) to avoid requiring
an admin to pre-register every user.  Admins can promote via User Management.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from i4g.api.roles import DEFAULT_ROLE, Role
from i4g.store import sql as sql_schema
from i4g.store.sql import dialect_insert

logger = logging.getLogger(__name__)


class AccountStore:
    """Manages account records in the ``accounts`` table."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_account(self, email: str) -> dict[str, Any] | None:
        """Look up an account by email.

        Args:
            email: The user's email address (primary key).

        Returns:
            Account dict or ``None`` if not found.
        """
        with self._session_factory() as session:
            row = session.execute(
                sa.select(sql_schema.accounts).where(sql_schema.accounts.c.email == email)
            ).first()
            if row is None:
                return None
            return dict(row._mapping)

    def get_or_create_account(self, email: str, display_name: str | None = None) -> dict[str, Any]:
        """Look up an account, creating it with the default role if absent.

        This is the main entry point used by ``require_token()`` to ensure
        every authenticated user has an account record.

        Args:
            email: The user's email address.
            display_name: Optional display name (used on first creation).

        Returns:
            Account dict with ``email``, ``role``, ``display_name``, etc.
        """
        existing = self.get_account(email)
        if existing is not None:
            return existing

        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            stmt = dialect_insert(session, sql_schema.accounts).values(
                email=email,
                role=DEFAULT_ROLE.value,
                display_name=display_name or email.split("@")[0],
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            # If another request raced us, do nothing — we'll read below.
            stmt = stmt.on_conflict_do_nothing(index_elements=["email"])
            session.execute(stmt)
            session.commit()

        # Always read back to get the authoritative row.
        return self.get_account(email)  # type: ignore[return-value]

    # Service-account email suffix — these are auto-provisioned by GCP
    # identity and should not appear in the admin user-management page.
    _SERVICE_ACCOUNT_SUFFIX = ".iam.gserviceaccount.com"

    def list_accounts(
        self, active_only: bool = True, *, include_service_accounts: bool = False
    ) -> list[dict[str, Any]]:
        """Return all accounts, optionally filtering to active only.

        Args:
            active_only: If True, exclude deactivated accounts.
            include_service_accounts: If False (default), exclude GCP
                service-account emails (``*.iam.gserviceaccount.com``).

        Returns:
            List of account dicts.
        """
        with self._session_factory() as session:
            query = sa.select(sql_schema.accounts).order_by(sql_schema.accounts.c.email)
            if active_only:
                query = query.where(sql_schema.accounts.c.is_active == sa.true())
            if not include_service_accounts:
                query = query.where(
                    ~sql_schema.accounts.c.email.endswith(self._SERVICE_ACCOUNT_SUFFIX)
                )
            rows = session.execute(query).all()
            return [dict(r._mapping) for r in rows]

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def update_role(self, email: str, new_role: str, actor: str) -> dict[str, Any] | None:
        """Change a user's role and log the change.

        Args:
            email: Target user's email.
            new_role: The new role value (must be a valid ``Role``).
            actor: Email of the admin performing the change.

        Returns:
            Updated account dict, or ``None`` if user not found.

        Raises:
            ValueError: If *new_role* is not a valid role.
        """
        # Validate role value.
        try:
            Role(new_role)
        except ValueError:
            raise ValueError(f"Invalid role: {new_role!r}. Must be one of {[r.value for r in Role]}")

        existing = self.get_account(email)
        if existing is None:
            return None

        old_role = existing["role"]
        now = datetime.now(timezone.utc)

        with self._session_factory() as session:
            session.execute(
                sa.update(sql_schema.accounts)
                .where(sql_schema.accounts.c.email == email)
                .values(role=new_role, updated_at=now)
            )

            # Audit trail — dedicated account_actions table (no FK to review_queue).
            session.execute(
                sa.insert(sql_schema.account_actions).values(
                    action_id=f"role-change-{email}-{now.isoformat()}",
                    target_email=email,
                    actor=actor,
                    action="role_change",
                    payload={
                        "old_role": old_role,
                        "new_role": new_role,
                    },
                    created_at=now,
                )
            )
            session.commit()

        logger.info("Role changed: %s %s → %s (by %s)", email, old_role, new_role, actor)
        return self.get_account(email)

    def update_display_name(self, email: str, display_name: str) -> dict[str, Any] | None:
        """Update a user's display name.

        Args:
            email: Target user's email.
            display_name: New display name.

        Returns:
            Updated account dict, or ``None`` if user not found.
        """
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            result = session.execute(
                sa.update(sql_schema.accounts)
                .where(sql_schema.accounts.c.email == email)
                .values(display_name=display_name, updated_at=now)
            )
            session.commit()
            if result.rowcount == 0:
                return None
        return self.get_account(email)

    def deactivate_account(self, email: str, actor: str) -> bool:
        """Deactivate an account (soft disable).

        Args:
            email: Target user's email.
            actor: Email of the admin performing the action.

        Returns:
            True if the account was deactivated.
        """
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            result = session.execute(
                sa.update(sql_schema.accounts)
                .where(sql_schema.accounts.c.email == email)
                .values(is_active=False, updated_at=now)
            )
            if result.rowcount > 0:
                session.execute(
                    sa.insert(sql_schema.account_actions).values(
                        action_id=f"deactivate-{email}-{now.isoformat()}",
                        target_email=email,
                        actor=actor,
                        action="account_deactivated",
                        payload={},
                        created_at=now,
                    )
                )
            session.commit()
            return result.rowcount > 0

    def reactivate_account(self, email: str, actor: str) -> bool:
        """Reactivate a previously deactivated account.

        Args:
            email: Target user's email.
            actor: Email of the admin performing the action.

        Returns:
            True if the account was reactivated.
        """
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            result = session.execute(
                sa.update(sql_schema.accounts)
                .where(sql_schema.accounts.c.email == email)
                .values(is_active=True, updated_at=now)
            )
            if result.rowcount > 0:
                session.execute(
                    sa.insert(sql_schema.account_actions).values(
                        action_id=f"reactivate-{email}-{now.isoformat()}",
                        target_email=email,
                        actor=actor,
                        action="account_reactivated",
                        payload={},
                        created_at=now,
                    )
                )
            session.commit()
            return result.rowcount > 0
