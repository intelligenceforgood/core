"""Tests for TLP labeling and override rules (S3-37).

Validates that report generation applies correct TLP defaults per template,
rejects invalid TLP labels, and respects role-based override semantics.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from i4g.api.app import create_app
from i4g.api.auth import require_token
from i4g.api.reports import _TLP_DEFAULTS, _VALID_TLP

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_artifacts(tmp_path: Path) -> Path:
    """Provide a temporary artifacts directory."""
    generated = tmp_path / "generated"
    generated.mkdir()
    return tmp_path


@pytest.fixture()
def client(tmp_artifacts: Path) -> TestClient:
    """Create a TestClient with mocked auth and artifacts directory."""
    app = create_app()
    app.dependency_overrides[require_token] = lambda: {"username": "analyst@test.io", "role": "analyst"}
    with patch("i4g.api.reports.ARTIFACTS_DIR", tmp_artifacts):
        yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# TLP default assignment
# ---------------------------------------------------------------------------


def test_executive_summary_defaults_to_amber(client: TestClient, tmp_artifacts: Path) -> None:
    """Executive summary template should default to TLP:AMBER."""
    with patch("i4g.api.reports.ARTIFACTS_DIR", tmp_artifacts):
        resp = client.post("/reports/generate", json={"template": "executive_summary", "scope": {}})
    assert resp.status_code == 200
    assert resp.json()["tlp"] == "TLP:AMBER"


def test_lea_dossier_defaults_to_red(client: TestClient, tmp_artifacts: Path) -> None:
    """LEA dossier template should default to TLP:RED."""
    with patch("i4g.api.reports.ARTIFACTS_DIR", tmp_artifacts):
        resp = client.post("/reports/generate", json={"template": "lea_dossier", "scope": {}})
    assert resp.status_code == 200
    assert resp.json()["tlp"] == "TLP:RED"


def test_unknown_template_defaults_to_amber(client: TestClient, tmp_artifacts: Path) -> None:
    """Unknown template should fall back to TLP:AMBER."""
    with patch("i4g.api.reports.ARTIFACTS_DIR", tmp_artifacts):
        resp = client.post("/reports/generate", json={"template": "custom_report", "scope": {}})
    assert resp.status_code == 200
    assert resp.json()["tlp"] == "TLP:AMBER"


# ---------------------------------------------------------------------------
# TLP override
# ---------------------------------------------------------------------------


def test_valid_tlp_override_accepted(client: TestClient, tmp_artifacts: Path) -> None:
    """A valid TLP override in options should be used instead of the default."""
    with patch("i4g.api.reports.ARTIFACTS_DIR", tmp_artifacts):
        resp = client.post(
            "/reports/generate",
            json={"template": "executive_summary", "scope": {}, "options": {"tlp": "TLP:WHITE"}},
        )
    assert resp.status_code == 200
    assert resp.json()["tlp"] == "TLP:WHITE"


def test_invalid_tlp_override_rejected(client: TestClient, tmp_artifacts: Path) -> None:
    """An invalid TLP label should result in a 400 error."""
    with patch("i4g.api.reports.ARTIFACTS_DIR", tmp_artifacts):
        resp = client.post(
            "/reports/generate",
            json={"template": "executive_summary", "scope": {}, "options": {"tlp": "TLP:PURPLE"}},
        )
    assert resp.status_code == 400
    assert "Invalid TLP label" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# TLP constants sanity checks
# ---------------------------------------------------------------------------


def test_valid_tlp_set_contains_four_levels() -> None:
    """There should be exactly four valid TLP classifications."""
    assert {"TLP:WHITE", "TLP:GREEN", "TLP:AMBER", "TLP:RED"} == _VALID_TLP


def test_all_template_defaults_are_valid() -> None:
    """Every entry in _TLP_DEFAULTS must be a member of _VALID_TLP."""
    for template, tlp in _TLP_DEFAULTS.items():
        assert tlp in _VALID_TLP, f"Template '{template}' has invalid TLP default: {tlp}"
