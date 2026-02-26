"""Unit tests for SSI playbook endpoints (Phase C.4).

Tests use a temporary directory for playbook JSON files, patching
``_get_playbook_dir`` in the playbook router so they never touch the
real playbook directory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import i4g.api.app as app_module
from i4g.api.app import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Rate limit reset
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    """Clear the in-memory rate limit log before and after each test."""
    app_module.REQUEST_LOG.clear()
    yield
    app_module.REQUEST_LOG.clear()

# ---------------------------------------------------------------------------
# Sample playbook data
# ---------------------------------------------------------------------------

_SAMPLE_STEP = {
    "action": "click",
    "selector": "#signup-btn",
    "value": "",
    "description": "Click signup button",
    "retry_on_failure": 0,
    "fallback_to_llm": True,
}

_SAMPLE_PLAYBOOK: dict[str, Any] = {
    "playbook_id": "test_playbook_v1",
    "url_pattern": r"scam\.example\.com",
    "description": "Test playbook",
    "steps": [_SAMPLE_STEP],
    "fallback_to_llm": True,
    "max_duration_sec": 120,
    "author": "tester",
    "version": "1.0",
    "tested_urls": ["https://scam.example.com"],
    "tags": ["test"],
    "enabled": True,
}

_SECOND_PLAYBOOK: dict[str, Any] = {
    "playbook_id": "phishing_v1",
    "url_pattern": r"phish\.example\.com",
    "description": "Phishing playbook",
    "steps": [
        {"action": "type", "selector": "#email", "value": "{identity.email}"},
        {"action": "click", "selector": "#submit"},
    ],
    "enabled": True,
    "tags": ["phishing"],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _playbook_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect playbook storage to a temporary directory."""
    pb_dir = tmp_path / "playbooks"
    pb_dir.mkdir()
    monkeypatch.setattr("i4g.api.ssi_playbooks._get_playbook_dir", lambda: pb_dir)
    return pb_dir


@pytest.fixture()
def playbook_dir(_playbook_dir: Path) -> Path:
    """Convenience alias for the temp playbook directory."""
    return _playbook_dir


def _write_playbook(pb_dir: Path, data: dict[str, Any]) -> Path:
    """Write a playbook JSON file and return the file path."""
    pb_file = pb_dir / f"{data['playbook_id']}.json"
    pb_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return pb_file


# =========================================================================
# GET /playbooks/ssi — list playbooks
# =========================================================================


class TestListPlaybooks:
    """Tests for ``GET /playbooks/ssi``."""

    def test_empty_list(self) -> None:
        """Empty directory returns empty list."""
        resp = client.get("/playbooks/ssi")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_summaries(self, playbook_dir: Path) -> None:
        """Playbooks on disk appear in the summary list."""
        _write_playbook(playbook_dir, _SAMPLE_PLAYBOOK)
        _write_playbook(playbook_dir, _SECOND_PLAYBOOK)

        resp = client.get("/playbooks/ssi")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

        ids = {pb["playbookId"] for pb in data}
        assert ids == {"test_playbook_v1", "phishing_v1"}

    def test_summary_has_step_count(self, playbook_dir: Path) -> None:
        """Summary includes the correct step count."""
        _write_playbook(playbook_dir, _SECOND_PLAYBOOK)
        resp = client.get("/playbooks/ssi")
        data = resp.json()
        pb = data[0]
        assert pb["stepsCount"] == 2

    def test_summary_fields(self, playbook_dir: Path) -> None:
        """Summary contains expected camelCase fields."""
        _write_playbook(playbook_dir, _SAMPLE_PLAYBOOK)
        resp = client.get("/playbooks/ssi")
        pb = resp.json()[0]
        expected_keys = {"playbookId", "urlPattern", "description", "stepsCount", "enabled", "version", "tags"}
        assert expected_keys <= set(pb.keys())

    def test_skips_malformed_files(self, playbook_dir: Path) -> None:
        """Malformed JSON files are skipped without crashing."""
        (playbook_dir / "bad.json").write_text("not json", encoding="utf-8")
        _write_playbook(playbook_dir, _SAMPLE_PLAYBOOK)
        resp = client.get("/playbooks/ssi")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


# =========================================================================
# GET /playbooks/ssi/{playbook_id} — get detail
# =========================================================================


class TestGetPlaybook:
    """Tests for ``GET /playbooks/ssi/{playbook_id}``."""

    def test_not_found(self) -> None:
        """Non-existent playbook returns 404."""
        resp = client.get("/playbooks/ssi/no_such_playbook")
        assert resp.status_code == 404

    def test_returns_detail(self, playbook_dir: Path) -> None:
        """Existing playbook returns full detail."""
        _write_playbook(playbook_dir, _SAMPLE_PLAYBOOK)
        resp = client.get("/playbooks/ssi/test_playbook_v1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["playbookId"] == "test_playbook_v1"
        assert data["urlPattern"] == r"scam\.example\.com"
        assert len(data["steps"]) == 1

    def test_detail_includes_metadata(self, playbook_dir: Path) -> None:
        """Detail includes author, version, tags, and tested URLs."""
        _write_playbook(playbook_dir, _SAMPLE_PLAYBOOK)
        resp = client.get("/playbooks/ssi/test_playbook_v1")
        data = resp.json()
        assert data["author"] == "tester"
        assert data["version"] == "1.0"
        assert data["tags"] == ["test"]
        assert data["testedUrls"] == ["https://scam.example.com"]


# =========================================================================
# POST /playbooks/ssi — create playbook
# =========================================================================


class TestCreatePlaybook:
    """Tests for ``POST /playbooks/ssi``."""

    def test_create_success(self, playbook_dir: Path) -> None:
        """Creating a new playbook returns 201 and persists to disk."""
        resp = client.post("/playbooks/ssi", json=_SAMPLE_PLAYBOOK)
        assert resp.status_code == 201
        data = resp.json()
        assert data["playbookId"] == "test_playbook_v1"

        # Verify file written
        pb_file = playbook_dir / "test_playbook_v1.json"
        assert pb_file.exists()
        on_disk = json.loads(pb_file.read_text())
        assert on_disk["playbook_id"] == "test_playbook_v1"

    def test_create_conflict(self, playbook_dir: Path) -> None:
        """Creating a playbook with an existing ID returns 409."""
        _write_playbook(playbook_dir, _SAMPLE_PLAYBOOK)
        resp = client.post("/playbooks/ssi", json=_SAMPLE_PLAYBOOK)
        assert resp.status_code == 409

    def test_create_invalid_id(self) -> None:
        """Playbook ID with invalid characters is rejected."""
        bad_pb = {**_SAMPLE_PLAYBOOK, "playbook_id": "INVALID-ID!"}
        resp = client.post("/playbooks/ssi", json=bad_pb)
        assert resp.status_code == 422

    def test_create_invalid_regex(self) -> None:
        """Invalid regex in url_pattern is rejected."""
        bad_pb = {**_SAMPLE_PLAYBOOK, "url_pattern": "[invalid"}
        resp = client.post("/playbooks/ssi", json=bad_pb)
        assert resp.status_code == 422

    def test_create_no_steps(self) -> None:
        """Playbook with empty steps is rejected."""
        bad_pb = {**_SAMPLE_PLAYBOOK, "steps": []}
        resp = client.post("/playbooks/ssi", json=bad_pb)
        assert resp.status_code == 422

    def test_create_creates_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Playbook directory is created if it does not exist."""
        new_dir = tmp_path / "new_playbooks"
        monkeypatch.setattr("i4g.api.ssi_playbooks._get_playbook_dir", lambda: new_dir)
        resp = client.post("/playbooks/ssi", json=_SAMPLE_PLAYBOOK)
        assert resp.status_code == 201
        assert new_dir.exists()


# =========================================================================
# PUT /playbooks/ssi/{playbook_id} — update playbook
# =========================================================================


class TestUpdatePlaybook:
    """Tests for ``PUT /playbooks/ssi/{playbook_id}``."""

    def test_update_success(self, playbook_dir: Path) -> None:
        """Updating an existing playbook replaces its content."""
        _write_playbook(playbook_dir, _SAMPLE_PLAYBOOK)
        updated = {**_SAMPLE_PLAYBOOK, "description": "Updated description"}
        resp = client.put("/playbooks/ssi/test_playbook_v1", json=updated)
        assert resp.status_code == 200
        assert resp.json()["description"] == "Updated description"

        on_disk = json.loads((playbook_dir / "test_playbook_v1.json").read_text())
        assert on_disk["description"] == "Updated description"

    def test_update_not_found(self) -> None:
        """Updating a non-existent playbook returns 404."""
        resp = client.put("/playbooks/ssi/no_such", json={**_SAMPLE_PLAYBOOK, "playbook_id": "no_such"})
        assert resp.status_code == 404

    def test_update_id_mismatch(self, playbook_dir: Path) -> None:
        """Path ID not matching body ID returns 400."""
        _write_playbook(playbook_dir, _SAMPLE_PLAYBOOK)
        resp = client.put("/playbooks/ssi/test_playbook_v1", json=_SECOND_PLAYBOOK)
        assert resp.status_code == 400

    def test_update_invalid_regex(self, playbook_dir: Path) -> None:
        """Invalid regex on update is rejected."""
        _write_playbook(playbook_dir, _SAMPLE_PLAYBOOK)
        bad = {**_SAMPLE_PLAYBOOK, "url_pattern": "[bad"}
        resp = client.put("/playbooks/ssi/test_playbook_v1", json=bad)
        assert resp.status_code == 422


# =========================================================================
# DELETE /playbooks/ssi/{playbook_id} — delete playbook
# =========================================================================


class TestDeletePlaybook:
    """Tests for ``DELETE /playbooks/ssi/{playbook_id}``."""

    def test_delete_success(self, playbook_dir: Path) -> None:
        """Deleting an existing playbook removes the file."""
        _write_playbook(playbook_dir, _SAMPLE_PLAYBOOK)
        resp = client.delete("/playbooks/ssi/test_playbook_v1")
        assert resp.status_code == 204
        assert not (playbook_dir / "test_playbook_v1.json").exists()

    def test_delete_not_found(self) -> None:
        """Deleting a non-existent playbook returns 404."""
        resp = client.delete("/playbooks/ssi/no_such")
        assert resp.status_code == 404

    def test_delete_then_get_404(self, playbook_dir: Path) -> None:
        """After deletion, GET returns 404."""
        _write_playbook(playbook_dir, _SAMPLE_PLAYBOOK)
        client.delete("/playbooks/ssi/test_playbook_v1")
        resp = client.get("/playbooks/ssi/test_playbook_v1")
        assert resp.status_code == 404


# =========================================================================
# POST /playbooks/ssi/test-match — URL pattern matching
# =========================================================================


class TestPlaybookMatch:
    """Tests for ``POST /playbooks/ssi/test-match``."""

    def test_no_match(self) -> None:
        """No playbooks loaded returns no match."""
        resp = client.post("/playbooks/ssi/test-match", json={"url": "https://example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["matched"] is False
        assert data["playbookId"] is None

    def test_match_found(self, playbook_dir: Path) -> None:
        """URL matching a playbook pattern returns its details."""
        _write_playbook(playbook_dir, _SAMPLE_PLAYBOOK)
        resp = client.post(
            "/playbooks/ssi/test-match",
            json={"url": "https://scam.example.com/deposit"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["matched"] is True
        assert data["playbookId"] == "test_playbook_v1"
        assert data["urlPattern"] == r"scam\.example\.com"

    def test_match_first_wins(self, playbook_dir: Path) -> None:
        """First matching playbook (alphabetical file order) wins."""
        # "a_first" sorts before "b_second"
        pb_a = {**_SAMPLE_PLAYBOOK, "playbook_id": "a_first", "url_pattern": "example"}
        pb_b = {**_SECOND_PLAYBOOK, "playbook_id": "b_second", "url_pattern": "example"}
        _write_playbook(playbook_dir, pb_a)
        _write_playbook(playbook_dir, pb_b)
        resp = client.post(
            "/playbooks/ssi/test-match",
            json={"url": "https://example.com"},
        )
        assert resp.json()["playbookId"] == "a_first"

    def test_disabled_playbook_skipped(self, playbook_dir: Path) -> None:
        """Disabled playbooks are not matched."""
        disabled = {**_SAMPLE_PLAYBOOK, "enabled": False}
        _write_playbook(playbook_dir, disabled)
        resp = client.post(
            "/playbooks/ssi/test-match",
            json={"url": "https://scam.example.com"},
        )
        assert resp.json()["matched"] is False

    def test_match_missing_url_field(self) -> None:
        """Missing 'url' field returns 422."""
        resp = client.post("/playbooks/ssi/test-match", json={})
        assert resp.status_code == 422


# =========================================================================
# Full CRUD lifecycle
# =========================================================================


class TestPlaybookLifecycle:
    """End-to-end CRUD lifecycle test."""

    def test_create_list_update_delete(self, playbook_dir: Path) -> None:
        """Full lifecycle: create → list → get → update → delete."""
        # Create
        resp = client.post("/playbooks/ssi", json=_SAMPLE_PLAYBOOK)
        assert resp.status_code == 201

        # List
        resp = client.get("/playbooks/ssi")
        assert len(resp.json()) == 1

        # Get
        resp = client.get("/playbooks/ssi/test_playbook_v1")
        assert resp.status_code == 200
        assert resp.json()["description"] == "Test playbook"

        # Update
        updated = {**_SAMPLE_PLAYBOOK, "description": "Updated"}
        resp = client.put("/playbooks/ssi/test_playbook_v1", json=updated)
        assert resp.status_code == 200
        assert resp.json()["description"] == "Updated"

        # Verify update persisted
        resp = client.get("/playbooks/ssi/test_playbook_v1")
        assert resp.json()["description"] == "Updated"

        # Delete
        resp = client.delete("/playbooks/ssi/test_playbook_v1")
        assert resp.status_code == 204

        # Verify gone
        resp = client.get("/playbooks/ssi")
        assert resp.json() == []
