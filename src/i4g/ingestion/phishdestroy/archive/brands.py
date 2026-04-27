"""Brand impersonation indicator lookup helpers for PhishDestroy archive adapters (Sprint 2 Phase D).

Provides read-only access to the ``indicators`` table so archive adapters can link a team's
``panel_url`` to existing indicators when performing best-effort brand impersonation writes.

No new ``IndicatorStore`` is introduced — direct ``select`` against the ``sql.py`` table is
sufficient and intentional for Phase D (Phase E may promote this to a store method).

References:
    - PRD §5.5 (``brand_impersonations``) — ``planning/prd_phishdestroy_integration.md``.
    - Phase D manifest §"Behaviour contract — brand impersonation best-effort".
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import sqlalchemy as sa

from i4g.store import sql as sql_schema


def lookup_indicators_for_domain(
    session_factory: Callable[..., Any],
    domain: str,
) -> list[str]:
    """Return ``indicator_id`` values matching ``(category IN ('domain', 'url'), number = domain)``.

    Performs a single read-only query against the ``indicators`` table using a fresh session
    from *session_factory*.  Returns an empty list when no indicators match.

    Does **not** create indicators — Phase D is read-only against the indicators table.

    Args:
        session_factory: A callable that returns a context-managed SQLAlchemy session, e.g.
            ``chat_session_store._session_factory``.  Callers pass an existing store's factory
            rather than opening a new connection.  Reaching into ``_session_factory`` is a
            deliberate internal access mirroring Phase C's use of ``EvidenceStorage._backend``.
        domain: The panel domain or URL to look up, e.g. ``"tttadmin.com"``.

    Returns:
        List of ``indicator_id`` strings, possibly empty.  Ordered by ``indicator_id`` for
        deterministic output in tests.
    """
    tbl = sql_schema.indicators
    stmt = (
        sa.select(tbl.c.indicator_id)
        .where(
            sa.and_(
                tbl.c.category.in_(["domain", "url"]),
                tbl.c.number == domain,
            )
        )
        .order_by(tbl.c.indicator_id)
    )
    with session_factory() as session:
        rows = session.execute(stmt).fetchall()
    return [row[0] for row in rows]
