from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    with patch("i4g.api.auth.require_token", return_value={"sub": "test@test.com", "role": "admin"}):
        from i4g.api.app import create_app

        app = create_app()
        return TestClient(app)


def test_dashboard_overview_metrics(client, monkeypatch):
    """Test that /dashboard/overview returns the required metrics."""
    with patch("i4g.api.dashboard.get_db_session") as mock_get_session:
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        # Mock scalar to return something reasonable
        mock_session.scalar.return_value = 10
        # Mock execute.all to return empty lists for alerts/activities to simplify test
        mock_session.execute.return_value.all.return_value = []

        # We need to override the dependency in the app
        from i4g.api.review_deps import get_db_session

        client.app.dependency_overrides[get_db_session] = lambda: mock_session

        response = client.get("/dashboard/overview")
        assert response.status_code == 200
        data = response.json()

        assert "metrics" in data
        assert "alerts" in data

        # Verify the new metrics are present
        metric_labels = [m["label"] for m in data["metrics"]]
        assert "Engagement completion" in metric_labels
        assert "Loss linkages" in metric_labels
        assert "Avg Campaign Risk" in metric_labels

        client.app.dependency_overrides = {}
