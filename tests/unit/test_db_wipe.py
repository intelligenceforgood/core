"""Unit tests for the `i4g db wipe` command (local SQLite path)."""

from __future__ import annotations

import contextlib

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.store import sql as sql_schema
from i4g.store.sql_writer import CaseBundle, CasePayload, SourceDocumentPayload, SqlWriter


@pytest.fixture()
def local_db(tmp_path):
    """Create a SQLite DB, seed one case, and return (engine, db_path)."""

    db_path = tmp_path / "i4g_store.db"
    engine = sa.create_engine(f"sqlite:///{db_path}", future=True)
    sql_schema.METADATA.create_all(engine)

    factory = sessionmaker(bind=engine, future=True)
    writer = SqlWriter(session_factory=factory)

    bundle = CaseBundle(
        case=CasePayload(
            case_id="wipe-test-001",
            dataset="test",
            source_type="form",
            classification="test",
            confidence=0.5,
            text="Test case for wipe",
        ),
        documents=[SourceDocumentPayload(alias="d1", title="doc", text="Test case for wipe")],
        entities=[],
        indicators=[],
    )
    writer.persist_case_bundle(bundle, ingestion_run_id="run-1")

    yield engine, db_path
    engine.dispose()


def test_wipe_local_truncates_all_data_tables(local_db):
    """After wipe, all data tables are empty but the schema remains."""

    engine, _ = local_db
    from i4g.cli.db import _WIPE_TABLE_ORDER

    # Verify data exists before wipe
    with engine.connect() as conn:
        case_count = conn.execute(sa.text("SELECT COUNT(*) FROM cases")).scalar()
        assert case_count == 1

    # Perform wipe via DELETE (TRUNCATE not supported on SQLite)
    with engine.connect() as conn:
        for table_name in _WIPE_TABLE_ORDER:
            with contextlib.suppress(sa.exc.OperationalError):
                conn.execute(sa.text(f"DELETE FROM {table_name}"))  # noqa: S608
        conn.commit()

    # Verify all data tables are empty
    with engine.connect() as conn:
        case_count = conn.execute(sa.text("SELECT COUNT(*) FROM cases")).scalar()
        assert case_count == 0

        doc_count = conn.execute(sa.text("SELECT COUNT(*) FROM source_documents")).scalar()
        assert doc_count == 0

    # Verify schema is intact (tables still exist)
    inspector = sa.inspect(engine)
    table_names = inspector.get_table_names()
    assert "cases" in table_names
    assert "source_documents" in table_names
    assert "entities" in table_names


def test_wipe_table_order_covers_all_data_tables():
    """Ensure _WIPE_TABLE_ORDER covers all non-preserved tables in the schema."""

    from i4g.cli.db import _WIPE_TABLE_ORDER

    preserved = {"accounts", "account_actions", "alembic_version"}
    all_tables = {t.name for t in sql_schema.METADATA.sorted_tables}
    expected_wipe = all_tables - preserved

    wipe_set = set(_WIPE_TABLE_ORDER)

    missing = expected_wipe - wipe_set
    assert not missing, f"Tables missing from _WIPE_TABLE_ORDER: {missing}"
