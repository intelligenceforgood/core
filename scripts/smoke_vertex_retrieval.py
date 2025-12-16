#!/usr/bin/env python3
"""Quick smoke test for the Vertex AI Search data store."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Sequence

from google.cloud import discoveryengine_v1beta as discoveryengine

REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project",
        required=True,
        help="Google Cloud project that owns the Discovery data store.",
    )
    parser.add_argument(
        "--location",
        default="global",
        help="Discovery location (default: global).",
    )
    parser.add_argument(
        "--data-store-id",
        required=True,
        help="Discovery data store identifier.",
    )
    parser.add_argument(
        "--jsonl",
        default="data/retrieval_poc/cases.jsonl",
        help="JSON Lines file to validate via dry-run ingestion.",
    )
    parser.add_argument(
        "--serving-config-id",
        default="default_search",
        help="Serving config identifier (default: default_search).",
    )
    parser.add_argument(
        "--query",
        default="wallet address verification",
        help="Query string to use for the search portion of the smoke test.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=5,
        help="Maximum number of results to fetch when validating search (default: 5).",
    )
    return parser.parse_args(argv)


def run_dry_run(args: argparse.Namespace) -> None:
    from i4g.cli import ingest

    payload = SimpleNamespace(
        project=args.project,
        location=args.location,
        data_store_id=args.data_store_id,
        jsonl=Path(args.jsonl),
        dataset=None,
        batch_size=50,
        reconcile_mode="INCREMENTAL",
        branch_id="default_branch",
        dry_run=True,
        verbose=False,
    )
    exit_code = ingest.ingest_vertex_search(payload)
    if exit_code != 0:
        raise SystemExit("Dry-run ingestion failed; see logs above.")


def run_query(args: argparse.Namespace) -> None:
    client = discoveryengine.SearchServiceClient()
    serving_config = client.serving_config_path(
        project=args.project,
        location=args.location,
        data_store=args.data_store_id,
        serving_config=args.serving_config_id,
    )
    request = discoveryengine.SearchRequest(
        serving_config=serving_config,
        query=args.query,
        page_size=args.page_size,
    )
    results = list(client.search(request=request))
    if not results:
        raise SystemExit("Search returned no results; ingestion may be empty.")
    top = results[0].document
    summary = top.struct_data.get("summary") if top.struct_data else None
    print(
        "Smoke test success: %d results (top id=%s, summary=%s)"
        % (len(results), top.id, summary or top.title or "<unknown>")
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_dry_run(args)
    run_query(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
