"""
Unit tests for StructuredStore (unified SQLAlchemy implementation).
"""

from unittest.mock import MagicMock, patch

from i4g.store.structured import SqlAlchemyStructuredStore, StructuredStore


def test_sqlalchemy_alias():
    """SqlAlchemyStructuredStore is a backward-compatible alias."""
    assert SqlAlchemyStructuredStore is StructuredStore


def test_init_with_session_factory():
    """StructuredStore accepts a pre-configured session_factory."""
    mock_session = MagicMock()
    mock_conn = MagicMock()
    mock_session.connection.return_value = mock_conn
    mock_session.bind.dialect.name = "sqlite"
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=None)

    mock_factory = MagicMock(return_value=mock_session)

    with patch("i4g.store.sql.METADATA.create_all") as mock_create_all:
        StructuredStore(session_factory=mock_factory)

    mock_create_all.assert_called_once_with(mock_conn)


def test_init_skips_create_all_for_postgresql():
    """StructuredStore skips create_all when dialect is not SQLite."""
    mock_session = MagicMock()
    mock_session.bind.dialect.name = "postgresql"
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=None)

    mock_factory = MagicMock(return_value=mock_session)

    with patch("i4g.store.sql.METADATA.create_all") as mock_create_all:
        StructuredStore(session_factory=mock_factory)

    mock_create_all.assert_not_called()
