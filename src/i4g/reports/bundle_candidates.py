"""Helpers that transform accepted reviews into :class:`DossierCandidate` objects."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation

from i4g.reports.bundle_builder import DossierCandidate
from i4g.reports.bundle_metrics import compute_bundle_metrics
from i4g.store.review_store import ReviewStore
from i4g.store.structured import StructuredStore
from i4g.utils.datetime_parse import parse_datetime as _shared_parse_datetime


class BundleCandidateProvider:
    """Pulls accepted queue entries and enriches them with structured metadata."""

    def __init__(
        self,
        review_store: ReviewStore | None = None,
        structured_store: StructuredStore | None = None,
    ) -> None:
        if review_store is None or structured_store is None:
            from i4g.services.factories import build_review_store, build_structured_store

        self._review_store = review_store or build_review_store()
        self._structured_store = structured_store or build_structured_store()

    def list_candidates(self, *, limit: int = 200) -> list[DossierCandidate]:
        """Return accepted review entries mapped to dossier candidates."""

        metrics_rows = self._list_metrics_rows(limit=limit)
        if metrics_rows:
            return self._map_metric_rows(metrics_rows)

        rows = self._review_store.get_queue(status="accepted", limit=limit)
        return self._map_queue_rows(rows)

    def _list_metrics_rows(self, *, limit: int) -> list[dict]:
        view_fn = getattr(self._review_store, "list_dossier_candidates", None)
        if not callable(view_fn):
            return []
        try:
            return list(view_fn(status="accepted", limit=limit))
        except TypeError:
            return []
        except Exception:
            return []

    def _map_metric_rows(self, rows: Iterable[dict]) -> list[DossierCandidate]:
        candidates: list[DossierCandidate] = []
        for row in rows:
            case_id = str(row.get("case_id") or "").strip()
            if not case_id:
                continue
            record = self._structured_store.get_by_id(case_id)
            entities = getattr(record, "entities", None) or {}
            accepted_at = _parse_datetime(row.get("accepted_at"))
            candidates.append(
                DossierCandidate(
                    case_id=case_id,
                    loss_amount_usd=_loss_amount_from_value(row.get("loss_amount_usd")),
                    accepted_at=accepted_at,
                    jurisdiction=str(row.get("jurisdiction") or "unknown"),
                    cross_border=bool(row.get("cross_border")),
                    primary_entities=_primary_entities(entities),
                )
            )
        return candidates

    def _map_queue_rows(self, rows: Iterable[dict]) -> list[DossierCandidate]:
        candidates: list[DossierCandidate] = []
        for row in rows:
            case_id = str(row.get("case_id") or "").strip()
            if not case_id:
                continue
            record = self._structured_store.get_by_id(case_id)
            entities = getattr(record, "entities", None) or {}
            accepted_at = _parse_datetime(row.get("last_updated") or row.get("queued_at"))
            metadata = getattr(record, "metadata", None) or {}
            metrics = compute_bundle_metrics(metadata)
            candidates.append(
                DossierCandidate(
                    case_id=case_id,
                    loss_amount_usd=metrics.loss_amount_usd,
                    accepted_at=accepted_at,
                    jurisdiction=metrics.jurisdiction,
                    cross_border=metrics.cross_border,
                    primary_entities=_primary_entities(entities),
                )
            )
        return candidates


def _parse_datetime(value: object | None) -> datetime:
    """Parse datetime with fallback to now(utc)."""
    return _shared_parse_datetime(value, on_error="now")


def _loss_amount_from_value(value: object | None) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _primary_entities(entities: dict[str, Sequence[str]]) -> Sequence[str]:
    collected: list[str] = []
    if not isinstance(entities, dict):
        return tuple()
    for values in entities.values():
        if not values:
            continue
        for value in values:
            if not value:
                continue
            collected.append(str(value))
            if len(collected) >= 5:
                return tuple(collected)
    return tuple(collected)
