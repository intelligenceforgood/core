"""Shared Pydantic response models for API endpoints.

Provides typed response schemas that FastAPI uses for OpenAPI documentation
and runtime validation.  Keep models thin -- they describe the *shape* of
the JSON the server returns, not domain/business logic.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from i4g.api.camel import CamelModel


# ---------------------------------------------------------------------------
# Generic / reusable envelopes
# ---------------------------------------------------------------------------


class ItemListResponse(CamelModel):
    """Paginated list wrapper used by several list endpoints."""

    items: list[dict[str, Any]]
    count: int


class EventListResponse(CamelModel):
    """Wrapper for event/action history lists."""

    events: list[dict[str, Any]]
    count: int


class IdResponse(CamelModel):
    """Single-ID confirmation used by create / share / import endpoints."""

    search_id: str


class MutationResponse(CamelModel):
    """Generic update/delete confirmation."""

    updated: bool | None = None
    deleted: bool | None = None
    search_id: str | None = None


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
    message: str | None = None


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
    reviews: list[dict[str, Any]]
    count: int


class ActionHistoryResponse(CamelModel):
    """Audit trail for a review."""

    review_id: str
    actions: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Search (review_search.py)
# ---------------------------------------------------------------------------


class SearchResultsResponse(CamelModel):
    """Response from GET /reviews/search."""

    results: list[dict[str, Any]]
    count: int
    offset: int
    limit: int
    total: int
    vector_hits: int | None = None
    structured_hits: int | None = None
    merged_results: int | None = None
    source_breakdown: dict[str, Any] | None = None
    diagnostics: dict[str, Any] | None = None
    search_id: str
    duration_ms: float | None = None


class AdvancedSearchResultsResponse(CamelModel):
    """Response from POST /reviews/search/query.

    Extends the raw hybrid search result with a search_id.
    Uses ``model_config`` to allow extra fields from the search service.
    """

    model_config = {"extra": "allow"}

    search_id: str
    results: list[dict[str, Any]] | None = None
    count: int | None = None
    total: int | None = None


class SearchSchemaResponse(CamelModel):
    """Dynamic filter schema returned by GET /reviews/search/schema.

    Uses ``extra = "allow"`` because the schema is dynamic.
    """

    model_config = {"extra": "allow"}

    classifications: list[str] | None = None
    campaigns: list[dict[str, Any]] | None = None


class PresetListResponse(CamelModel):
    """List of tag presets."""

    presets: list[dict[str, Any]]
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
    case_id: str | None = None
    detector: str | None = None
    created_at: str | None = None


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
    job_id: str | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "received"
    job: dict[str, Any] | None = None


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
    case_id: str | None = None
    review_id: str | None = None


# ---------------------------------------------------------------------------
# Reports (reports.py)
# ---------------------------------------------------------------------------


class VerifyArtifact(CamelModel):
    """Single artifact in a dossier verification result."""

    label: str
    path: str | None = None
    expected_hash: str | None = None
    actual_hash: str | None = None
    exists: bool
    matches: bool
    size_bytes: int | None = None
    error: str | None = None


class DossierVerifyResponse(CamelModel):
    """Result of verifying a dossier's artifacts."""

    plan_id: str
    algorithm: str
    warnings: list[str] = Field(default_factory=list)
    missing_count: int
    mismatch_count: int
    all_verified: bool
    artifacts: list[VerifyArtifact]


class DriveAclResponse(CamelModel):
    """Drive folder metadata + permissions."""

    plan_id: str
    folder_id: str | None = None
    folder_name: str | None = None
    link: str | None = None
    drive_id: str | None = None
    permissions: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


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

    metrics: list[DashboardMetric]
    alerts: list[DashboardAlert]
    activity: list[DashboardActivity]
    reminders: list[DashboardReminder]


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

    metrics: list[AnalyticsMetric]
    detection_rate_series: list[DailySeries]
    pipeline_breakdown: list[PipelineStep]
    geography_breakdown: list[GeographyBreakdown]
    weekly_incidents: list[WeeklyIncident]


# ---------------------------------------------------------------------------
# Discovery (discovery.py)
# ---------------------------------------------------------------------------


class DiscoveryResult(CamelModel):
    """Single Discovery search result."""

    model_config = {"extra": "allow"}

    document_id: str | None = None
    document_name: str | None = None


class DiscoverySearchResponse(CamelModel):
    """Response from Discovery search."""

    results: list[dict[str, Any]]
    total_size: int
    next_page_token: str | None = None


# ---------------------------------------------------------------------------
# Cases (cases.py)
# ---------------------------------------------------------------------------


class CasesSummary(CamelModel):
    """Aggregate counts for the cases overview."""

    active: int = 0
    due_today: int = 0
    pending_review: int = 0
    escalations: int = 0


class CaseListItem(CamelModel):
    """Minimal case data for list views."""

    model_config = {"extra": "allow"}

    id: str
    title: str
    priority: str
    status: str


class CaseQueue(CamelModel):
    """Queue summary entry."""

    id: str
    name: str
    description: str
    count: int


class CasesListResponse(CamelModel):
    """Response for GET /cases."""

    summary: CasesSummary
    cases: list[CaseListItem]
    queues: list[CaseQueue]


# ---------------------------------------------------------------------------
# Review detail (review_detail.py) — single review
# ---------------------------------------------------------------------------


class ReviewItemResponse(CamelModel):
    """Single review queue item returned by GET /reviews/{review_id}."""

    model_config = {"extra": "allow"}

    review_id: str
    case_id: str
    status: str | None = None
    priority: str | None = None


# ---------------------------------------------------------------------------
# Saved search export (review_search.py)
# ---------------------------------------------------------------------------


class SavedSearchExportResponse(CamelModel):
    """Exported saved search configuration."""

    model_config = {"extra": "allow"}

    search_id: str
    name: str
    params: dict[str, Any] | None = None
    tags: list[str] | None = None


# ---------------------------------------------------------------------------
# Taxonomy (taxonomy.py)
# ---------------------------------------------------------------------------


class TaxonomyResponse(CamelModel):
    """Taxonomy tree. Uses ``extra = "allow"`` for dynamic structure."""

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Intake record / job detail
# ---------------------------------------------------------------------------


class IntakeRecordResponse(CamelModel):
    """Full intake record. Uses ``extra = "allow"`` for flexible payloads."""

    model_config = {"extra": "allow"}

    intake_id: str


class IntakeJobResponse(CamelModel):
    """Intake job status detail."""

    model_config = {"extra": "allow"}

    job_id: str
