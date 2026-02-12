"""Ingestion utilities surfaced through the Typer CLI."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from collections.abc import Iterable, Iterator

import google.api_core.exceptions
from google.cloud import discoveryengine_v1beta as discoveryengine
from google.protobuf import json_format

from i4g.cli.admin import helpers as saved_searches
from i4g.cli.utils import console, iter_jsonl
from i4g.services.ingest_payloads import prepare_ingest_payload
from i4g.services.vertex_documents import build_vertex_document
from i4g.settings import get_settings
from i4g.store.ingest import IngestPipeline


def ingest_bundles(*, input_path: str | Path, limit: int | None = None) -> None:
    """Bulk ingest JSONL bundles into structured + vector stores."""

    bundle_path = Path(input_path)
    if not bundle_path.exists():
        console.print(f"[red]\u274c Bundle file not found:[/red] {bundle_path}")
        raise SystemExit(1)

    pipeline = IngestPipeline()
    count = 0
    for record in iter_jsonl(bundle_path):
        if limit and count >= limit:
            break
        mapped = {
            "case_id": record.get("id") or record.get("case_id"),
            "text": record.get("text", ""),
            "fraud_type": record.get("scam_type") or record.get("fraud_type", "unknown"),
            "fraud_confidence": float(record.get("fraud_confidence", 0.0) or 0.0),
            "entities": record.get("entities", {}),
            "metadata": record.get("metadata", {}),
        }
        pipeline.ingest_classified_case(mapped)
        count += 1
        if count % 100 == 0:
            console.print(f"[cyan]Ingested {count} records...[/cyan]")

    console.print(f"[green]✅ Ingest complete. Total records ingested: {count}[/green]")


def _enrich_record(record: dict[str, Any], default_dataset: str | None = None) -> dict[str, Any]:
    payload, _ = prepare_ingest_payload(record, default_dataset=default_dataset)
    enriched = dict(record)
    for key in (
        "case_id",
        "dataset",
        "categories",
        "indicator_ids",
        "fraud_type",
        "fraud_confidence",
        "tags",
        "summary",
        "channel",
        "timestamp",
        "structured_fields",
        "metadata",
    ):
        value = payload.get(key)
        if value is not None:
            enriched[key] = value
    return enriched


def _chunked(iterable: Iterable[discoveryengine.Document], size: int) -> Iterator[list[discoveryengine.Document]]:
    chunk: list[discoveryengine.Document] = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def ingest_vertex_search(
    *,
    verbose: bool = False,
    jsonl: str | Path,
    dataset: str | None = None,
    dry_run: bool = False,
    project: str | None = None,
    location: str = "global",
    data_store_id: str,
    branch_id: str = "default_branch",
    reconcile_mode: str = "INCREMENTAL",
    batch_size: int = 100,
) -> int:
    """Ingest JSONL scam cases into a Vertex AI Search data store."""

    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")
    settings = get_settings()

    records = list(iter_jsonl(Path(jsonl)))
    if not records:
        logging.warning("No records found; nothing to ingest.")
        return 0

    enriched_records = [_enrich_record(record, dataset) for record in records]
    documents = [build_vertex_document(record, default_dataset=dataset) for record in enriched_records]

    if dry_run:
        preview = documents[0]
        logging.info("Dry run: first document payload (id=%s)", preview.id)
        logging.info(json.dumps(json_format.MessageToDict(preview._pb), indent=2))
        logging.info("Total documents parsed: %s", len(documents))
        return 0

    resolved_project = project or settings.vector.vertex_ai_project
    if not resolved_project:
        console.print("[red]❌ Provide --project or set I4G_VECTOR__VERTEX_AI__PROJECT.[/red]")
        return 2

    client = discoveryengine.DocumentServiceClient()
    parent = client.branch_path(
        project=resolved_project,
        location=location,
        data_store=data_store_id,
        branch=branch_id,
    )

    reconcile_lookup = {
        "UNSPECIFIED": discoveryengine.ImportDocumentsRequest.ReconciliationMode.RECONCILIATION_MODE_UNSPECIFIED,
        "INCREMENTAL": discoveryengine.ImportDocumentsRequest.ReconciliationMode.INCREMENTAL,
        "FULL": discoveryengine.ImportDocumentsRequest.ReconciliationMode.FULL,
    }
    resolved_reconcile_mode = reconcile_lookup[reconcile_mode]

    total_success = 0
    total_fail = 0

    for batch_no, chunk in enumerate(_chunked(documents, batch_size), start=1):
        logging.info("Submitting batch %d with %d documents", batch_no, len(chunk))
        request = discoveryengine.ImportDocumentsRequest(
            parent=parent,
            inline_source=discoveryengine.ImportDocumentsRequest.InlineSource(documents=chunk),
            reconciliation_mode=resolved_reconcile_mode,
        )

        try:
            operation = client.import_documents(request=request)
            response = operation.result()
        except google.api_core.exceptions.GoogleAPIError as exc:
            logging.error("Batch %d failed: %s", batch_no, exc)
            total_fail += len(chunk)
            continue

        error_samples = list(getattr(response, "error_samples", []))
        batch_errors = len(error_samples)
        batch_success = max(len(chunk) - batch_errors, 0)
        total_success += batch_success
        total_fail += batch_errors

        if error_samples:
            logging.warning("Batch %d reported %d sample errors", batch_no, len(error_samples))
            for sample in error_samples[:3]:
                logging.warning(json_format.MessageToJson(sample))

        logging.info(
            "Batch %d completed: success=%d failure=%d",
            batch_no,
            batch_success,
            batch_errors,
        )

    logging.info(
        "Ingestion complete: %d succeeded, %d failed, total input %d",
        total_success,
        total_fail,
        len(documents),
    )

    return 0 if total_fail == 0 else 2


def tag_saved_searches(
    *,
    input_path: str | Path,
    output_path: str | Path | None = None,
    tag: str | None = None,
    schema_version: str | None = None,
    dedupe: bool = True,
) -> None:
    """Annotate saved-search exports with migration metadata."""

    in_path = Path(input_path)
    out_path = Path(output_path) if output_path else None
    destination, count = saved_searches.annotate_file(
        in_path,
        output_path=out_path,
        tag=tag or "",
        schema_version=schema_version or "",
        dedupe=dedupe,
    )
    console.print(f"[green]✅ Annotated {count} saved search(es); wrote {destination}[/green]")


__all__ = [
    "ingest_bundles",
    "ingest_vertex_search",
    "tag_saved_searches",
]
