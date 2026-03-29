"""Unit tests for the SQL writer helper."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.store import sql as sql_schema
from i4g.store.sql_writer import (
    CaseBundle,
    CasePayload,
    EntityMentionPayload,
    EntityPayload,
    IndicatorPayload,
    IndicatorSourcePayload,
    SourceDocumentPayload,
    SqlWriter,
)


@pytest.fixture()
def writer(tmp_path) -> Iterator[tuple[SqlWriter, sa.Engine]]:
    """Provide a SqlWriter backed by an isolated SQLite database."""

    db_path = tmp_path / "sql_writer.db"
    engine = sa.create_engine(f"sqlite:///{db_path}", future=True)
    sql_schema.METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    yield SqlWriter(session_factory=factory), engine
    engine.dispose()


def _build_bundle(case_id: str, *, doc_alias: str, text: str) -> CaseBundle:
    return CaseBundle(
        case=CasePayload(
            case_id=case_id,
            dataset="account_list",
            source_type="ocr",
            classification="crypto_investment",
            confidence=0.91,
            text=text,
        ),
        documents=[
            SourceDocumentPayload(
                alias=doc_alias,
                title="OCR chunk",
                text=text,
                chunk_index=0,
                chunk_count=1,
            )
        ],
        entities=[
            EntityPayload(
                alias="wallet-1",
                entity_type="wallet_address",
                canonical_value="0xabc",
                confidence=0.84,
                mentions=[
                    EntityMentionPayload(document_alias=doc_alias, span_start=10, span_end=20, sentence="Wallet ref")
                ],
            )
        ],
        indicators=[
            IndicatorPayload(
                category="wallet",
                type="crypto",
                number="0xabc",
                dataset="account_list",
                confidence=0.65,
                sources=[IndicatorSourcePayload(document_alias=doc_alias, entity_alias="wallet-1")],
            )
        ],
    )


def test_writer_persists_case_documents_and_entities(writer):
    sql_writer, engine = writer
    bundle = _build_bundle("case-123", doc_alias="doc-a", text="Send USDT to 0xabc")
    result = sql_writer.persist_case_bundle(bundle, ingestion_run_id="run-1")

    assert result.case_id == "case-123"
    assert len(result.document_ids) == 1
    assert len(result.entity_ids) == 1
    assert len(result.indicator_ids) == 1

    with engine.connect() as conn:
        case_row = conn.execute(sa.select(sql_schema.cases).where(sql_schema.cases.c.case_id == "case-123")).one()
        assert case_row.dataset == "account_list"
        assert case_row.ingestion_run_id == "run-1"
        assert case_row.classification == "crypto_investment"
        expected_hash = hashlib.sha256(bundle.case.text.encode("utf-8")).hexdigest()
        assert case_row.raw_text_sha256 == expected_hash

        docs = conn.execute(sa.select(sql_schema.source_documents)).fetchall()
        assert len(docs) == 1
        assert docs[0].case_id == "case-123"

        entities = conn.execute(sa.select(sql_schema.entities)).fetchall()
        assert len(entities) == 1
        assert entities[0].canonical_value == "0xabc"

        mentions = conn.execute(sa.select(sql_schema.entity_mentions)).fetchall()
        assert len(mentions) == 1
        assert mentions[0].document_id == docs[0].document_id

        indicator_sources = conn.execute(sa.select(sql_schema.indicator_sources)).fetchall()
        assert len(indicator_sources) == 1
        assert indicator_sources[0].document_id == docs[0].document_id


def test_writer_upserts_entities_and_indicator_sources(writer):
    sql_writer, engine = writer
    first_bundle = _build_bundle("case-999", doc_alias="doc-1", text="Original text")
    initial_result = sql_writer.persist_case_bundle(first_bundle)

    # Re-run with updated metadata and a new document reference
    second_bundle = CaseBundle(
        case=CasePayload(
            case_id="case-999",
            dataset="account_list",
            source_type="ocr",
            classification="romance_scam",
            confidence=0.51,
            text="Updated",
        ),
        documents=[
            SourceDocumentPayload(
                alias="doc-2",
                document_id="doc-static",
                text="Updated doc",
                chunk_index=1,
                chunk_count=2,
            )
        ],
        entities=[
            EntityPayload(
                alias="wallet-1",
                entity_type="wallet_address",
                canonical_value="0xabc",
                confidence=0.95,
                mentions=[EntityMentionPayload(document_alias="doc-2", span_start=5, span_end=15, sentence="New ref")],
            )
        ],
        indicators=[
            IndicatorPayload(
                category="wallet",
                type="crypto",
                number="0xabc",
                dataset="account_list",
                confidence=0.77,
                sources=[IndicatorSourcePayload(document_alias="doc-2", entity_alias="wallet-1")],
            )
        ],
    )
    updated_result = sql_writer.persist_case_bundle(second_bundle)

    with engine.connect() as conn:
        case_row = conn.execute(sa.select(sql_schema.cases).where(sql_schema.cases.c.case_id == "case-999")).one()
        assert case_row.classification == "romance_scam"

        entities = conn.execute(sa.select(sql_schema.entities)).fetchall()
        assert len(entities) == 1
        mentions = conn.execute(sa.select(sql_schema.entity_mentions)).fetchall()
        assert len(mentions) == 1
        assert mentions[0].document_id == "doc-static"

        indicator_rows = conn.execute(sa.select(sql_schema.indicators)).fetchall()
        assert len(indicator_rows) == 1
        assert indicator_rows[0].indicator_id == updated_result.indicator_ids[0]
        indicator_sources = conn.execute(sa.select(sql_schema.indicator_sources)).fetchall()
        assert len(indicator_sources) == 1
        assert indicator_sources[0].document_id == "doc-static"

    assert initial_result.indicator_ids[0] == updated_result.indicator_ids[0]


def test_reingest_with_preprocessing_change_duplicates(writer):
    """Re-ingesting the same raw data with a minor text change produces a duplicate
    because the SHA-256 hash changes.  This documents the edge case that bootstrap
    must wipe before re-ingesting when preprocessing logic changes."""

    sql_writer, engine = writer

    original_text = "Send USDT to 0xabc via Trust Wallet"
    bundle_v1 = CaseBundle(
        case=CasePayload(
            case_id="case-dup-001",
            dataset="test_dataset",
            source_type="form",
            classification="crypto_investment",
            confidence=0.85,
            text=original_text,
        ),
        documents=[SourceDocumentPayload(alias="d1", title="v1", text=original_text, chunk_index=0, chunk_count=1)],
        entities=[],
        indicators=[],
    )
    sql_writer.persist_case_bundle(bundle_v1, ingestion_run_id="run-a")

    # Simulate a preprocessing change: extra whitespace normalisation
    modified_text = "Send  USDT  to  0xabc  via  Trust  Wallet"  # same semantics, different bytes
    assert modified_text != original_text  # different text → different hash
    bundle_v2 = CaseBundle(
        case=CasePayload(
            case_id="case-dup-002",  # new id (real re-ingest generates new UUIDs)
            dataset="test_dataset",
            source_type="form",
            classification="crypto_investment",
            confidence=0.85,
            text=modified_text,
        ),
        documents=[SourceDocumentPayload(alias="d2", title="v2", text=modified_text, chunk_index=0, chunk_count=1)],
        entities=[],
        indicators=[],
    )
    sql_writer.persist_case_bundle(bundle_v2, ingestion_run_id="run-b")

    with engine.connect() as conn:
        rows = conn.execute(sa.select(sql_schema.cases)).fetchall()
        # Both rows exist because their SHA-256 hashes differ — this IS a duplicate
        assert len(rows) == 2, (
            "Expected 2 case rows (duplication) when text changes between ingestion runs. "
            "Bootstrap must wipe the DB before re-ingesting to avoid this."
        )


def test_reingest_same_content_deduplicates(writer):
    """Re-ingesting identical content (same dataset + SHA) correctly deduplicates."""

    sql_writer, engine = writer

    text = "Victim wired $5000 to unknown wallet"
    bundle_a = CaseBundle(
        case=CasePayload(
            case_id="case-dedup-a",
            dataset="dedup_ds",
            source_type="form",
            classification="wire_fraud",
            confidence=0.90,
            text=text,
        ),
        documents=[SourceDocumentPayload(alias="d1", title="doc", text=text, chunk_index=0, chunk_count=1)],
        entities=[],
        indicators=[],
    )
    result_a = sql_writer.persist_case_bundle(bundle_a)

    # Re-ingest exact same content with different case_id → should dedup to original
    bundle_b = CaseBundle(
        case=CasePayload(
            case_id="case-dedup-b",
            dataset="dedup_ds",
            source_type="form",
            classification="wire_fraud",
            confidence=0.92,
            text=text,
        ),
        documents=[SourceDocumentPayload(alias="d2", title="doc-v2", text=text, chunk_index=0, chunk_count=1)],
        entities=[],
        indicators=[],
    )
    result_b = sql_writer.persist_case_bundle(bundle_b)

    assert result_b.case_id == result_a.case_id, "Same content should dedup to the original case_id"

    with engine.connect() as conn:
        rows = conn.execute(sa.select(sql_schema.cases)).fetchall()
        assert len(rows) == 1, "Only one case should exist after deduplication"
