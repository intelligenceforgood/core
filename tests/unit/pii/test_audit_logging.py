"""Test audit logging for PII vault operations."""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from i4g.pii.tokenization import TokenizationService
from i4g.store.pii_token_store import PiiTokenStore


@pytest.fixture
def temp_db(tmp_path):
    return tmp_path / "pii_vault.db"


@pytest.fixture
def store(temp_db):
    return PiiTokenStore(db_path=temp_db)


@pytest.fixture
def service(store):
    # Mock observability to focus on store audit log
    return TokenizationService(
        store=store,
        observability=MagicMock(),
        pepper="test-pepper",
        encryption_key="test-key-must-be-32-bytes-long-encoded-in-base64="
    )


def test_detokenize_logs_access(service, store):
    # 1. Tokenize a value
    result = service.tokenize("sensitive@example.com", "EID")
    token = result.token
    
    # 2. Detokenize
    service.detokenize(token, actor="analyst-alice", case_id="case-123")
    
    # 3. Verify Audit Log
    with store._connect() as conn:
        row = conn.execute("SELECT * FROM audit_log WHERE token = ?", (token,)).fetchone()
        
    assert row is not None
    assert row["actor"] == "analyst-alice"
    assert row["action"] == "detokenize"
    assert row["outcome"] == "success"
    assert row["case_id"] == "case-123"
    assert row["prefix"] == "EID"


def test_detokenize_missing_token_logs_failure(service, store):
    token = "EID-MISSING1"
    
    service.detokenize(token, actor="analyst-bob")
    
    with store._connect() as conn:
        row = conn.execute("SELECT * FROM audit_log WHERE token = ?", (token,)).fetchone()
        
    assert row is not None
    assert row["actor"] == "analyst-bob"
    assert row["action"] == "detokenize"
    assert row["outcome"] == "not_found"
