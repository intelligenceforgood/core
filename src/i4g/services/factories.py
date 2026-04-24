"""Factory helpers that instantiate core services based on configuration.

These helpers centralize the logic for honoring the environment-specific
settings declared in :mod:`i4g.settings`. They return the concrete storage or
vector store implementations compatible with the current environment profile,
raising ``NotImplementedError`` when a backend is declared but not yet
implemented.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from i4g.reports.bundle_builder import BundleBuilder
from i4g.reports.bundle_candidates import BundleCandidateProvider
from i4g.reports.dossier_context import DossierContextLoader
from i4g.services.classifier import FraudClassifier
from i4g.services.retention import RetentionService
from i4g.services.vertex_writer import VertexDocumentWriter
from i4g.settings import Settings, get_settings
from i4g.storage import EvidenceStorage
from i4g.store.actor_identity_edge_store import ActorIdentityEdgeStore
from i4g.store.actor_identity_store import ActorIdentityStore
from i4g.store.analytics_store import AnalyticsStore
from i4g.store.annotation_store import AnnotationStore
from i4g.store.blocklist_hit_store import BlocklistHitStore
from i4g.store.domain_discovery_store import DomainDiscoveryStore
from i4g.store.dossier_queue_store import DossierQueueStore
from i4g.store.engagement_store import EngagementStore
from i4g.store.entity_store import EntityStore
from i4g.store.ingestion_retry_store import IngestionRetryStore
from i4g.store.ingestion_run_tracker import IngestionRunTracker
from i4g.store.intake_store import IntakeStore
from i4g.store.review_store import ReviewStore
from i4g.store.sql import METADATA
from i4g.store.sql import session_factory as build_sql_session_factory
from i4g.store.sql_writer import SqlWriter
from i4g.store.ssi_events_store import SsiEventsStore
from i4g.store.ssi_store import SsiStore
from i4g.store.structured import StructuredStore
from i4g.store.threat_actor_store import ThreatActorStore
from i4g.store.threat_campaign_store import ThreatCampaignStore
from i4g.store.vector import VectorStore
from i4g.store.watchlist_store import WatchlistStore


def build_structured_store(db_path: str | Path | None = None) -> StructuredStore:
    """Return a structured-store instance that matches the configured backend.

    Args:
        db_path: Optional path override for local SQLite. Ignored when the
            configured backend is Cloud SQL.

    Returns:
        Instantiated :class:`StructuredStore`.
    """
    settings = get_settings()
    backend = settings.storage.structured_backend
    if backend == "cloudsql":
        return StructuredStore(session_factory=build_sql_session_factory())
    # sqlite (default) or any local backend
    return StructuredStore(db_path=db_path)


def build_entity_store() -> EntityStore:
    """Instantiate an :class:`EntityStore` backed by the configured SQL engine."""

    session_factory = build_sql_session_factory()
    return EntityStore(session_factory=session_factory)


def build_review_store(db_path: str | Path | None = None) -> ReviewStore:
    """Return a :class:`ReviewStore` honoring the structured backend settings.

    Note:
        We now use ReviewStore (formerly SqlAlchemyReviewStore) for both SQLite
        and Cloud SQL to ensure logic parity between environments.
    """

    settings = get_settings()
    backend = settings.storage.structured_backend
    session_factory = build_sql_session_factory()

    if backend == "sqlite":
        # Ensure tables exist for local development, mimicking the legacy store's behavior
        # where it auto-initialized the schema.
        engine = session_factory.kw["bind"]
        METADATA.create_all(engine)

    return ReviewStore(session_factory=session_factory)


def build_engagement_store() -> EngagementStore:
    """Return an :class:`EngagementStore` backed by the configured SQL engine."""
    session_factory = build_sql_session_factory()
    return EngagementStore(session_factory=session_factory)


def build_vector_store(
    *,
    backend: str | None = None,
    persist_dir: str | Path | None = None,
    embedding_model: str | None = None,
    collection_name: str | None = None,
    reset: bool = False,
) -> VectorStore:
    """Return a vector store implementation consistent with current settings.

    Args:
    backend: Explicit backend to use (overrides configured default).
    persist_dir: Optional directory override for the vector backend.
        embedding_model: Embedding model identifier. Defaults to the configured
            ``settings.vector.embedding_model`` when ``None``.
        collection_name: Optional override for the vector collection/index
            name. Defaults to ``settings.vector.collection``.
        reset: Whether to reset any persisted artifacts before instantiation.

    Returns:
    Configured :class:`VectorStore` instance.

    Raises:
        NotImplementedError: If the configured backend lacks an implementation.
    """

    settings = get_settings()
    resolved_backend = (backend or settings.vector.backend).lower()
    model_name = embedding_model or settings.vector.embedding_model
    collection = collection_name or settings.vector.collection

    if resolved_backend in {"chroma", "faiss"}:
        return VectorStore(
            persist_dir=str(persist_dir) if persist_dir is not None else None,
            embedding_model=model_name,
            backend=resolved_backend,
            collection_name=collection,
            reset=reset,
        )

    if resolved_backend == "pgvector":
        raise NotImplementedError("pgvector backend not implemented yet")

    if resolved_backend == "vertex_ai":
        return VectorStore(
            backend="vertex_ai",
            reset=reset,
        )

    raise NotImplementedError(f"Unsupported vector backend '{resolved_backend}'")


def build_intake_store(db_path: str | Path | None = None) -> IntakeStore:
    """Return an :class:`IntakeStore` aligned with the structured backend."""
    settings = get_settings()
    pii_key = settings.crypto.pii_key
    backend = settings.storage.structured_backend
    if backend == "cloudsql":
        return IntakeStore(session_factory=build_sql_session_factory(), pii_key=pii_key)
    return IntakeStore(db_path=db_path, pii_key=pii_key)


def build_evidence_storage(*, local_dir: str | Path | None = None) -> EvidenceStorage:
    """Instantiate the configured evidence storage provider."""

    path = Path(local_dir) if isinstance(local_dir, str) else local_dir
    return EvidenceStorage(local_dir=path)


def build_sql_writer(*, settings: Settings | None = None) -> SqlWriter:
    """Create a SqlWriter bound to the configured SQLAlchemy engine."""

    session_factory = build_sql_session_factory(settings=settings)
    return SqlWriter(session_factory=session_factory)


def build_ingestion_run_tracker(*, settings: Settings | None = None) -> IngestionRunTracker:
    """Return a tracker for ingestion run metrics."""

    session_factory = build_sql_session_factory(settings=settings)
    return IngestionRunTracker(session_factory=session_factory)


def build_ingestion_retry_store(*, settings: Settings | None = None) -> IngestionRetryStore:
    """Return a store for managing ingestion retry queue entries."""

    session_factory = build_sql_session_factory(settings=settings)
    return IngestionRetryStore(session_factory=session_factory)


def build_vertex_writer(*, settings: Settings | None = None) -> VertexDocumentWriter:
    """Instantiate a Vertex document writer honoring current settings/env."""

    resolved = settings or get_settings()
    project = resolved.vector.vertex_ai_project
    location = resolved.vector.vertex_ai_location or "global"
    data_store = resolved.vector.vertex_ai_data_store
    branch = resolved.vector.vertex_ai_branch or "default_branch"

    if not project or not data_store:
        raise RuntimeError(
            "Vertex writer requires project and data store. Set I4G_VERTEX_SEARCH_* env vars or vector settings.",
        )

    return VertexDocumentWriter(
        project=project,
        location=location,
        data_store_id=data_store,
        branch=branch,
        default_dataset=resolved.ingestion.default_dataset,
        timeout_seconds=resolved.ingestion.fanout_timeout_seconds,
    )


def build_dossier_queue_store(db_path: str | Path | None = None) -> DossierQueueStore:
    """Return a DossierQueueStore instance backed by the configured backend."""
    settings = get_settings()
    backend = settings.storage.structured_backend
    if backend == "cloudsql":
        return DossierQueueStore(session_factory=build_sql_session_factory())
    return DossierQueueStore(db_path=db_path)


def build_ssi_store(db_path: str | Path | None = None) -> SsiStore:
    """Return an :class:`SsiStore` aligned with the structured backend.

    Args:
        db_path: Optional path override for local SQLite.  Ignored when the
            configured backend is Cloud SQL.

    Returns:
        Instantiated :class:`SsiStore`.
    """
    settings = get_settings()
    backend = settings.storage.structured_backend
    if backend == "cloudsql":
        return SsiStore(session_factory=build_sql_session_factory())
    return SsiStore(db_path=db_path)


def build_ssi_events_store(db_path: str | Path | None = None) -> SsiEventsStore:
    """Return an :class:`SsiEventsStore` aligned with the structured backend.

    Args:
        db_path: Optional path override for local SQLite.  Ignored when the
            configured backend is Cloud SQL.

    Returns:
        Instantiated :class:`SsiEventsStore`.
    """
    settings = get_settings()
    backend = settings.storage.structured_backend
    if backend == "cloudsql":
        return SsiEventsStore(session_factory=build_sql_session_factory())
    return SsiEventsStore(db_path=db_path)


def build_threat_campaign_store(db_path: str | Path | None = None) -> ThreatCampaignStore:
    """Return a :class:`ThreatCampaignStore` aligned with the structured backend.

    Args:
        db_path: Optional path override for local SQLite.  Ignored when the
            configured backend is Cloud SQL.

    Returns:
        Instantiated :class:`ThreatCampaignStore`.
    """
    settings = get_settings()
    backend = settings.storage.structured_backend
    if backend == "cloudsql":
        return ThreatCampaignStore(session_factory=build_sql_session_factory())
    return ThreatCampaignStore(db_path=db_path)


def build_analytics_store(db_path: str | Path | None = None) -> AnalyticsStore:
    """Return an :class:`AnalyticsStore` aligned with the structured backend.

    Args:
        db_path: Optional path override for local SQLite.  Ignored when the
            configured backend is Cloud SQL.

    Returns:
        Instantiated :class:`AnalyticsStore`.
    """
    settings = get_settings()
    backend = settings.storage.structured_backend
    if backend == "cloudsql":
        return AnalyticsStore(session_factory=build_sql_session_factory())
    return AnalyticsStore(db_path=db_path)


def build_annotation_store(db_path: str | Path | None = None) -> AnnotationStore:
    """Return an :class:`AnnotationStore` aligned with the structured backend.

    Args:
        db_path: Optional path override for local SQLite.  Ignored when the
            configured backend is Cloud SQL.

    Returns:
        Instantiated :class:`AnnotationStore`.
    """
    settings = get_settings()
    backend = settings.storage.structured_backend
    if backend == "cloudsql":
        return AnnotationStore(session_factory=build_sql_session_factory())
    return AnnotationStore(db_path=db_path)


def build_watchlist_store(db_path: str | Path | None = None) -> WatchlistStore:
    """Return a :class:`WatchlistStore` aligned with the structured backend.

    Args:
        db_path: Optional path override for local SQLite.  Ignored when the
            configured backend is Cloud SQL.

    Returns:
        Instantiated :class:`WatchlistStore`.
    """
    settings = get_settings()
    backend = settings.storage.structured_backend
    if backend == "cloudsql":
        return WatchlistStore(session_factory=build_sql_session_factory())
    return WatchlistStore(db_path=db_path)


def build_threat_actor_store(db_path: str | Path | None = None) -> ThreatActorStore:
    """Return a :class:`ThreatActorStore` aligned with the structured backend."""
    settings = get_settings()
    backend = settings.storage.structured_backend
    if backend == "cloudsql":
        return ThreatActorStore(session_factory=build_sql_session_factory())
    return ThreatActorStore(db_path=db_path)


def build_actor_identity_store(db_path: str | Path | None = None) -> ActorIdentityStore:
    """Return an :class:`ActorIdentityStore` aligned with the structured backend."""
    settings = get_settings()
    backend = settings.storage.structured_backend
    if backend == "cloudsql":
        return ActorIdentityStore(session_factory=build_sql_session_factory())
    return ActorIdentityStore(db_path=db_path)


def build_actor_identity_edge_store(db_path: str | Path | None = None) -> ActorIdentityEdgeStore:
    """Return an :class:`ActorIdentityEdgeStore` aligned with the structured backend."""
    settings = get_settings()
    backend = settings.storage.structured_backend
    if backend == "cloudsql":
        return ActorIdentityEdgeStore(session_factory=build_sql_session_factory())
    return ActorIdentityEdgeStore(db_path=db_path)


def build_blocklist_hit_store(db_path: str | Path | None = None) -> BlocklistHitStore:
    """Return a :class:`BlocklistHitStore` aligned with the structured backend."""
    settings = get_settings()
    backend = settings.storage.structured_backend
    if backend == "cloudsql":
        return BlocklistHitStore(session_factory=build_sql_session_factory())
    return BlocklistHitStore(db_path=db_path)


def build_domain_discovery_store(db_path: str | Path | None = None) -> DomainDiscoveryStore:
    """Return a :class:`DomainDiscoveryStore` aligned with the structured backend."""
    settings = get_settings()
    backend = settings.storage.structured_backend
    if backend == "cloudsql":
        return DomainDiscoveryStore(session_factory=build_sql_session_factory())
    return DomainDiscoveryStore(db_path=db_path)


def build_bundle_builder(
    *,
    queue_store: DossierQueueStore | None = None,
    shared_drive_parent_id: str | None = None,
) -> BundleBuilder:
    """Instantiate a BundleBuilder with Drive metadata derived from settings."""

    settings = get_settings()
    parent_id = shared_drive_parent_id or settings.report.drive_parent_id
    store = queue_store or build_dossier_queue_store()
    return BundleBuilder(queue_store=store, shared_drive_parent_id=parent_id)


def build_bundle_candidate_provider(
    *,
    review_store: ReviewStore | None = None,
    structured_store: StructuredStore | None = None,
) -> BundleCandidateProvider:
    """Return a provider that yields dossier candidates from accepted reviews."""

    resolved_review = review_store or build_review_store()
    resolved_structured = structured_store or build_structured_store()
    return BundleCandidateProvider(review_store=resolved_review, structured_store=resolved_structured)


def build_dossier_context_loader(
    *,
    structured_store: StructuredStore | None = None,
    review_store: ReviewStore | None = None,
) -> DossierContextLoader:
    """Instantiate a context loader that hydrates dossier cases with metadata."""

    resolved_structured = structured_store or build_structured_store()
    resolved_review = review_store or build_review_store()
    return DossierContextLoader(structured_store=resolved_structured, review_store=resolved_review)


def build_fraud_classifier() -> FraudClassifier:
    """Return a configured FraudClassifier instance."""
    from i4g.llm.client import build_llm_client

    return FraudClassifier(llm_client=build_llm_client())


def build_llm_client(*, settings: Settings | None = None):
    """Return a simple LLM client (``generate(prompt) -> str``).

    Delegates to :func:`i4g.llm.client.build_llm_client`.
    """
    from i4g.llm.client import build_llm_client as _build

    return _build(settings=settings)


def build_langchain_llm(*, settings: Settings | None = None):
    """Return a LangChain-compatible LLM (``invoke(messages)``).

    Delegates to :func:`i4g.llm.client.build_langchain_llm`.
    """
    from i4g.llm.client import build_langchain_llm as _build

    return _build(settings=settings)


def build_retention_service() -> RetentionService:
    """Instantiate a :class:`RetentionService` with all configured stores.

    The service handles automated retention purge and GDPR operations.
    Optional stores (evidence, vector) are attached when
    available — failures are silently skipped.
    """
    sf = build_sql_session_factory()

    evidence_storage = None
    with contextlib.suppress(Exception):
        evidence_storage = build_evidence_storage()

    vector_store = None
    with contextlib.suppress(Exception):
        vector_store = build_vector_store()

    return RetentionService(
        sf,
        evidence_storage=evidence_storage,
        vector_store=vector_store,
    )


def build_inference_client():
    """Return the configured inference backend.

    Returns ``MLPlatformClient`` when ``settings.ml.inference_backend``
    is ``"ml_platform"``, otherwise returns the existing LLM-based
    classifier.
    """
    settings = get_settings()
    if settings.ml.inference_backend == "ml_platform":
        from i4g.ml.client import MLPlatformClient

        return MLPlatformClient()
    return build_llm_client()


def build_entity_extraction_client():
    """Return the configured entity extraction backend.

    Returns ``MLPlatformClient`` when
    ``settings.ml.entity_extraction_backend`` is ``"ml_platform"``,
    otherwise returns the LLM client for use with
    ``extract_semantic_entities()``.
    """
    settings = get_settings()
    if settings.ml.entity_extraction_backend == "ml_platform":
        from i4g.ml.client import MLPlatformClient

        return MLPlatformClient()
    return build_llm_client()


def build_risk_scoring_client():
    """Return the configured risk scoring backend.

    Returns ``MLPlatformClient`` when
    ``settings.ml.risk_scoring_backend`` is ``"ml_platform"``,
    otherwise returns the LLM client.
    """
    settings = get_settings()
    if settings.ml.risk_scoring_backend == "ml_platform":
        from i4g.ml.client import MLPlatformClient

        return MLPlatformClient()
    return build_llm_client()


def build_similarity_client():
    """Return the configured document similarity backend.

    Returns ``MLPlatformClient`` when
    ``settings.ml.similarity_backend`` is ``"ml_platform"``,
    otherwise returns the LLM client.
    """
    settings = get_settings()
    if settings.ml.similarity_backend == "ml_platform":
        from i4g.ml.client import MLPlatformClient

        return MLPlatformClient()
    return build_llm_client()


__all__ = [
    "build_fraud_classifier",
    "build_llm_client",
    "build_langchain_llm",
    "build_structured_store",
    "build_entity_store",
    "build_review_store",
    "build_vector_store",
    "build_intake_store",
    "build_evidence_storage",
    "build_sql_writer",
    "build_ingestion_run_tracker",
    "build_ingestion_retry_store",
    "build_vertex_writer",
    "build_dossier_queue_store",
    "build_ssi_store",
    "build_ssi_events_store",
    "build_bundle_builder",
    "build_bundle_candidate_provider",
    "build_dossier_context_loader",
    "build_retention_service",
    "build_threat_campaign_store",
    "build_threat_actor_store",
    "build_actor_identity_store",
    "build_actor_identity_edge_store",
    "build_blocklist_hit_store",
    "build_domain_discovery_store",
    "build_analytics_store",
    "build_annotation_store",
    "build_inference_client",
    "build_entity_extraction_client",
    "build_risk_scoring_client",
    "build_similarity_client",
]
