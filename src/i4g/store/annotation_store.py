"""Annotation store for freeform analyst notes on entities, indicators, and campaigns.

Provides CRUD operations for the ``annotations`` table, supporting notes
on any target type (entity, indicator, campaign, case).
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from i4g.store.sql import METADATA, annotations, build_engine


class AnnotationStore:
    """Store for managing analyst annotations on entities, indicators, campaigns, and cases.

    Args:
        db_path: Path to SQLite database (local mode).
        session_factory: SQLAlchemy session factory (Cloud SQL mode).
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        session_factory: sessionmaker | None = None,
    ) -> None:
        if session_factory is not None:
            self._session_factory = session_factory
        else:
            engine = build_engine()
            if engine.dialect.name == "sqlite":
                METADATA.create_all(engine, checkfirst=True)
            self._session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    @contextmanager
    def _session_scope(self):
        """Yield a session and auto-close on exit."""
        session: Session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    def create_annotation(
        self,
        *,
        target_type: str,
        target_id: str,
        content: str,
        author: str = "system",
    ) -> str:
        """Create a new annotation.

        Args:
            target_type: One of ``entity``, ``indicator``, ``campaign``, ``case``.
            target_id: ID of the target object.
            content: The annotation text.
            author: Who wrote the annotation.

        Returns:
            The new annotation ID.
        """
        annotation_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        with self._session_scope() as session:
            session.execute(
                sa.insert(annotations).values(
                    annotation_id=annotation_id,
                    target_type=target_type,
                    target_id=target_id,
                    content=content,
                    author=author,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()
        return annotation_id

    def get_annotation(self, annotation_id: str) -> dict[str, Any] | None:
        """Retrieve a single annotation by ID.

        Args:
            annotation_id: The annotation UUID.

        Returns:
            Annotation dict or None if not found.
        """
        with self._session_scope() as session:
            row = session.execute(sa.select(annotations).where(annotations.c.annotation_id == annotation_id)).first()
            if row is None:
                return None
            return dict(row._mapping)

    def list_annotations(
        self,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
        author: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List annotations with optional filters.

        Args:
            target_type: Filter by target type.
            target_id: Filter by target ID.
            author: Filter by author.
            limit: Max results.
            offset: Pagination offset.

        Returns:
            List of annotation dicts.
        """
        stmt = sa.select(annotations).order_by(annotations.c.created_at.desc())
        if target_type:
            stmt = stmt.where(annotations.c.target_type == target_type)
        if target_id:
            stmt = stmt.where(annotations.c.target_id == target_id)
        if author:
            stmt = stmt.where(annotations.c.author == author)
        stmt = stmt.limit(limit).offset(offset)

        with self._session_scope() as session:
            rows = session.execute(stmt).all()
            return [dict(r._mapping) for r in rows]

    def update_annotation(self, annotation_id: str, *, content: str) -> bool:
        """Update the content of an existing annotation.

        Args:
            annotation_id: The annotation UUID.
            content: New annotation content.

        Returns:
            True if the annotation was updated.
        """
        with self._session_scope() as session:
            result = session.execute(
                sa.update(annotations)
                .where(annotations.c.annotation_id == annotation_id)
                .values(content=content, updated_at=datetime.now(UTC))
            )
            session.commit()
            return result.rowcount > 0

    def delete_annotation(self, annotation_id: str) -> bool:
        """Delete an annotation.

        Args:
            annotation_id: The annotation UUID.

        Returns:
            True if the annotation was deleted.
        """
        with self._session_scope() as session:
            result = session.execute(sa.delete(annotations).where(annotations.c.annotation_id == annotation_id))
            session.commit()
            return result.rowcount > 0
