"""SSI scan persistence store for the core gateway.

``SsiStore`` provides the CRUD layer for the four SSI tables
(``site_scans``, ``harvested_wallets``, ``agent_sessions``,
``pii_exposures``) that live in core's Alembic-managed database.

It mirrors the public API of ``ssi.store.ScanStore`` so that the
gateway endpoints can serve the same data without importing from the
``ssi`` package.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.store import sql as sql_schema
from i4g.store.sql import METADATA, dialect_insert
from i4g.store.sql import session_factory as default_session_factory
from i4g.utils.url_normalization import normalize_url

logger = logging.getLogger(__name__)


class SsiStore:
    """Persist SSI scan results, wallets, agent actions, and PII exposures.

    Args:
        db_path: Convenience path for a local SQLite file.  Mutually
            exclusive with *session_factory*.
        session_factory: Pre-configured ``sessionmaker`` (e.g. Cloud SQL
            or a shared test fixture).
    """

    def __init__(
        self,
        db_path: str | None = None,
        *,
        session_factory: sessionmaker | None = None,
    ) -> None:
        if session_factory is not None:
            self._session_factory = session_factory
        elif db_path is not None:
            engine = sa.create_engine(
                f"sqlite:///{db_path}",
                pool_pre_ping=True,
                connect_args={"check_same_thread": False},
            )
            METADATA.create_all(engine, checkfirst=True)
            self._session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        else:
            self._session_factory = default_session_factory()

    # ------------------------------------------------------------------
    # case_investigations queries
    # ------------------------------------------------------------------

    def get_case_investigations(self, case_id: str) -> list[dict[str, Any]]:
        """Return investigations linked to a case via ``case_investigations``.

        Args:
            case_id: The case to look up.

        Returns:
            List of dicts with scan + link metadata, ordered by link date desc.
        """
        ci = sql_schema.case_investigations
        ss = sql_schema.site_scans
        stmt = (
            sa.select(
                ci.c.scan_id,
                ci.c.trigger_type,
                ci.c.created_at.label("linked_at"),
                ss.c.url,
                ss.c.normalized_url,
                ss.c.status,
                ss.c.risk_score,
                ss.c.completed_at,
            )
            .select_from(ci.join(ss, ci.c.scan_id == ss.c.scan_id))
            .where(ci.c.case_id == case_id)
            .order_by(ci.c.created_at.desc())
        )
        with self._session_factory() as session:
            rows = session.execute(stmt).all()
        return [dict(r._mapping) for r in rows]

    def get_scan_linked_cases(self, scan_id: str) -> list[dict[str, Any]]:
        """Return cases linked to a scan via ``case_investigations``.

        Args:
            scan_id: The scan to look up.

        Returns:
            List of dicts with case summary + link metadata, ordered by link date desc.
        """
        ci = sql_schema.case_investigations
        c = sql_schema.cases
        stmt = (
            sa.select(
                ci.c.case_id,
                ci.c.trigger_type,
                ci.c.created_at.label("linked_at"),
                c.c.dataset,
                c.c.classification,
                c.c.status,
            )
            .select_from(ci.join(c, ci.c.case_id == c.c.case_id))
            .where(ci.c.scan_id == scan_id)
            .order_by(ci.c.created_at.desc())
        )
        with self._session_factory() as session:
            rows = session.execute(stmt).all()
        return [dict(r._mapping) for r in rows]

    # ------------------------------------------------------------------
    # site_scans CRUD
    # ------------------------------------------------------------------

    def create_scan(
        self,
        *,
        url: str,
        scan_type: str = "passive",
        domain: str | None = None,
        case_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        scan_id: str | None = None,
    ) -> str:
        """Insert a new ``site_scans`` row and return the ``scan_id``.

        Args:
            url: Target URL for the investigation.
            scan_type: One of ``passive``, ``active``, ``full``.
            domain: Extracted domain from the URL.
            case_id: Optional linked core case ID.
            metadata: Arbitrary metadata dict.
            scan_id: Optional pre-generated ID.  When ``None`` a fresh UUID
                is created.  Pass a known ID so the DB record and the SSI
                job share the same identifier.

        Returns:
            The ``scan_id`` (UUID string).
        """
        scan_id = scan_id or str(uuid4())
        now = datetime.now(UTC)
        with self._session_factory() as session:
            session.execute(
                sa.insert(sql_schema.site_scans).values(
                    scan_id=scan_id,
                    case_id=case_id,
                    url=url,
                    normalized_url=normalize_url(url),
                    domain=domain,
                    scan_type=scan_type,
                    status="running",
                    metadata=metadata or {},
                    started_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()
        logger.debug("Created scan %s for %s", scan_id, url)
        return scan_id

    def update_scan(self, scan_id: str, **fields: Any) -> None:
        """Update arbitrary columns on a ``site_scans`` row.

        Args:
            scan_id: The scan to update.
            **fields: Column name/value pairs to set.
        """
        fields["updated_at"] = datetime.now(UTC)
        with self._session_factory() as session:
            session.execute(
                sa.update(sql_schema.site_scans).where(sql_schema.site_scans.c.scan_id == scan_id).values(**fields)
            )
            session.commit()

    def complete_scan(
        self,
        scan_id: str,
        *,
        status: str = "completed",
        passive_result: dict[str, Any] | None = None,
        active_result: dict[str, Any] | None = None,
        classification_result: dict[str, Any] | None = None,
        risk_score: float | None = None,
        taxonomy_version: str | None = None,
        wallet_count: int = 0,
        total_cost_usd: float | None = None,
        llm_input_tokens: int = 0,
        llm_output_tokens: int = 0,
        duration_seconds: float | None = None,
        error_message: str | None = None,
        evidence_path: str | None = None,
        evidence_zip_sha256: str | None = None,
    ) -> None:
        """Finalise a scan with aggregated results.

        Args:
            scan_id: The scan being completed.
            status: Terminal status (``completed`` or ``failed``).
            passive_result: Aggregated passive recon results (WHOIS, DNS, etc.).
            active_result: Aggregated active recon results (agent, browser).
            classification_result: Taxonomy classification output.
            risk_score: Overall fraud risk score (0–100).
            taxonomy_version: Version of the taxonomy used for classification.
            wallet_count: Number of wallets harvested.
            total_cost_usd: Total LLM API cost.
            llm_input_tokens: Total input tokens consumed.
            llm_output_tokens: Total output tokens consumed.
            duration_seconds: Wall-clock time for the investigation.
            error_message: Error details if the scan failed.
            evidence_path: GCS or local path to evidence bundle.
            evidence_zip_sha256: SHA-256 hash of the evidence ZIP.
        """
        now = datetime.now(UTC)
        values: dict[str, Any] = {
            "status": status,
            "wallet_count": wallet_count,
            "llm_input_tokens": llm_input_tokens,
            "llm_output_tokens": llm_output_tokens,
            "completed_at": now,
            "updated_at": now,
        }
        if passive_result is not None:
            values["passive_result"] = passive_result
        if active_result is not None:
            values["active_result"] = active_result
        if classification_result is not None:
            values["classification_result"] = classification_result
        if risk_score is not None:
            values["risk_score"] = risk_score
        if taxonomy_version is not None:
            values["taxonomy_version"] = taxonomy_version
        if total_cost_usd is not None:
            values["total_cost_usd"] = total_cost_usd
        if duration_seconds is not None:
            values["duration_seconds"] = duration_seconds
        if error_message is not None:
            values["error_message"] = error_message
        if evidence_path is not None:
            values["evidence_path"] = evidence_path
        if evidence_zip_sha256 is not None:
            values["evidence_zip_sha256"] = evidence_zip_sha256

        with self._session_factory() as session:
            session.execute(
                sa.update(sql_schema.site_scans).where(sql_schema.site_scans.c.scan_id == scan_id).values(**values)
            )
            session.commit()
        logger.info("Completed scan %s with status=%s", scan_id, status)

    def get_scan(self, scan_id: str) -> dict[str, Any] | None:
        """Return a single scan row as a dict, or ``None``.

        Args:
            scan_id: The scan to retrieve.

        Returns:
            Dict with column values, or ``None`` if not found.
        """
        with self._session_factory() as session:
            row = session.execute(
                sa.select(sql_schema.site_scans).where(sql_schema.site_scans.c.scan_id == scan_id)
            ).first()
        return dict(row._mapping) if row else None

    def list_scans(
        self,
        *,
        domain: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return a paginated list of scans, optionally filtered.

        Args:
            domain: Filter by domain.
            status: Filter by scan status.
            limit: Maximum number of results.
            offset: Pagination offset.

        Returns:
            List of scan dicts ordered by ``created_at`` descending.
        """
        stmt = sa.select(sql_schema.site_scans).order_by(sql_schema.site_scans.c.created_at.desc())
        if domain is not None:
            stmt = stmt.where(sql_schema.site_scans.c.domain == domain)
        if status is not None:
            stmt = stmt.where(sql_schema.site_scans.c.status == status)
        stmt = stmt.limit(limit).offset(offset)
        with self._session_factory() as session:
            rows = session.execute(stmt).all()
        return [dict(r._mapping) for r in rows]

    # ------------------------------------------------------------------
    # harvested_wallets CRUD
    # ------------------------------------------------------------------

    def add_wallet(
        self,
        *,
        scan_id: str,
        token_symbol: str,
        network_short: str,
        wallet_address: str,
        token_label: str = "",
        network_label: str = "",
        source: str = "js",
        confidence: float = 0.0,
        site_url: str = "",
        case_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        harvested_at: datetime | None = None,
    ) -> str:
        """Insert a single wallet row.

        On conflict (duplicate address for same scan + token + network),
        updates the confidence, source, and metadata.

        Args:
            scan_id: Parent scan ID.
            token_symbol: Cryptocurrency symbol (e.g. ``ETH``).
            network_short: Network abbreviation (e.g. ``ERC20``).
            wallet_address: The wallet address string.
            token_label: Human-readable token name.
            network_label: Human-readable network name.
            source: How the wallet was found (``js``, ``llm``, ``opportunistic``).
            confidence: Detection confidence (0.0–1.0).
            site_url: URL where the wallet was found.
            case_id: Optional linked core case ID.
            metadata: Arbitrary metadata dict.
            harvested_at: When the wallet was detected.

        Returns:
            The generated ``wallet_id``.
        """
        wallet_id = str(uuid4())
        with self._session_factory() as session:
            stmt = dialect_insert(session, sql_schema.harvested_wallets).values(
                wallet_id=wallet_id,
                scan_id=scan_id,
                case_id=case_id,
                token_label=token_label,
                token_symbol=token_symbol,
                network_label=network_label,
                network_short=network_short,
                wallet_address=wallet_address,
                source=source,
                confidence=confidence,
                site_url=site_url,
                metadata=metadata or {},
                harvested_at=harvested_at or datetime.now(UTC),
                created_at=datetime.now(UTC),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["scan_id", "token_symbol", "network_short", "wallet_address"],
                set_={
                    "confidence": confidence,
                    "source": source,
                    "metadata": metadata or {},
                },
            )
            session.execute(stmt)
            session.commit()
        return wallet_id

    def add_wallets_bulk(self, scan_id: str, wallets: list[dict[str, Any]]) -> int:
        """Bulk-insert wallets from a list of dicts.

        Args:
            scan_id: Parent scan ID.
            wallets: List of wallet dicts.  Required keys: ``token_symbol``,
                ``network_short``, ``wallet_address``.

        Returns:
            Count of rows inserted.
        """
        if not wallets:
            return 0
        now = datetime.now(UTC)
        rows = []
        for w in wallets:
            rows.append(
                {
                    "wallet_id": str(uuid4()),
                    "scan_id": scan_id,
                    "case_id": w.get("case_id"),
                    "token_label": w.get("token_label", ""),
                    "token_symbol": w["token_symbol"],
                    "network_label": w.get("network_label", ""),
                    "network_short": w["network_short"],
                    "wallet_address": w["wallet_address"],
                    "source": w.get("source", "js"),
                    "confidence": w.get("confidence", 0.0),
                    "site_url": w.get("site_url", ""),
                    "metadata": w.get("metadata", {}),
                    "harvested_at": w.get("harvested_at", now),
                    "created_at": now,
                }
            )
        with self._session_factory() as session:
            session.execute(sa.insert(sql_schema.harvested_wallets), rows)
            session.commit()
        logger.debug("Bulk-inserted %d wallets for scan %s", len(rows), scan_id)
        return len(rows)

    def get_wallets(self, scan_id: str) -> list[dict[str, Any]]:
        """Return all wallet rows for a scan.

        Args:
            scan_id: The scan to retrieve wallets for.

        Returns:
            List of wallet dicts ordered by ``created_at``.
        """
        with self._session_factory() as session:
            rows = session.execute(
                sa.select(sql_schema.harvested_wallets)
                .where(sql_schema.harvested_wallets.c.scan_id == scan_id)
                .order_by(sql_schema.harvested_wallets.c.created_at)
            ).all()
        return [dict(r._mapping) for r in rows]

    def search_wallets(
        self,
        *,
        address: str | None = None,
        token_symbol: str | None = None,
        limit: int = 100,
        deduplicate: bool = True,
    ) -> list[dict[str, Any]]:
        """Search wallets across all scans by address or token.

        Args:
            address: Filter by exact wallet address.
            token_symbol: Filter by token symbol (e.g. ``ETH``, ``BTC``).
            limit: Maximum number of results.
            deduplicate: When ``True`` (default), groups by
                ``(wallet_address, token_symbol, network_short)`` and returns
                one row per unique address with ``first_seen_at``,
                ``last_seen_at``, and ``seen_count`` aggregates.

        Returns:
            List of wallet dicts, deduplicated by default.
        """
        hw = sql_schema.harvested_wallets

        if deduplicate:
            stmt = sa.select(
                hw.c.wallet_address,
                hw.c.token_symbol,
                hw.c.token_label,
                hw.c.network_short,
                hw.c.network_label,
                sa.func.max(hw.c.confidence).label("confidence"),
                sa.func.max(hw.c.source).label("source"),
                sa.func.max(hw.c.site_url).label("site_url"),
                sa.func.min(hw.c.harvested_at).label("first_seen_at"),
                sa.func.max(hw.c.harvested_at).label("last_seen_at"),
                sa.func.count().label("seen_count"),
            ).group_by(
                hw.c.wallet_address,
                hw.c.token_symbol,
                hw.c.token_label,
                hw.c.network_short,
                hw.c.network_label,
            )
            if address is not None:
                stmt = stmt.where(hw.c.wallet_address == address)
            if token_symbol is not None:
                stmt = stmt.where(hw.c.token_symbol == token_symbol.upper())
            stmt = stmt.order_by(sa.desc("last_seen_at")).limit(limit)
        else:
            stmt = sa.select(hw)
            if address is not None:
                stmt = stmt.where(hw.c.wallet_address == address)
            if token_symbol is not None:
                stmt = stmt.where(hw.c.token_symbol == token_symbol.upper())
            stmt = stmt.order_by(hw.c.created_at.desc()).limit(limit)

        with self._session_factory() as session:
            rows = session.execute(stmt).all()
        return [dict(r._mapping) for r in rows]

    # ------------------------------------------------------------------
    # agent_sessions CRUD
    # ------------------------------------------------------------------

    def log_agent_action(
        self,
        *,
        scan_id: str,
        state: str,
        sequence: int,
        action_type: str | None = None,
        action_detail: dict[str, Any] | None = None,
        screenshot_path: str | None = None,
        page_url: str | None = None,
        dom_confidence: float | None = None,
        llm_model: str | None = None,
        llm_input_tokens: int | None = None,
        llm_output_tokens: int | None = None,
        cost_usd: float | None = None,
        duration_ms: int | float | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Record a single agent action in the audit trail.

        Args:
            scan_id: Parent scan ID.
            state: Agent state (e.g. ``completed``, ``error``).
            sequence: Step sequence number.
            action_type: Type of action performed.
            action_detail: JSON-serialisable action details.
            screenshot_path: Path to screenshot taken during this step.
            page_url: URL the agent was on.
            dom_confidence: DOM interaction confidence score.
            llm_model: LLM model used for this step.
            llm_input_tokens: Input tokens for this step.
            llm_output_tokens: Output tokens for this step.
            cost_usd: API cost for this step.
            duration_ms: Duration of this step in milliseconds.
            error: Error message if the step failed.
            metadata: Arbitrary metadata dict.

        Returns:
            The generated ``session_id``.
        """
        session_id = str(uuid4())
        with self._session_factory() as session:
            session.execute(
                sa.insert(sql_schema.agent_sessions).values(
                    session_id=session_id,
                    scan_id=scan_id,
                    state=state,
                    action_type=action_type,
                    action_detail=action_detail,
                    screenshot_path=screenshot_path,
                    page_url=page_url,
                    dom_confidence=dom_confidence,
                    llm_model=llm_model,
                    llm_input_tokens=llm_input_tokens,
                    llm_output_tokens=llm_output_tokens,
                    cost_usd=cost_usd,
                    duration_ms=int(duration_ms) if duration_ms is not None else None,
                    error=error,
                    sequence=sequence,
                    metadata=metadata or {},
                    created_at=datetime.now(UTC),
                )
            )
            session.commit()
        return session_id

    def get_agent_actions(self, scan_id: str) -> list[dict[str, Any]]:
        """Return the full agent action trail for a scan, ordered by sequence.

        Args:
            scan_id: The scan to retrieve agent actions for.

        Returns:
            List of agent action dicts ordered by ``sequence``.
        """
        with self._session_factory() as session:
            rows = session.execute(
                sa.select(sql_schema.agent_sessions)
                .where(sql_schema.agent_sessions.c.scan_id == scan_id)
                .order_by(sql_schema.agent_sessions.c.sequence)
            ).all()
        return [dict(r._mapping) for r in rows]

    # ------------------------------------------------------------------
    # pii_exposures CRUD
    # ------------------------------------------------------------------

    def add_pii_exposure(
        self,
        *,
        scan_id: str,
        field_type: str,
        field_label: str | None = None,
        form_action: str | None = None,
        page_url: str | None = None,
        is_required: bool | None = None,
        was_submitted: bool = False,
        case_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        detected_at: datetime | None = None,
    ) -> str:
        """Record a PII field found on the scam site.

        Args:
            scan_id: Parent scan ID.
            field_type: Category of PII (``email``, ``password``, ``phone``, etc.).
            field_label: Label or name attribute of the form field.
            form_action: Form action URL.
            page_url: URL of the page containing the form.
            is_required: Whether the field was marked required.
            was_submitted: Whether synthetic PII was submitted.
            case_id: Optional linked core case ID.
            metadata: Arbitrary metadata dict.
            detected_at: When the field was detected.

        Returns:
            The generated ``exposure_id``.
        """
        exposure_id = str(uuid4())
        with self._session_factory() as session:
            session.execute(
                sa.insert(sql_schema.pii_exposures).values(
                    exposure_id=exposure_id,
                    scan_id=scan_id,
                    case_id=case_id,
                    field_type=field_type,
                    field_label=field_label,
                    form_action=form_action,
                    page_url=page_url,
                    is_required=is_required,
                    was_submitted=was_submitted,
                    metadata=metadata or {},
                    detected_at=detected_at or datetime.now(UTC),
                    created_at=datetime.now(UTC),
                )
            )
            session.commit()
        return exposure_id

    def add_pii_exposures_bulk(self, scan_id: str, exposures: list[dict[str, Any]]) -> int:
        """Bulk-insert PII exposure records.

        Args:
            scan_id: Parent scan ID.
            exposures: List of exposure dicts.  Required key: ``field_type``.

        Returns:
            Count of rows inserted.
        """
        if not exposures:
            return 0
        now = datetime.now(UTC)
        rows = []
        for e in exposures:
            rows.append(
                {
                    "exposure_id": str(uuid4()),
                    "scan_id": scan_id,
                    "case_id": e.get("case_id"),
                    "field_type": e["field_type"],
                    "field_label": e.get("field_label"),
                    "form_action": e.get("form_action"),
                    "page_url": e.get("page_url"),
                    "is_required": e.get("is_required"),
                    "was_submitted": e.get("was_submitted", False),
                    "metadata": e.get("metadata", {}),
                    "detected_at": e.get("detected_at", now),
                    "created_at": now,
                }
            )
        with self._session_factory() as session:
            session.execute(sa.insert(sql_schema.pii_exposures), rows)
            session.commit()
        logger.debug("Bulk-inserted %d PII exposures for scan %s", len(rows), scan_id)
        return len(rows)

    def get_pii_exposures(self, scan_id: str) -> list[dict[str, Any]]:
        """Return all PII exposure records for a scan.

        Args:
            scan_id: The scan to retrieve exposures for.

        Returns:
            List of exposure dicts ordered by ``created_at``.
        """
        with self._session_factory() as session:
            rows = session.execute(
                sa.select(sql_schema.pii_exposures)
                .where(sql_schema.pii_exposures.c.scan_id == scan_id)
                .order_by(sql_schema.pii_exposures.c.created_at)
            ).all()
        return [dict(r._mapping) for r in rows]
