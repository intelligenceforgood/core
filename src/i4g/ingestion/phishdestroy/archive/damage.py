"""Damage parser for PhishDestroy ``successful_thefts/result.json`` deposit messages (Sprint 2 Phase D).

Parses Telegram channel export JSON for the Russian-language and English-language deposit
notification format used by PhishDestroy-tracked scam teams.  The module is **pure** — no
database calls or side-effects; the adapter is responsible for persisting the returned records.

References:
    - PRD §5.3 (``financial_damage_claims``) — ``planning/prd_phishdestroy_integration.md``.
    - Phase D manifest §"Behaviour contract — damage parser".
"""

from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

LOGGER = logging.getLogger("i4g.ingestion.phishdestroy.archive.damage")

# ── Pattern anchors ──────────────────────────────────────────────────────────
# Both Russian and English variants must be supported.

_DEPOSIT_HEADER_RU = "Зачислен новый депозит"
_DEPOSIT_HEADER_EN = "New deposit received"

_RE_AMOUNT = re.compile(
    r"(?:Сумма в USD|Amount in USD)[^\d\-]*\$?\s*([0-9]+(?:[.,][0-9]+)?)",
    re.IGNORECASE,
)
_RE_CHAIN = re.compile(
    r"(?:Сеть|Network)[^A-Za-z0-9]*([A-Za-z0-9\-]+)",
    re.IGNORECASE,
)
_RE_PROJECT = re.compile(
    r"(?:Проект|Project)[^A-Za-z0-9]*([^\n]+?)(?:\s*(?:🀄|🫂|👤|Сеть|Network)|$)",
    re.IGNORECASE,
)
_RE_PERCENT = re.compile(
    r"(?:Процент|Percentage)[^\d\-]*([0-9]+(?:[.,][0-9]+)?)",
    re.IGNORECASE,
)
_RE_CREDITED = re.compile(
    r"(?:К зачислению|To be credited)[^\d\-]*\$?\s*([0-9]+(?:[.,][0-9]+)?)",
    re.IGNORECASE,
)


def _to_decimal(raw: str) -> Decimal:
    """Convert a possibly comma-decimal string to :class:`Decimal`.

    Raises:
        InvalidOperation: When conversion fails.
    """
    return Decimal(raw.replace(",", ".").strip())


def _render_text(entry: dict[str, Any]) -> str:
    """Render the ``text`` / ``text_entities`` field of a Telegram message to a plain string."""
    # Prefer text_entities (Telegram export schema).
    entities = entry.get("text_entities")
    if isinstance(entities, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else (part if isinstance(part, str) else "")
            for part in entities
        )

    raw = entry.get("text", "")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        return "".join(part if isinstance(part, str) else part.get("text", "") for part in raw)
    return ""


@dataclass(frozen=True)
class DamageRecord:
    """A single parsed deposit record from ``successful_thefts/result.json``."""

    message_id: int
    """``entry["id"]`` from the Telegram export."""

    project: str | None
    """Project / casino name, or ``None`` when absent."""

    chain: str | None
    """Cryptocurrency network (uppercased), e.g. ``"BTC"``, ``"ETH"``, or ``None``."""

    amount_usd_claimed: Decimal
    """Claimed deposit amount in USD (required; messages without this line are skipped)."""

    amount_usd_credited: Decimal | None
    """Amount credited to the operator after percentage split, or ``None``."""

    operator_share_percent: Decimal | None
    """Operator split percentage, or ``None``."""

    raw_text: str
    """Joined plain-text rendering of the message (for debug / metadata excerpts)."""


def parse_deposit_messages(
    messages: Iterable[dict[str, Any]],
) -> tuple[list[DamageRecord], int]:
    """Parse a ``successful_thefts/result.json`` messages list.

    Args:
        messages: Iterable of Telegram message dicts from the ``"messages"`` array.

    Returns:
        A ``(records, skipped_message_count)`` tuple.  Service-type messages, edit
        records, and messages that lack a deposit header or a parseable "Amount in USD" /
        "Сумма в USD" line are counted in ``skipped_message_count`` but do not raise.
    """
    records: list[DamageRecord] = []
    skipped = 0

    for entry in messages:
        # Skip non-message types (service, empty, edited shadows, etc.)
        if entry.get("type") != "message":
            skipped += 1
            continue

        raw_text = _render_text(entry)

        # Skip messages that are not deposit notifications.
        if _DEPOSIT_HEADER_RU not in raw_text and _DEPOSIT_HEADER_EN not in raw_text:
            skipped += 1
            continue

        # "Amount in USD" is required — skip if absent.
        amount_match = _RE_AMOUNT.search(raw_text)
        if not amount_match:
            skipped += 1
            LOGGER.debug("Skipping message id=%s: no Amount in USD line", entry.get("id"))
            continue

        try:
            amount_usd_claimed = _to_decimal(amount_match.group(1))
        except InvalidOperation:
            skipped += 1
            LOGGER.debug(
                "Skipping message id=%s: could not parse amount %r",
                entry.get("id"),
                amount_match.group(1),
            )
            continue

        # Optional fields — extraction failures do not skip the message.
        chain: str | None = None
        chain_match = _RE_CHAIN.search(raw_text)
        if chain_match:
            chain = chain_match.group(1).upper()

        project: str | None = None
        project_match = _RE_PROJECT.search(raw_text)
        if project_match:
            project = project_match.group(1).strip() or None

        operator_share_percent: Decimal | None = None
        pct_match = _RE_PERCENT.search(raw_text)
        if pct_match:
            with contextlib.suppress(InvalidOperation):
                operator_share_percent = _to_decimal(pct_match.group(1))

        amount_usd_credited: Decimal | None = None
        credited_match = _RE_CREDITED.search(raw_text)
        if credited_match:
            with contextlib.suppress(InvalidOperation):
                amount_usd_credited = _to_decimal(credited_match.group(1))

        records.append(
            DamageRecord(
                message_id=int(entry["id"]),
                project=project,
                chain=chain,
                amount_usd_claimed=amount_usd_claimed,
                amount_usd_credited=amount_usd_credited,
                operator_share_percent=operator_share_percent,
                raw_text=raw_text,
            )
        )

    return records, skipped
