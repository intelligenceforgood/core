"""Constants and dataclasses for the dev bootstrap workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
DATA_DIR = REPO_ROOT / "data"
BUNDLES_DIR = DATA_DIR / "bundles"

DEFAULT_WIF_SA = "sa-infra@i4g-dev.iam.gserviceaccount.com"
DEFAULT_RUNTIME_SA = "sa-app@i4g-dev.iam.gserviceaccount.com"
IAP_CLIENT_ID_FALLBACK = "544936845045-a87u04lgc7go7asc4nhed36ka50iqh0h.apps.googleusercontent.com"
DEFAULT_PROJECT = "i4g-dev"
DEFAULT_REGION = "us-central1"
DEFAULT_SMOKE_API_URL = "https://fastapi-gateway-y5jge5w2cq-uc.a.run.app"
DEFAULT_REPORT_DIR = REPO_ROOT / "data" / "reports" / "bootstrap_dev"
DEFAULT_JOBS = {
    "ingest": "ingest-bootstrap",
    "vertex": "",
    "sql": "",
    "bigquery": "",
    "gcs_assets": "",
    "reports": "generate-reports",
    "saved_searches": "",
    "seed_reviews": "ingest-bootstrap",
}


@dataclass
class JobSpec:
    label: str
    job_name: str
    args: list[str]
    env: dict[str, str] | None = None


@dataclass
class JobResult:
    label: str
    job_name: str
    command: str
    status: str
    stdout: str
    stderr: str
    error: str | None
