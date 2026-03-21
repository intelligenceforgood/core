"""HTTP client for ML Platform prediction endpoints."""

from __future__ import annotations

import logging

import httpx

from i4g.settings import get_settings

logger = logging.getLogger(__name__)


class MLPlatformClient:
    """Async HTTP client for the ML Platform serving layer.

    Wraps prediction and feedback endpoints exposed by the ``ml``
    serving application.  Uses ``httpx.AsyncClient`` for non-blocking
    calls from the FastAPI request path.
    """

    def __init__(self, *, base_url: str | None = None, timeout: float = 30.0) -> None:
        settings = get_settings()
        self._base_url = base_url or settings.ml.platform_base_url
        self._timeout = timeout

    async def classify(self, text: str, case_id: str) -> dict:
        """Request a classification prediction from the ML Platform.

        Args:
            text: Case narrative text to classify.
            case_id: Identifier of the case being classified.

        Returns:
            Prediction response dict from the ML Platform.

        Raises:
            httpx.HTTPStatusError: If the prediction request fails.
        """
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            resp = await client.post(
                "/predict/classify",
                json={"text": text, "case_id": case_id},
            )
            resp.raise_for_status()
            return resp.json()

    async def send_feedback(
        self,
        prediction_id: str,
        case_id: str,
        correction: dict,
        analyst_id: str,
    ) -> None:
        """Submit analyst feedback / correction for a prediction.

        Args:
            prediction_id: The prediction being corrected.
            case_id: Case the prediction belongs to.
            correction: Dict with corrected labels keyed by axis.
            analyst_id: Analyst who made the correction.

        Raises:
            httpx.HTTPStatusError: If the feedback submission fails.
        """
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            resp = await client.post(
                "/feedback",
                json={
                    "prediction_id": prediction_id,
                    "case_id": case_id,
                    "correction": correction,
                    "analyst_id": analyst_id,
                },
            )
            resp.raise_for_status()
