"""Test audit logging for PII vault operations."""

from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.pii.tokenization import TokenizationService
from i4g.store.pii_token_store_sql import SqlAlchemyPiiTokenStore
from i4g.store.sql import VAULT_METADATA, audit_log


@pytest.fixture
def temp_db(tmp_path):
    return tmp_path / "pii_vault.db"


@pytest.fixture
def vault_session_factory(temp_db):
    engine = sa.create_engine(
        f"sqlite:///{temp_db.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    VAULT_METADATA.create_all(engine, checkfirst=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture
def store(vault_session_factory):
    return SqlAlchemyPiiTokenStore(session_factory=vault_session_factory)


@pytest.fixture
def service(store):
    # Mock observability to focus on store audit log
    return TokenizationService(
        store=store,
        observability=MagicMock(),
        pepper="test-pepper",
        encryption_key="test-key-must-be-32-bytes-long-encoded-in-base64=",
    )


def _query_audit_log(session_factory, token_val):
    """Helper to query audit_log for a specific token."""
    with session_factory() as session:
        row = session.execute(sa.select(audit_log).where(audit_log.c.token == token_val)).fetchone()
        return row._mapping if row else None


def test_detokenize_logs_access(service, store, vault_session_factory):
    # 1. Tokenize a value
    result = service.tokenize("sensitive@example.com", "EID")
    token = result.token

    # 2. Detokenize
    service.detokenize(token, actor="analyst-alice", case_id="case-123")

    # 3. Verify Audit Log
    row = _query_audit_log(vault_session_factory, token)

    assert row is not None
    assert row["actor"] == "analyst-alice"
    assert row["action"] == "detokenize"
    assert row["outcome"] == "success"
    assert row["case_id"] == "case-123"
    assert row["prefix"] == "EID"


def test_detokenize_missing_token_logs_failure(service, store, vault_session_factory):
    token = "EID-MISSING1"

    service.detokenize(token, actor="analyst-bob")

    row = _query_audit_log(vault_session_factory, token)

    assert row is not None
    assert row["actor"] == "analyst-bob"
    assert row["action"] == "detokenize"
    assert row["outcome"] == "not_found"
