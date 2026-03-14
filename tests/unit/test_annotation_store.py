"""Unit tests for AnnotationStore CRUD operations (Sprint 4 — S4-15)."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.store.annotation_store import AnnotationStore
from i4g.store.sql import METADATA


def _make_store(db_path: Path) -> AnnotationStore:
    """Build an AnnotationStore backed by a temporary SQLite file."""
    engine = sa.create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    METADATA.create_all(engine)
    sf = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return AnnotationStore(session_factory=sf)


def test_table_initialization(tmp_path: Path) -> None:
    """Tables are created when the store is initialized."""
    _make_store(tmp_path / "ann.db")


def test_create_and_get_annotation(tmp_path: Path) -> None:
    """Annotations can be created and retrieved."""
    store = _make_store(tmp_path / "ann.db")

    aid = store.create_annotation(
        target_type="entity",
        target_id="wallet:0xAAA",
        content="Suspicious activity detected",
        author="analyst@test.com",
    )
    assert aid

    annotation = store.get_annotation(aid)
    assert annotation is not None
    assert annotation["target_type"] == "entity"
    assert annotation["target_id"] == "wallet:0xAAA"
    assert annotation["content"] == "Suspicious activity detected"
    assert annotation["author"] == "analyst@test.com"
    assert annotation["created_at"] is not None


def test_get_annotation_not_found(tmp_path: Path) -> None:
    """Getting a non-existent annotation returns None."""
    store = _make_store(tmp_path / "ann.db")
    assert store.get_annotation("nonexistent") is None


def test_list_annotations_unfiltered(tmp_path: Path) -> None:
    """List all annotations without filters."""
    store = _make_store(tmp_path / "ann.db")
    store.create_annotation(target_type="entity", target_id="a", content="note 1")
    store.create_annotation(target_type="indicator", target_id="b", content="note 2")
    store.create_annotation(target_type="case", target_id="c", content="note 3")

    results = store.list_annotations()
    assert len(results) == 3


def test_list_annotations_filter_by_target_type(tmp_path: Path) -> None:
    """List annotations filtered by target type."""
    store = _make_store(tmp_path / "ann.db")
    store.create_annotation(target_type="entity", target_id="a", content="note 1")
    store.create_annotation(target_type="indicator", target_id="b", content="note 2")

    results = store.list_annotations(target_type="entity")
    assert len(results) == 1
    assert results[0]["target_type"] == "entity"


def test_list_annotations_filter_by_target_id(tmp_path: Path) -> None:
    """List annotations filtered by target ID."""
    store = _make_store(tmp_path / "ann.db")
    store.create_annotation(target_type="entity", target_id="wallet:0xAAA", content="note 1")
    store.create_annotation(target_type="entity", target_id="wallet:0xBBB", content="note 2")

    results = store.list_annotations(target_id="wallet:0xAAA")
    assert len(results) == 1
    assert results[0]["target_id"] == "wallet:0xAAA"


def test_list_annotations_limit(tmp_path: Path) -> None:
    """List respects the limit parameter."""
    store = _make_store(tmp_path / "ann.db")
    for i in range(5):
        store.create_annotation(target_type="entity", target_id=f"e{i}", content=f"note {i}")

    results = store.list_annotations(limit=3)
    assert len(results) == 3


def test_update_annotation(tmp_path: Path) -> None:
    """Annotation content can be updated."""
    store = _make_store(tmp_path / "ann.db")
    aid = store.create_annotation(target_type="entity", target_id="a", content="original")

    success = store.update_annotation(aid, content="updated text")
    assert success is True

    updated = store.get_annotation(aid)
    assert updated["content"] == "updated text"


def test_update_annotation_not_found(tmp_path: Path) -> None:
    """Updating a non-existent annotation returns False."""
    store = _make_store(tmp_path / "ann.db")
    assert store.update_annotation("nonexistent", content="x") is False


def test_delete_annotation(tmp_path: Path) -> None:
    """Annotations can be deleted."""
    store = _make_store(tmp_path / "ann.db")
    aid = store.create_annotation(target_type="entity", target_id="a", content="to delete")

    success = store.delete_annotation(aid)
    assert success is True
    assert store.get_annotation(aid) is None


def test_delete_annotation_not_found(tmp_path: Path) -> None:
    """Deleting a non-existent annotation returns False."""
    store = _make_store(tmp_path / "ann.db")
    assert store.delete_annotation("nonexistent") is False


def test_list_annotations_ordered_by_created_at(tmp_path: Path) -> None:
    """List returns annotations in reverse chronological order."""
    store = _make_store(tmp_path / "ann.db")
    aid1 = store.create_annotation(target_type="entity", target_id="a", content="first")
    aid2 = store.create_annotation(target_type="entity", target_id="b", content="second")

    results = store.list_annotations()
    # Most recent first
    assert results[0]["annotation_id"] == aid2
    assert results[1]["annotation_id"] == aid1
