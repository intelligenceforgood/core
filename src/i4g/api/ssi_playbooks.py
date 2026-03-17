"""SSI playbook CRUD and URL-matching endpoints.

Provides REST endpoints for managing investigation playbooks — deterministic
action scripts that the SSI browser agent executes against known scam-site
patterns.

* ``GET    /playbooks/ssi``              — list all playbooks
* ``GET    /playbooks/ssi/{playbook_id}`` — retrieve a single playbook
* ``POST   /playbooks/ssi``              — create a new playbook
* ``PUT    /playbooks/ssi/{playbook_id}`` — update an existing playbook
* ``DELETE /playbooks/ssi/{playbook_id}`` — delete a playbook
* ``POST   /playbooks/ssi/test-match``   — test a URL against patterns

Playbooks are stored as JSON files on disk, following the same file-based
approach used by the SSI FastAPI app.  The directory is configured
via ``settings.ssi.playbook_dir`` (env: ``SSI_PLAYBOOK_DIR``).
"""

from __future__ import annotations

import json
import logging
import re
from enum import StrEnum
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from i4g.api.auth import require_role, require_token
from i4g.api.camel import CamelModel
from i4g.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/playbooks/ssi",
    tags=["ssi", "playbooks"],
    dependencies=[Depends(require_token)],
)


# ---------------------------------------------------------------------------
# Playbook models (self-contained — no SSI imports)
# ---------------------------------------------------------------------------


class PlaybookStepType(StrEnum):
    """Action types a playbook step can perform."""

    CLICK = "click"
    TYPE = "type"
    SELECT = "select"
    NAVIGATE = "navigate"
    WAIT = "wait"
    SCROLL = "scroll"
    EXTRACT = "extract"


class PlaybookStep(BaseModel):
    """Single deterministic step in a playbook."""

    action: PlaybookStepType
    selector: str = ""
    value: str = ""
    description: str = ""
    retry_on_failure: int = Field(default=0, ge=0, le=10)
    fallback_to_llm: bool = Field(default=True)


class PlaybookSchema(BaseModel):
    """Full playbook definition used for create/update request bodies.

    Field names use ``snake_case`` internally (matching the JSON files on
    disk).  Response serialisation uses ``CamelModel`` subclasses.
    """

    playbook_id: str = Field(..., pattern=r"^[a-z0-9_]+$")
    url_pattern: str
    description: str = ""
    steps: list[PlaybookStep] = Field(..., min_length=1)
    fallback_to_llm: bool = Field(default=True)
    max_duration_sec: int = Field(default=120, ge=10, le=600)
    author: str = ""
    version: str = "1.0"
    tested_urls: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("url_pattern")
    @classmethod
    def _validate_regex(cls, v: str) -> str:
        """Ensure ``url_pattern`` is a compilable regex."""
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"Invalid regex in url_pattern: {exc}") from exc
        return v


# ---------------------------------------------------------------------------
# Response models (camelCase on the wire)
# ---------------------------------------------------------------------------


class PlaybookSummaryResponse(CamelModel):
    """Lightweight playbook summary returned by the list endpoint."""

    playbook_id: str
    url_pattern: str
    description: str = ""
    steps_count: int
    enabled: bool
    version: str = "1.0"
    tags: list[str] = Field(default_factory=list)


class PlaybookDetailResponse(CamelModel):
    """Full playbook detail returned by GET and mutating endpoints."""

    playbook_id: str
    url_pattern: str
    description: str = ""
    steps: list[dict[str, Any]]
    fallback_to_llm: bool = True
    max_duration_sec: int = 120
    author: str = ""
    version: str = "1.0"
    tested_urls: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True


class TestMatchRequest(BaseModel):
    """Request body for the test-match endpoint."""

    url: str = Field(..., description="URL to test against all playbook patterns.")


class TestMatchResponse(CamelModel):
    """Result of testing a URL against registered playbook patterns."""

    matched: bool
    playbook_id: str | None = None
    playbook_description: str | None = None
    url_pattern: str | None = None


# ---------------------------------------------------------------------------
# File-system helpers
# ---------------------------------------------------------------------------


def _get_playbook_dir() -> Path:
    """Return the resolved playbook directory from settings.

    Returns:
        Absolute ``Path`` to the playbook directory.
    """
    return Path(get_settings().ssi.playbook_dir)


def _load_all(pb_dir: Path) -> list[dict[str, Any]]:
    """Load all playbook JSON files from *pb_dir*.

    Args:
        pb_dir: Directory containing ``*.json`` playbook files.

    Returns:
        List of raw playbook dicts, sorted by filename.
    """
    if not pb_dir.is_dir():
        logger.warning("Playbook directory does not exist: %s", pb_dir)
        return []
    playbooks: list[dict[str, Any]] = []
    for json_file in sorted(pb_dir.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            playbooks.append(data)
        except Exception:
            logger.exception("Failed to load playbook from %s", json_file)
    return playbooks


def _load_one(pb_dir: Path, playbook_id: str) -> dict[str, Any] | None:
    """Load a single playbook by ID from disk.

    Args:
        pb_dir: Playbook directory.
        playbook_id: The playbook identifier (also the filename stem).

    Returns:
        Playbook dict or ``None`` if the file does not exist.
    """
    pb_file = pb_dir / f"{playbook_id}.json"
    if not pb_file.exists():
        return None
    return json.loads(pb_file.read_text(encoding="utf-8"))


def _match_url(playbooks: list[dict[str, Any]], url: str) -> dict[str, Any] | None:
    """Return the first enabled playbook whose ``url_pattern`` matches *url*.

    Args:
        playbooks: List of playbook dicts to test.
        url: URL to match against patterns.

    Returns:
        The matching playbook dict, or ``None``.
    """
    for pb in playbooks:
        if not pb.get("enabled", True):
            continue
        pattern = pb.get("url_pattern", "")
        try:
            if re.search(pattern, url, re.IGNORECASE):
                return pb
        except re.error:
            logger.warning("Bad regex in playbook %s: %s", pb.get("playbook_id"), pattern)
    return None


def _playbook_to_detail(pb: dict[str, Any]) -> dict[str, Any]:
    """Normalise a raw playbook dict into the detail response shape.

    Args:
        pb: Raw playbook dict loaded from JSON.

    Returns:
        Dict matching ``PlaybookDetailResponse`` fields.
    """
    return {
        "playbook_id": pb.get("playbook_id", ""),
        "url_pattern": pb.get("url_pattern", ""),
        "description": pb.get("description", ""),
        "steps": pb.get("steps", []),
        "fallback_to_llm": pb.get("fallback_to_llm", True),
        "max_duration_sec": pb.get("max_duration_sec", 120),
        "author": pb.get("author", ""),
        "version": pb.get("version", "1.0"),
        "tested_urls": pb.get("tested_urls", []),
        "tags": pb.get("tags", []),
        "enabled": pb.get("enabled", True),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[PlaybookSummaryResponse])
def list_playbooks(
    _user: dict = Depends(require_role("analyst")),
) -> list[dict[str, Any]]:
    """List all registered SSI playbooks.

    Returns:
        List of playbook summaries with step counts.
    """
    pb_dir = _get_playbook_dir()
    playbooks = _load_all(pb_dir)
    return [
        {
            "playbook_id": pb.get("playbook_id", ""),
            "url_pattern": pb.get("url_pattern", ""),
            "description": pb.get("description", ""),
            "steps_count": len(pb.get("steps", [])),
            "enabled": pb.get("enabled", True),
            "version": pb.get("version", "1.0"),
            "tags": pb.get("tags", []),
        }
        for pb in playbooks
    ]


@router.get("/{playbook_id}", response_model=PlaybookDetailResponse)
def get_playbook(
    playbook_id: str,
    _user: dict = Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Retrieve a single playbook by ID.

    Args:
        playbook_id: The unique playbook identifier.

    Returns:
        Full playbook detail.

    Raises:
        HTTPException: 404 if the playbook does not exist.
    """
    pb_dir = _get_playbook_dir()
    pb = _load_one(pb_dir, playbook_id)
    if pb is None:
        raise HTTPException(status_code=404, detail=f"Playbook '{playbook_id}' not found")
    return _playbook_to_detail(pb)


@router.post("", response_model=PlaybookDetailResponse, status_code=201)
def create_playbook(
    playbook: PlaybookSchema,
    _user: dict = Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Create a new playbook and persist it to disk.

    The playbook JSON file is written as ``{playbook_id}.json`` inside
    the configured playbook directory.

    Args:
        playbook: The full playbook definition.

    Returns:
        The created playbook detail.

    Raises:
        HTTPException: 409 if a playbook with that ID already exists.
    """
    pb_dir = _get_playbook_dir()
    pb_dir.mkdir(parents=True, exist_ok=True)

    pb_file = pb_dir / f"{playbook.playbook_id}.json"
    if pb_file.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Playbook '{playbook.playbook_id}' already exists",
        )

    data = playbook.model_dump()
    pb_file.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    logger.info("Created playbook %s at %s", playbook.playbook_id, pb_file)
    return _playbook_to_detail(data)


@router.put("/{playbook_id}", response_model=PlaybookDetailResponse)
def update_playbook(
    playbook_id: str,
    playbook: PlaybookSchema,
    _user: dict = Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Update an existing playbook on disk.

    Args:
        playbook_id: The playbook identifier from the URL path.
        playbook: The updated playbook definition.

    Returns:
        The updated playbook detail.

    Raises:
        HTTPException: 400 if the path ID does not match the body ID.
        HTTPException: 404 if the playbook does not exist.
    """
    if playbook.playbook_id != playbook_id:
        raise HTTPException(status_code=400, detail="Playbook ID in URL does not match body")

    pb_dir = _get_playbook_dir()
    pb_file = pb_dir / f"{playbook_id}.json"
    if not pb_file.exists():
        raise HTTPException(status_code=404, detail=f"Playbook '{playbook_id}' not found")

    data = playbook.model_dump()
    pb_file.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    logger.info("Updated playbook %s", playbook_id)
    return _playbook_to_detail(data)


@router.delete("/{playbook_id}", status_code=204)
def delete_playbook(
    playbook_id: str,
    _user: dict = Depends(require_role("analyst")),
) -> None:
    """Delete a playbook from disk.

    Args:
        playbook_id: The playbook identifier.

    Raises:
        HTTPException: 404 if the playbook does not exist.
    """
    pb_dir = _get_playbook_dir()
    pb_file = pb_dir / f"{playbook_id}.json"
    if not pb_file.exists():
        raise HTTPException(status_code=404, detail=f"Playbook '{playbook_id}' not found")
    pb_file.unlink()
    logger.info("Deleted playbook %s", playbook_id)


@router.post("/test-match", response_model=TestMatchResponse)
def test_match(
    req: TestMatchRequest,
    _user: dict = Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Test a URL against all registered playbook patterns.

    Returns the first matching playbook (if any).  Disabled playbooks
    are skipped.

    Args:
        req: Request containing the URL to test.

    Returns:
        Match result with playbook details if a match is found.
    """
    pb_dir = _get_playbook_dir()
    playbooks = _load_all(pb_dir)
    matched = _match_url(playbooks, req.url)
    if matched is None:
        return {"matched": False}
    return {
        "matched": True,
        "playbook_id": matched.get("playbook_id"),
        "playbook_description": matched.get("description", ""),
        "url_pattern": matched.get("url_pattern", ""),
    }
