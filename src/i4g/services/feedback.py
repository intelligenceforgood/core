"""Feedback service — abstracts storage so the backend can swap later.

Phase 1 uses Google Sheets via the Sheets API.  The ``FeedbackService``
protocol defines the contract; ``GoogleSheetsFeedbackService`` implements it.
A ``LoggingFeedbackService`` is provided for local development.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Payload model
# ---------------------------------------------------------------------------

# Map feedback-ID page prefix → Google Sheet tab name
PAGE_TAB_MAP: dict[str, str] = {
    "dashboard": "Dashboard",
    "search": "Search",
    "accounts": "Accounts",
    "discovery": "Discovery",
    "cases": "Cases",
    "case-detail": "Case Detail",
    "case-intake": "Case Intake",
    "dossiers": "Dossiers",
    "campaigns": "Campaigns",
    "taxonomy": "Taxonomy",
    "analytics": "Analytics",
    "ssi-investigate": "SSI Investigate",
    "ssi-investigations": "SSI Investigations",
    "ssi-detail": "SSI Investigation Detail",
    "ssi-wallets": "SSI Wallets",
    "admin-users": "Admin Users",
    "navigation": "Dashboard",  # global nav feedback goes to Dashboard tab
}


class FeedbackPayload(BaseModel):
    """Feedback submission from the analyst console."""

    feedback_id: str = Field(
        ...,
        description="Two-level ID: page.section (e.g. 'dashboard.metrics').",
    )
    feedback_type: str = Field(
        ...,
        description="One of: Bug, Feature Request, UX Issue, Question, Other.",
    )
    priority: str = Field(
        default="P2-Medium",
        description="P0-Critical, P1-High, P2-Medium, or P3-Low.",
    )
    subject: str = Field(
        ...,
        max_length=120,
        description="Short summary of the feedback.",
    )
    description: str = Field(
        ...,
        max_length=2000,
        description="Detailed description.",
    )
    submitter: str = Field(
        default="",
        description="Email or username of the submitter.",
    )
    page_url: str = Field(
        default="",
        description="The page URL from window.location.href.",
    )
    user_agent: str = Field(
        default="",
        description="The browser user-agent string from navigator.userAgent.",
    )


# ---------------------------------------------------------------------------
# Service protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class FeedbackService(Protocol):
    """Abstract feedback storage interface."""

    def submit(self, payload: FeedbackPayload) -> bool:
        """Append a feedback entry. Returns True on success.

        Args:
            payload: The feedback submission data.

        Returns:
            True if the feedback was persisted successfully.
        """
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Google Sheets implementation
# ---------------------------------------------------------------------------


class GoogleSheetsFeedbackService:
    """Appends feedback rows to a Google Sheet via the Sheets API.

    Args:
        sheet_id: The Google Sheet spreadsheet ID.
        credentials: Optional pre-built credentials. Defaults to ADC.
    """

    def __init__(self, sheet_id: str, credentials: Any = None) -> None:
        self._sheet_id = sheet_id
        self._credentials = credentials
        self._service: Any = None

    def _get_service(self) -> Any:
        """Lazily build the Sheets API client.

        Uses an explicit ``httplib2.Http`` instance with a pre-set timeout so
        that ``google-auth`` credential refreshes on Cloud Run do not trigger
        the "httplib2 transport does not support per-request timeout" warning
        (which in some library versions prevents token refresh and silently
        blocks all API calls).
        """
        if self._service is not None:
            return self._service

        import httplib2
        from google_auth_httplib2 import AuthorizedHttp
        from googleapiclient.discovery import build

        if self._credentials:
            creds = self._credentials
        else:
            import google.auth

            creds, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )

        authorized_http = AuthorizedHttp(creds, http=httplib2.Http(timeout=30))
        self._service = build("sheets", "v4", http=authorized_http, cache_discovery=False)
        return self._service

    def _resolve_tab(self, feedback_id: str) -> tuple[str, str]:
        """Parse feedback_id into (sheet_tab_name, section).

        Args:
            feedback_id: Two-level ID like 'dashboard.metrics'.

        Returns:
            Tuple of (tab_name, section).
        """
        parts = feedback_id.split(".", 1)
        page_key = parts[0]
        section = parts[1] if len(parts) > 1 else "page"
        tab_name = PAGE_TAB_MAP.get(page_key, "Dashboard")
        return tab_name, section

    def submit(self, payload: FeedbackPayload) -> bool:
        """Append a row to the appropriate sheet tab.

        Args:
            payload: The feedback submission data.

        Returns:
            True if the row was appended successfully.
        """
        tab_name, section = self._resolve_tab(payload.feedback_id)
        now_et = datetime.now(tz=ZoneInfo("America/New_York"))
        hour12 = now_et.strftime("%I").lstrip("0") or "12"
        timestamp = f"{now_et.strftime('%b')} {now_et.day}, {now_et.year} " f"{hour12}:{now_et.strftime('%M %p')} ET"

        row = [
            payload.feedback_type,  # A: Type
            payload.priority,  # B: Priority
            "New",  # C: Status
            "",  # D: Effort
            timestamp,  # E: Create Date
            tab_name,  # F: Page
            section,  # G: Section
            payload.subject,  # H: Subject
            payload.description,  # I: Description
            payload.submitter,  # J: Submitter
            "",  # K: Owner
            payload.page_url,  # L: Page URL
            payload.user_agent,  # M: User Agent
            "",  # N: Resolution Notes
        ]

        try:
            service = self._get_service()
            result = (
                service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self._sheet_id,
                    range=f"'{tab_name}'!A:N",
                    valueInputOption="RAW",
                    insertDataOption="OVERWRITE",
                    body={"values": [row]},
                )
                .execute()
            )
            logger.debug("Sheets append OK: updatedRange=%s", result.get("updates", {}).get("updatedRange"))
        except Exception:
            logger.exception("FEEDBACK append FAILED for tab '%s'", tab_name)
            return False

        logger.info(
            "Feedback submitted: %s/%s by %s",
            tab_name,
            section,
            payload.submitter or "anonymous",
        )
        return True


# ---------------------------------------------------------------------------
# Local/mock implementation
# ---------------------------------------------------------------------------


class LoggingFeedbackService:
    """Logs feedback to stdout instead of writing to a sheet.

    Suitable for local development and testing.
    """

    @staticmethod
    def _resolve_tab(feedback_id: str) -> tuple[str, str]:
        """Parse *feedback_id* the same way :class:`GoogleSheetsFeedbackService` does.

        Args:
            feedback_id: Two-level ID like 'dashboard.metrics'.

        Returns:
            Tuple of (tab_name, section).
        """
        parts = feedback_id.split(".", 1)
        page_key = parts[0]
        section = parts[1] if len(parts) > 1 else "page"
        tab_name = PAGE_TAB_MAP.get(page_key, page_key)
        return tab_name, section

    def submit(self, payload: FeedbackPayload) -> bool:
        """Log the feedback payload.

        Args:
            payload: The feedback submission data.

        Returns:
            Always True.
        """
        tab_name, section = self._resolve_tab(payload.feedback_id)
        logger.warning(
            "FEEDBACK (local — not persisted) [%s/%s] %s | %s: %s — %s (by %s)",
            tab_name,
            section,
            payload.priority,
            payload.feedback_type,
            payload.subject,
            payload.description[:80],
            payload.submitter or "anonymous",
        )
        return True
