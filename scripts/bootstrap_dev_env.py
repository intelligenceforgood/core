#!/usr/bin/env python3
"""Bootstrap the dev environment via Cloud Run jobs with guardrails.

This orchestrator executes the Cloud Run jobs that refresh structured data,
Vertex indexes, and supporting assets. It is intentionally conservative: it
refuses to target prod projects unless explicitly forced and defaults to the
`sa-infra@i4g-dev.iam.gserviceaccount.com` WIF service account for execution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from i4g.settings import get_settings  # noqa: E402

DEFAULT_WIF_SA = "sa-infra@i4g-dev.iam.gserviceaccount.com"
DEFAULT_PROJECT = "i4g-dev"
DEFAULT_REGION = "us-central1"
DEFAULT_REPORT_DIR = REPO_ROOT / "data" / "reports" / "dev_bootstrap"
DEFAULT_JOBS = {
    "firestore": "bootstrap-firestore",
    "vertex": "bootstrap-vertex",
    "sql": "bootstrap-sql",
    "bigquery": "bootstrap-bigquery",
    "gcs_assets": "bootstrap-gcs-assets",
    "reports": "bootstrap-reports",
    "saved_searches": "bootstrap-saved-searches",
}


@dataclass
class JobSpec:
    label: str
    job_name: str
    args: list[str]


@dataclass
class JobResult:
    label: str
    job_name: str
    command: str
    status: str
    stdout: str
    stderr: str
    error: str | None


@dataclass
class SmokeResult:
    status: str
    message: str


@dataclass
class DossierSmokeResult:
    status: str
    message: str
    plan_id: Optional[str]
    manifest_path: Optional[str]
    signature_path: Optional[str]


@dataclass
class SearchSmokeResult:
    status: str
    message: str


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap the dev environment via Cloud Run jobs")
    parser.add_argument("--project", default=DEFAULT_PROJECT, help="Target GCP project (default: i4g-dev).")
    parser.add_argument("--region", default=DEFAULT_REGION, help="Cloud Run region (default: us-central1).")
    parser.add_argument("--bundle-uri", dest="bundle_uri", help="Bundle URI passed to all jobs, if supported.")
    parser.add_argument("--dataset", help="Dataset identifier injected into job args, if supported.")
    parser.add_argument(
        "--wif-service-account",
        default=DEFAULT_WIF_SA,
        help="Service account to impersonate via WIF (default: sa-infra@i4g-dev).",
    )
    parser.add_argument("--firestore-job", default=DEFAULT_JOBS["firestore"], help="Firestore refresh job name.")
    parser.add_argument("--vertex-job", default=DEFAULT_JOBS["vertex"], help="Vertex import job name.")
    parser.add_argument("--sql-job", default=DEFAULT_JOBS["sql"], help="SQL/Firestore sync job name.")
    parser.add_argument("--bigquery-job", default=DEFAULT_JOBS["bigquery"], help="BigQuery refresh job name.")
    parser.add_argument("--gcs-assets-job", default=DEFAULT_JOBS["gcs_assets"], help="GCS asset sync job name.")
    parser.add_argument("--reports-job", default=DEFAULT_JOBS["reports"], help="Reports/dossiers job name.")
    parser.add_argument(
        "--saved-searches-job",
        default=DEFAULT_JOBS["saved_searches"],
        help="Saved searches/tag presets job name.",
    )
    parser.add_argument("--skip-firestore", action="store_true", help="Skip Firestore refresh job.")
    parser.add_argument("--skip-vertex", action="store_true", help="Skip Vertex import job.")
    parser.add_argument("--skip-sql", action="store_true", help="Skip SQL/Firestore sync job.")
    parser.add_argument("--skip-bigquery", action="store_true", help="Skip BigQuery refresh job.")
    parser.add_argument("--skip-gcs-assets", action="store_true", help="Skip GCS asset sync job.")
    parser.add_argument("--skip-reports", action="store_true", help="Skip reports/dossiers job.")
    parser.add_argument("--skip-saved-searches", action="store_true", help="Skip saved searches job.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned commands without executing them.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Skip job execution and only run verification smokes.",
    )
    parser.add_argument(
        "--run-smoke",
        action="store_true",
        help="Run Cloud Run intake smoke after job execution (or standalone with --verify-only).",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
        #!/usr/bin/env python3
        """Shim for legacy callers; routes to i4g.cli.bootstrap.dev.main."""

        from __future__ import annotations

        import sys
        from pathlib import Path
        from typing import Sequence

        REPO_ROOT = Path(__file__).resolve().parents[1]
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))

        from i4g.cli.bootstrap import dev


        def main(argv: Sequence[str] | None = None) -> int:
            return dev.main(argv)


        if __name__ == "__main__":
            sys.exit(main())
        help="API token for smoke requests.",
