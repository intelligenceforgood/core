"""
Unit tests for SqlAlchemyStructuredStore in i4g.store.structured.
"""
import pytest
from unittest.mock import MagicMock, patch
import sqlalchemy as sa
from i4g.store.structured import SqlAlchemyStructuredStore
from i4g.settings import Settings

@pytest.fixture
def mock_settings():
    with patch("i4g.store.structured.get_settings") as mock_get:
        settings = MagicMock(spec=Settings)
        settings.storage = MagicMock()
        settings.storage.structured_backend = "cloudsql"
        settings.secrets = MagicMock()
        settings.secrets.project = "test-project"
        mock_get.return_value = settings
        yield settings

def test_init_rollback_on_set_role_failure(mock_settings):
    """Test that conn.rollback() is called when SET ROLE fails."""
    mock_session = MagicMock()
    mock_conn = MagicMock()
    mock_session.connection.return_value = mock_conn
    
    # Setup context manager for session
    mock_session.__enter__.return_value = mock_session
    mock_session.__exit__.return_value = None
    
    mock_session_factory = MagicMock(return_value=mock_session)

    # Simulate SET ROLE failure
    def execute_side_effect(statement, *args, **kwargs):
        stmt_str = str(statement)
        if "SET ROLE postgres" in stmt_str:
            raise Exception("Permission denied")
        return MagicMock()

    mock_conn.execute.side_effect = execute_side_effect

    # Mock create_all to avoid actual DB calls
    with patch("i4g.store.sql.METADATA.create_all") as mock_create_all:
        store = SqlAlchemyStructuredStore(session_factory=mock_session_factory)

    # Verify rollback was called
    mock_conn.rollback.assert_called_once()
    
    # Verify create_all was still called
    mock_create_all.assert_called_once_with(mock_conn)

def test_init_success(mock_settings):
    """Test that SET ROLE and RESET ROLE are called on success."""
    mock_session = MagicMock()
    mock_conn = MagicMock()
    mock_session.connection.return_value = mock_conn
    
    mock_session.__enter__.return_value = mock_session
    mock_session.__exit__.return_value = None
    
    mock_session_factory = MagicMock(return_value=mock_session)

    # Mock create_all
    with patch("i4g.store.sql.METADATA.create_all") as mock_create_all:
        store = SqlAlchemyStructuredStore(session_factory=mock_session_factory)

    # Verify SET ROLE and RESET ROLE were called
    calls = mock_conn.execute.call_args_list
    set_role_called = any("SET ROLE postgres" in str(call[0][0]) for call in calls)
    reset_role_called = any("RESET ROLE" in str(call[0][0]) for call in calls)
    
    assert set_role_called
    assert reset_role_called
    
    # Verify create_all was called
    mock_create_all.assert_called_once_with(mock_conn)
