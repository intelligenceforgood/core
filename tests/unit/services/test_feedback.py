"""Unit tests for the feedback service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from i4g.services.feedback import (
    PAGE_TAB_MAP,
    FeedbackPayload,
    GoogleSheetsFeedbackService,
    LoggingFeedbackService,
)

# ---------------------------------------------------------------------------
# FeedbackPayload
# ---------------------------------------------------------------------------


class TestFeedbackPayload:
    """Validation and serialisation of feedback payloads."""

    def test_minimal_payload(self) -> None:
        """Required fields only produces a valid payload."""
        p = FeedbackPayload(
            feedback_id="dashboard.metrics",
            feedback_type="Bug",
            subject="Metric shows NaN",
            description="The active-cases metric shows NaN when there are no cases.",
        )
        assert p.feedback_id == "dashboard.metrics"
        assert p.priority == "P2-Medium"
        assert p.submitter == ""

    def test_full_payload(self) -> None:
        """All fields populated."""
        p = FeedbackPayload(
            feedback_id="search.results",
            feedback_type="Feature Request",
            priority="P1-High",
            subject="Add export button",
            description="Would love to export search results as CSV.",
            submitter="analyst@example.com",
            page_url="https://console.example.com/search",
            user_agent="Mozilla/5.0 (X11; Linux x86_64)",
        )
        assert p.submitter == "analyst@example.com"
        assert p.page_url.startswith("https://")
        assert "Mozilla" in p.user_agent

    def test_subject_max_length(self) -> None:
        """Subject longer than 120 chars should fail validation."""
        with pytest.raises(ValidationError):
            FeedbackPayload(
                feedback_id="dashboard.alerts",
                feedback_type="Bug",
                subject="x" * 121,
                description="ok",
            )


# ---------------------------------------------------------------------------
# PAGE_TAB_MAP
# ---------------------------------------------------------------------------


class TestPageTabMap:
    """Verify all expected pages are mapped."""

    def test_all_pages_present(self) -> None:
        """Spot-check key pages exist in the map."""
        assert "dashboard" in PAGE_TAB_MAP
        assert "search" in PAGE_TAB_MAP
        assert "ssi-investigate" in PAGE_TAB_MAP
        assert "admin-users" in PAGE_TAB_MAP
        assert "reports.builder" in PAGE_TAB_MAP
        assert "intelligence.entities" in PAGE_TAB_MAP
        assert "impact.geography" in PAGE_TAB_MAP
        assert "admin-engagements.compare" in PAGE_TAB_MAP

    def test_navigation_fallback(self) -> None:
        """Global nav feedback maps to Dashboard."""
        assert PAGE_TAB_MAP["navigation"] == "Dashboard"


# ---------------------------------------------------------------------------
# LoggingFeedbackService
# ---------------------------------------------------------------------------


class TestLoggingFeedbackService:
    """LoggingFeedbackService always returns True and logs."""

    def test_submit_returns_true(self) -> None:
        """Submit always succeeds."""
        svc = LoggingFeedbackService()
        payload = FeedbackPayload(
            feedback_id="cases.list",
            feedback_type="UX Issue",
            subject="Filter is confusing",
            description="The queue filter label is ambiguous.",
        )
        assert svc.submit(payload) is True

    def test_submit_with_dotless_id(self) -> None:
        """Feedback ID without a section delimiter still works."""
        svc = LoggingFeedbackService()
        payload = FeedbackPayload(
            feedback_id="dashboard",
            feedback_type="Question",
            subject="What does the metric mean?",
            description="Unclear definition.",
        )
        assert svc.submit(payload) is True


# ---------------------------------------------------------------------------
# GoogleSheetsFeedbackService
# ---------------------------------------------------------------------------


class TestGoogleSheetsFeedbackService:
    """GoogleSheetsFeedbackService interacts with the Sheets API."""

    def _make_service(self) -> GoogleSheetsFeedbackService:
        """Create a service instance with a mock credential."""
        return GoogleSheetsFeedbackService(
            sheet_id="test-sheet-id",
            credentials=MagicMock(),
        )

    def test_resolve_tab_known_page(self) -> None:
        """Known feedback_id resolves to the correct tab."""
        svc = self._make_service()
        tab, section = svc._resolve_tab("search.filters")
        assert tab == "Search"
        assert section == "filters"

    def test_resolve_tab_longest_prefix(self) -> None:
        """Longest matching feedback prefix wins when multiple prefixes fit."""
        svc = self._make_service()
        tab, section = svc._resolve_tab("reports.builder")
        assert tab == "Report Builder"
        assert section == "page"

    def test_resolve_tab_nested_exact_prefix(self) -> None:
        """Nested page families resolve to their dedicated tabs."""
        svc = self._make_service()
        tab, section = svc._resolve_tab("admin-engagements.compare")
        assert tab == "Engagement Comparison"
        assert section == "page"

    def test_resolve_tab_unknown_page(self) -> None:
        """Unknown page prefix defaults to Dashboard."""
        svc = self._make_service()
        tab, section = svc._resolve_tab("unknown.widget")
        assert tab == "Dashboard"
        assert section == "widget"

    def test_resolve_tab_no_section(self) -> None:
        """Feedback ID without a section defaults to 'page'."""
        svc = self._make_service()
        tab, section = svc._resolve_tab("dashboard")
        assert tab == "Dashboard"
        assert section == "page"

    @patch("i4g.services.feedback.GoogleSheetsFeedbackService._get_service")
    def test_submit_success(self, mock_get_svc: MagicMock) -> None:
        """Successful append returns True; no per-row batchUpdate is issued.

        All formatting is owned by setup_feedback_sheet.py --recreate;
        submit() only calls values().append().
        """
        mock_svc = MagicMock()
        mock_get_svc.return_value = mock_svc

        mock_svc.spreadsheets().values().append().execute.return_value = {
            "updates": {"updatedRange": "'Analytics'!A3:N3"}
        }

        svc = self._make_service()
        payload = FeedbackPayload(
            feedback_id="analytics.charts",
            feedback_type="Bug",
            subject="Chart not rendering",
            description="The bar chart shows a blank area.",
            submitter="user@example.com",
        )
        result = svc.submit(payload)
        assert result is True

        # Append called with the correct spreadsheet ID and 14-column range.
        call_kwargs = mock_svc.spreadsheets().values().append.call_args[1]
        assert call_kwargs["spreadsheetId"] == "test-sheet-id"
        assert "'Analytics'" in call_kwargs["range"]
        assert call_kwargs["range"].endswith("!A:N")

        # OVERWRITE preserves pre-set formatting from setup_feedback_sheet.py;
        # INSERT_ROWS would inherit header formatting on each new row.
        assert call_kwargs["insertDataOption"] == "OVERWRITE"

        # No per-row formatting — batchUpdate must NOT be called.
        mock_svc.spreadsheets().batchUpdate.assert_not_called()

    @patch("i4g.services.feedback.GoogleSheetsFeedbackService._get_service")
    def test_submit_api_error(self, mock_get_svc: MagicMock) -> None:
        """API error returns False (does not raise)."""
        mock_svc = MagicMock()
        mock_svc.spreadsheets().values().append().execute.side_effect = RuntimeError("API down")
        mock_get_svc.return_value = mock_svc

        svc = self._make_service()
        payload = FeedbackPayload(
            feedback_id="dashboard.metrics",
            feedback_type="Bug",
            subject="Error",
            description="Something broke.",
        )
        result = svc.submit(payload)
        assert result is False
