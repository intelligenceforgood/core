"""Shared Pydantic response models for API endpoints.

Provides typed response schemas that FastAPI uses for OpenAPI documentation
and runtime validation.  Keep models thin -- they describe the *shape* of
the JSON the server returns, not domain/business logic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import Field

from i4g.api.camel import CamelModel


# ---------------------------------------------------------------------------
# Generic / reusable envelopes
# ---------------------------------------------------------------------------


class ItemListResponse(CamelModel):
    """Paginated list wrapper used by several list endpoints."""

    items: List[Dict[str, Any]]
    count: int


class EventListResponse(CamelModel):
    """Wrapper for event/action history lists."""

    events: List[Dict[str, Any]]
    count: int


class IdResponse(CamelModel):
    """Single-ID confirmation used by create / share / import endpoints."""

    search_id: str


class MutationResponse(CamelModel):
    """Generic update/delete confirmation."""

    updated: Optional[bool] = None
    deleted: Optional[bool] = None
    search_id: Optional[str] = None


class BulkTagResponse(CamelModel):
    """Result of a bulk tag update."""

    updated: int


# ---------------------------------------------------------------------------
# Task status (app.py)
# ---------------------------------------------------------------------------


class TaskStatusResponse(CamelModel):
    """Background task status."""

    task_id: str
    status: str
    message: Optional[str] = None


class TaskUpdateResponse(CamelModel):
    """Confirmation of a task status update."""

    task_id: str
    updated: bool


class ReportTriggerResponse(CamelModel):
    """Result of triggering report generation."""

    status: str
    task_id: str


# ---------------------------------------------------------------------------
# Review queue (review_queue.py)
# ---------------------------------------------------------------------------


class EnqueueResponse(CamelModel):
    """Result of enqueuing a case for review."""

    review_id: str
    case_id: str


class ClaimResponse(CamelModel):
    """Result of claiming a review."""

    review_id: str
    status: str


class AnnotateResponse(CamelModel):
    """Result of annotating a review."""

    review_id: str
    annotated: bool


class FeedbackResponse(CamelModel):
    """Result of submitting feedback."""

    review_id: str
    feedback_recorded: bool


class DecisionResponse(CamelModel):
    """Result of making a decision on a review."""

    review_id: str
    status: str


# ---------------------------------------------------------------------------
# Review detail (review_detail.py)
# ---------------------------------------------------------------------------


class CaseReviewsResponse(CamelModel):
    """Reviews associated with a case."""

    case_id: str
    reviews: List[Dict[str, Any]]
    count: int


class ActionHistoryResponse(CamelModel):
    """Audit trail for a review."""

    review_id: str
    actions: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Search (review_search.py)
# ---------------------------------------------------------------------------


class SearchResultsResponse(CamelModel):
    """Response from GET /reviews/search."""

    results: List[Dict[str, Any]]
    count: int
    offset: int
    limit: int
    total: int
    vector_hits: Optional[int] = None
    structured_hits: Optional[int] = None
    merged_results: Optional[int] = None
    source_breakdown: Optional[Dict[str, Any]] = None
    diagnostics: Optional[Dict[str, Any]] = None
    search_id: str
    duration_ms: Optional[float] = None


class AdvancedSearchResultsResponse(CamelModel):
    """Response from POST /reviews/search/query.

    Extends the raw hybrid search result with a search_id.
    Uses ``model_config`` to allow extra fields from the search service.
    """

    model_config = {"extra": "allow"}

    search_id: str
    results: Optional[List[Dict[str, Any]]] = None
    count: Optional[int] = None
    total: Optional[int] = None


class SearchSchemaResponse(CamelModel):
    """Dynamic filter schema returned by GET /reviews/search/schema.

    Uses ``extra = "allow"`` because the schema is dynamic.
    """

    model_config = {"extra": "allow"}

    classifications: Optional[List[str]] = None
    campaigns: Optional[List[Dict[str, Any]]] = None


class PresetListResponse(CamelModel):
    """List of tag presets."""

    presets: List[Dict[str, Any]]
    count: int


# ---------------------------------------------------------------------------
# Tokenization (tokenization.py)
# ---------------------------------------------------------------------------


class TokenizeResponse(CamelModel):
    """Result of tokenizing a PII value."""

    token: str
    prefix: str
    digest: str
    normalized_value: str
    pepper_version: int


class DetokenizeResponse(CamelModel):
    """Result of detokenizing a token."""

    token: str
    prefix: str
    canonical_value: str
    pepper_version: int
    case_id: Optional[str] = None
    detector: Optional[str] = None
    created_at: Optional[str] = None


class TokenizationHealthResponse(CamelModel):
    """Tokenization readiness check."""

    pepper_configured: bool
    pepper_version: int
    encryption_enabled: bool


# ---------------------------------------------------------------------------
# Intake (intake.py)
# ---------------------------------------------------------------------------


class IntakeCreateResponse(CamelModel):
    """Result of creating a new intake."""

    intake_id: str
    job_id: Optional[str] = None
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    status: str = "received"
    job: Optional[Dict[str, Any]] = None


class IntakeJobUpdateResponse(CamelModel):
    """Confirmation of intake job status update."""

    updated: bool
    job_id: str


class IntakeStatusUpdateResponse(CamelModel):
    """Confirmation of intake status update."""

    updated: bool
    intake_id: str


class IntakeCaseAttachResponse(CamelModel):
    """Confirmation of attaching case metadata to intake."""

    updated: bool
    intake_id: str
    case_id: Optional[str] = None
    review_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Reports (reports.py)
# ---------------------------------------------------------------------------


class VerifyArtifact(CamelModel):
    """Single artifact in a dossier verification result."""

    label: str
    path: Optional[str] = None
    expected_hash: Optional[str] = None
    actual_hash: Optional[str] = None
    exists: bool
    matches: bool
    size_bytes: Optional[int] = None
    error: Optional[str] = None


class DossierVerifyResponse(CamelModel):
    """Result of verifying a dossier's artifacts."""

    plan_id: str
    algorithm: str
    warnings: List[str] = Field(default_factory=list)
    missing_count: int
    mismatch_count: int
    all_verified: bool
    artifacts: List[VerifyArtifact]


class DriveAclResponse(CamelModel):
    """Drive folder metadata + permissions."""

    plan_id: str
    folder_id: Optional[str] = None
    folder_name: Optional[str] = None
    link: Optional[str] = None
    drive_id: Optional[str] = None
    permissions: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Dashboard (dashboard.py)
# ---------------------------------------------------------------------------


class DashboardMetric(CamelModel):
    """Single metric card on the dashboard."""

    label: str
    value: str
    change: str


class DashboardActivity(CamelModel):
    """Recent activity entry."""

    id: str
    title: str
    actor: str
    when: str


class DashboardAlert(CamelModel):
    """Alert card on the dashboard."""

    id: str
    title: str
    detail: str
    time: str
    variant: str


class DashboardReminder(CamelModel):
    """Reminder item on the dashboard."""

    id: str
    text: str
    category: str


class DashboardOverviewResponse(CamelModel):
    """Complete dashboard overview payload."""

    metrics: List[DashboardMetric]
    alerts: List[DashboardAlert]
    activity: List[DashboardActivity]
    reminders: List[DashboardReminder]


# ---------------------------------------------------------------------------
# Analytics (analytics.py)
# ---------------------------------------------------------------------------


class AnalyticsMetric(CamelModel):
    """Single analytics metric with trend info."""

    id: str
    label: str
    value: str
    change: str
    trend: str


class DailySeries(CamelModel):
    """Daily data point for time series."""

    label: str
    value: int


class PipelineStep(CamelModel):
    """Step in the pipeline breakdown."""

    label: str
    value: int


class WeeklyIncident(CamelModel):
    """Weekly incident/intervention data point."""

    week: str
    incidents: int
    interventions: int


class GeographyBreakdown(CamelModel):
    """Regional breakdown data point."""

    region: str
    value: int


class AnalyticsOverviewResponse(CamelModel):
    """Complete analytics overview payload."""

    metrics: List[AnalyticsMetric]
    detection_rate_series: List[DailySeries]
    pipeline_breakdown: List[PipelineStep]
    geography_breakdown: List[GeographyBreakdown]
    weekly_incidents: List[WeeklyIncident]


# ---------------------------------------------------------------------------
# Discovery (discovery.py)
# ---------------------------------------------------------------------------


class DiscoveryResult(CamelModel):
    """Single Discovery search result."""

    model_config = {"extra": "allow"}

    document_id: Optional[str] = None
    document_name: Optional[str] = None


class DiscoverySearchResponse(CamelModel):
    """Response from Discovery search."""

    results: List[Dict[str, Any]]
    total_size: int
    next_page_token: Optional[str] = None
