"""Cloud Run job entrypoint for ingestion pipelines."""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from google.cloud import storage

from i4g.observability import get_observability
from i4g.ocr.tesseract import batch_extract_text
from i4g.services.alerting import get_alerting_service
from i4g.services.factories import (
    build_fraud_classifier,
    build_ingestion_retry_store,
    build_ingestion_run_tracker,
    build_structured_store,
    build_vector_store,
)
from i4g.services.ingest_payloads import prepare_ingest_payload
from i4g.settings import get_settings
from i4g.store.ingest import IngestPipeline
from i4g.store.sql_writer import SqlWriterResult
from i4g.worker.logging import configure_job_logging

LOGGER = logging.getLogger("i4g.worker.jobs.ingest")


def _download_and_yield(blob: storage.Blob) -> Iterator[dict[str, Any]]:
    """Downloads a JSONL blob to a temp file and yields records."""
    fd, tmp_path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        LOGGER.info("Downloading dataset from gs://%s/%s to %s", blob.bucket.name, blob.name, tmp_path)
        blob.download_to_filename(tmp_path)
        with open(tmp_path, encoding="utf-8") as handle:
            yield from _yield_from_handle(handle)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _process_images_and_yield(
    image_paths: list[str | Path], is_gcs: bool = False, bucket: storage.Bucket | None = None
) -> Iterator[dict[str, Any]]:
    """
    Runs OCR on a list of images and yields the results.

    Args:
        image_paths: List of paths (local) or blob names (if is_gcs).
        is_gcs: Whether the paths are GCS blob names.
        bucket: The GCS bucket object (required if is_gcs is True).
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        if is_gcs:
            if not bucket:
                raise ValueError("Bucket is required for GCS image processing")

            LOGGER.info("Downloading %d images from GCS to %s", len(image_paths), tmp_path)
            for blob_name in image_paths:
                blob = bucket.blob(str(blob_name))
                # Keep the filename
                filename = Path(str(blob_name)).name
                blob.download_to_filename(tmp_path / filename)
        else:
            LOGGER.info("Staging %d local images to %s", len(image_paths), tmp_path)
            for img_path in image_paths:
                if isinstance(img_path, str):
                    img_path = Path(img_path)
                shutil.copy(img_path, tmp_path / img_path.name)

        LOGGER.info("Running OCR on staged images in %s", tmp_path)
        # batch_extract_text returns List[Dict[str, str]]
        results = batch_extract_text(str(tmp_path))

        for result in results:
            filename = result["file"]

            # Find original reference to construct URL
            original_ref = None
            for p in image_paths:
                if Path(str(p)).name == filename:
                    original_ref = p
                    break

            enrichment = {}
            if original_ref:
                url = str(original_ref)
                if is_gcs and bucket:
                    url = f"https://storage.cloud.google.com/{bucket.name}/{original_ref}"

                enrichment = {
                    "source_url": url,
                    "document_title": filename,
                    "metadata": {
                        "files": [
                            {
                                "name": filename,
                                "type": "document" if filename.lower().endswith(".pdf") else "image",
                                "url": url,
                            }
                        ]
                    },
                }

            record = {**result, **enrichment}
            yield record


def _load_data(path: Path | str) -> Iterator[dict[str, Any]]:
    """
    Loads data from a path (local or GCS).
    Supports .jsonl files and image files (via OCR).
    """
    path_str = str(path)
    image_extensions = {".png", ".jpg", ".jpeg", ".pdf", ".tiff", ".bmp"}

    if path_str.startswith("gs://"):
        client = storage.Client()
        parts = path_str[5:].split("/", 1)
        bucket_name = parts[0]
        blob_name = parts[1] if len(parts) > 1 else ""
        bucket = client.bucket(bucket_name)

        # List all blobs matching the prefix
        LOGGER.info("Listing blobs in bucket %s with prefix %r", bucket_name, blob_name)
        blobs = list(client.list_blobs(bucket, prefix=blob_name))
        LOGGER.info("Found %d blobs matching prefix", len(blobs))

        jsonl_blobs = []
        image_blobs = []

        for b in blobs:
            if b.name.endswith(".jsonl"):
                jsonl_blobs.append(b)
            elif any(b.name.lower().endswith(ext) for ext in image_extensions):
                image_blobs.append(b.name)

        if jsonl_blobs:
            LOGGER.info("Found %d .jsonl files in %s", len(jsonl_blobs), path_str)
            for blob in jsonl_blobs:
                yield from _download_and_yield(blob)
        elif image_blobs:
            LOGGER.info("Found %d image files in %s. Running OCR...", len(image_blobs), path_str)
            yield from _process_images_and_yield(image_blobs, is_gcs=True, bucket=bucket)
        else:
            LOGGER.warning("No .jsonl or image files found in %s", path_str)
            return

    else:
        path = Path(path)
        if not path.exists():
            LOGGER.warning("Path not found: %s", path)
            return

        if path.is_dir():
            jsonl_files = list(path.glob("*.jsonl"))
            image_files = [p for p in path.glob("*.*") if p.suffix.lower() in image_extensions]

            if jsonl_files:
                LOGGER.info("Found %d .jsonl files in %s", len(jsonl_files), path)
                for file_path in jsonl_files:
                    with file_path.open("r", encoding="utf-8") as handle:
                        yield from _yield_from_handle(handle)
            elif image_files:
                LOGGER.info("Found %d image files in %s. Running OCR...", len(image_files), path)
                yield from _process_images_and_yield(image_files, is_gcs=False)
            else:
                LOGGER.warning("No .jsonl or image files found in %s", path)
        else:
            # Single file
            if path.suffix == ".jsonl":
                with path.open("r", encoding="utf-8") as handle:
                    yield from _yield_from_handle(handle)
            elif path.suffix.lower() in image_extensions:
                yield from _process_images_and_yield([path], is_gcs=False)
            else:
                LOGGER.warning("Unsupported file type: %s", path)


def _yield_from_handle(handle: Iterator[str]) -> Iterator[dict[str, Any]]:
    """Yields parsed JSON objects from a file handle."""
    for line_no, raw in enumerate(handle, start=1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            yield json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"failed to parse JSON on line {line_no}: {exc}") from exc


def _clone_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Deep clones a payload dictionary."""
    try:
        return json.loads(json.dumps(payload, default=str))
    except Exception:
        return dict(payload)


def _serialise_sql_result(result: SqlWriterResult | None) -> dict[str, Any] | None:
    """Serialises a SqlWriterResult to a dictionary."""
    if result is None:
        return None
    return {
        "case_id": result.case_id,
        "document_ids": list(result.document_ids),
        "entity_ids": list(result.entity_ids),
        "indicator_ids": list(result.indicator_ids),
    }


def _maybe_enqueue_retry(
    retry_store: Any,
    *,
    backend: str,
    attempted: bool,
    succeeded: bool,
    payload: dict[str, Any],
    retry_delay: int,
    max_retries: int,
    error: str | None = None,
    sql_result: SqlWriterResult | None = None,
) -> int:
    """Enqueues a retry if the operation failed and retries are enabled."""
    if not retry_store or not attempted or succeeded:
        return 0
    if max_retries <= 0:
        LOGGER.info(
            "Skipping %s retry for case_id=%s because max_retries=%s",
            backend,
            payload.get("case_id") or "unknown",
            max_retries,
        )
        return 0
    case_id = payload.get("case_id") or "unknown"
    try:
        cloned = _clone_payload(payload)
        queue_payload: dict[str, Any] = {"record": cloned}
        context: dict[str, Any] = {}
        serialised_sql = _serialise_sql_result(sql_result)
        if serialised_sql:
            context["sql_result"] = serialised_sql
        if error:
            context["error"] = error
        if context:
            queue_payload["context"] = context
        retry_store.enqueue(case_id=case_id, backend=backend, payload=queue_payload, delay_seconds=retry_delay)
        LOGGER.warning(
            "Scheduled %s retry for case_id=%s (max_attempts=%s) error=%s",
            backend,
            case_id,
            max_retries,
            error,
        )
        return 1
    except Exception:
        LOGGER.exception("Failed to enqueue %s retry for case_id=%s", backend, case_id)
        return 0


def main() -> int:
    """Entry point executed by the Cloud Run job container."""

    settings = get_settings()
    configure_job_logging(settings)

    dataset_path_str = str(settings.ingestion.dataset_path)
    if dataset_path_str.startswith("gs://"):
        dataset_path: str | Path = dataset_path_str
    else:
        dataset_path = Path(settings.ingestion.dataset_path)

    batch_limit = settings.ingestion.batch_limit
    rate_limit_delay = settings.ingestion.rate_limit_delay

    is_local = settings.env == "local"

    dry_run = settings.ingestion.dry_run
    reset_vector = settings.ingestion.reset_vector
    enable_vector = settings.ingestion.enable_vector_store
    enable_vertex = False if is_local else settings.ingestion.enable_vertex
    skip_classification = settings.ingestion.skip_classification

    dataset_name = (
        settings.ingestion.default_dataset
        if settings.ingestion.default_dataset != "unknown"
        else (dataset_path.stem if isinstance(dataset_path, Path) else "gcs_dataset")
    )

    LOGGER.info(
        (
            "Starting ingestion job: dataset=%s batch_limit=%s rate_limit_delay=%.2f dry_run=%s "
            "enable_vector=%s enable_vertex=%s reset_vector=%s"
        ),
        dataset_name,
        batch_limit or "unbounded",
        rate_limit_delay,
        dry_run,
        enable_vector,
        enable_vertex,
        reset_vector,
    )
    LOGGER.info("Resolved dataset path: %s", dataset_path)

    if isinstance(dataset_path, Path) and not dataset_path.exists():
        LOGGER.warning("Dataset path not found; nothing to ingest: %s", dataset_path)
        return 0

    structured_store = build_structured_store()
    vector_store = None
    if enable_vector:
        try:
            vector_store = build_vector_store(reset=reset_vector)
        except Exception:  # pragma: no cover - vector init is optional for jobs
            LOGGER.exception("Vector store initialisation failed; continuing without embeddings")
            enable_vector = False

    if not enable_vector:
        LOGGER.info("Vector ingestion disabled; skipping embedding writes")

    pipeline = IngestPipeline(
        structured_store=structured_store,
        vector_store=vector_store,
        enable_vector=enable_vector,
        enable_vertex=enable_vertex,
        default_dataset=dataset_name,
    )

    classifier = build_fraud_classifier()

    run_tracker = None
    run_id = None
    retry_store = None
    retry_delay = settings.ingestion.retry_delay_seconds
    max_retries = settings.ingestion.max_retries
    if not dry_run:
        try:
            run_tracker = build_ingestion_run_tracker()
            run_id = run_tracker.start_run(
                dataset=dataset_name,
                source_bundle=str(dataset_path),
                vector_enabled=enable_vector,
            )
        except Exception:
            LOGGER.exception("Failed to initialise ingestion run tracker; continuing without DB run row")
            run_tracker = None
            run_id = None

        try:
            retry_store = build_ingestion_retry_store()
        except Exception:
            LOGGER.exception("Failed to initialise ingestion retry store; retries disabled for this run")
            retry_store = None

    processed = 0
    failures = 0
    scheduled_retries = 0

    try:
        for record in _load_data(dataset_path):
            if batch_limit and processed >= batch_limit:
                break
            if rate_limit_delay > 0:
                time.sleep(rate_limit_delay)
            payload, diagnostics = prepare_ingest_payload(record, default_dataset=dataset_name)

            # Integrate Fraud Classifier
            if (
                not skip_classification
                and payload.get("text")
                and (not payload.get("fraud_type") or payload.get("fraud_type") == "unclassified")
            ):
                try:
                    classification_result = classifier.classify(payload["text"])

                    # Map primary intent to legacy field
                    if classification_result.intent:
                        # Sort by confidence desc
                        top_intent = sorted(classification_result.intent, key=lambda x: x.confidence, reverse=True)[0]
                        payload["fraud_type"] = top_intent.label
                        payload["fraud_confidence"] = top_intent.confidence
                        diagnostics["classification"] = top_intent.label
                        diagnostics["confidence"] = top_intent.confidence

                    # Store full result in metadata
                    if not payload.get("metadata"):
                        payload["metadata"] = {}
                    payload["metadata"]["classification_result"] = classification_result.model_dump()

                    LOGGER.info(
                        "Classified case %s as %s (%.2f)",
                        payload.get("case_id"),
                        payload["fraud_type"],
                        payload["fraud_confidence"],
                    )
                except Exception as e:
                    LOGGER.warning("Failed to classify case %s: %s", payload.get("case_id"), e)

            if dry_run:
                LOGGER.info(
                    "Dry run enabled; would ingest case_id=%s classification=%s confidence=%.2f text_source=%s",
                    payload.get("case_id") or "generated",
                    diagnostics["classification"],
                    diagnostics["confidence"],
                    diagnostics["text_source"],
                )
                processed += 1
                continue
            try:
                result = pipeline.ingest_classified_case(payload, ingestion_run_id=run_id)
                case_id = result.case_id
                payload["case_id"] = case_id
                if run_id:
                    payload.setdefault("ingestion_run_id", run_id)
                if run_tracker and run_id:
                    try:
                        run_tracker.record_case(
                            run_id,
                            result.sql_result,
                            vertex_writes=1 if result.vertex_written else 0,
                        )
                    except Exception:
                        LOGGER.exception("Failed to update ingestion run counters run_id=%s", run_id)

                if retry_store:
                    scheduled_retries += _maybe_enqueue_retry(
                        retry_store,
                        backend="vertex",
                        attempted=result.vertex_attempted,
                        succeeded=result.vertex_written,
                        payload=payload,
                        retry_delay=retry_delay,
                        max_retries=max_retries,
                        error=result.vertex_error,
                    )
                processed += 1
                LOGGER.info(
                    "Ingested record case_id=%s classification=%s confidence=%.2f text_source=%s",
                    case_id,
                    diagnostics["classification"],
                    diagnostics["confidence"],
                    diagnostics["text_source"],
                )
            except Exception:  # pragma: no cover - defensive logging around ingestion pipeline
                failures += 1
                LOGGER.exception("Failed to ingest record case_id=%s", payload.get("case_id"))
    except Exception as exc:  # pragma: no cover - unexpected reader failure
        LOGGER.exception("Ingestion batch aborted due to reader error")
        if run_tracker and run_id:
            try:
                run_tracker.complete_run(run_id, status="failed", last_error=str(exc))
            except Exception:
                LOGGER.exception("Failed to mark ingestion run as failed run_id=%s", run_id)
        return 1

    if run_tracker and run_id:
        run_status = "succeeded" if failures == 0 else "partial"
        last_error = None if failures == 0 else f"Encountered {failures} ingestion failure(s)"
        try:
            run_tracker.complete_run(
                run_id,
                status=run_status,
                last_error=last_error,
                retry_increment=scheduled_retries,
            )
        except Exception:
            LOGGER.exception("Failed to complete ingestion run metadata run_id=%s", run_id)

    LOGGER.info("Ingestion complete: processed=%s failures=%s", processed, failures)

    # F53: Emit operational metrics for dashboard consumption
    try:
        obs = get_observability(component="ingestion", settings=settings)
        obs.increment("ingestion.records.processed", value=float(processed), tags={"dataset": dataset_name})
        obs.increment("ingestion.records.failed", value=float(failures), tags={"dataset": dataset_name})
        obs.increment(
            "ingestion.records.retries_scheduled", value=float(scheduled_retries), tags={"dataset": dataset_name}
        )
        obs.emit_event(
            "ingestion.batch.complete",
            processed=processed,
            failures=failures,
            retries_scheduled=scheduled_retries,
            dataset=dataset_name,
            run_id=run_id,
        )
    except Exception:
        LOGGER.debug("Metrics emission failed; non-critical", exc_info=True)

    # F49: Check ingestion error rate and alert if above threshold
    try:
        alerting = get_alerting_service(settings=settings)
        alerting.check_ingestion_error_rate(
            processed=processed + failures,
            failures=failures,
            dataset=dataset_name,
            run_id=run_id,
        )
    except Exception:
        LOGGER.debug("Alerting check failed; non-critical", exc_info=True)

    return 0 if failures == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
