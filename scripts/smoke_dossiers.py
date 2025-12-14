#!/usr/bin/env python3
"""Smoke test for dossier listings and verification endpoints.

This script fetches dossier queue entries, selects a plan, and calls
`/reports/dossiers/{plan_id}/verify` to ensure manifests and signatures are
readable. It also checks that referenced local artifact paths exist.

Run from repo root:
    conda run -n i4g python scripts/smoke_dossiers.py --api-url http://localhost:8000 --token dev-token
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib import error, parse, request

DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_STATUS = "completed"
DEFAULT_LIMIT = 10


class SmokeError(RuntimeError):
    """Raised when a smoke step fails."""


@dataclass(frozen=True)
class VerificationResult:
    plan_id: str
    all_verified: bool
    missing_count: int
    mismatch_count: int
    manifest_path: Path | None
    signature_path: Path | None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="FastAPI base URL (default: localhost:8000)")
    parser.add_argument("--token", help="API key for authenticated endpoints (X-API-KEY)")
    parser.add_argument("--status", default=DEFAULT_STATUS, help="Queue status filter (default: completed)")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Max dossiers to inspect (default: 10)")
    parser.add_argument("--plan-id", help="Specific dossier plan_id to verify (optional)")
    return parser.parse_args(argv)


def _http_request(
    method: str, url: str, *, headers: Mapping[str, str] | None = None, data: bytes | None = None
) -> bytes:
    req = request.Request(url=url, data=data, headers=dict(headers or {}), method=method)
    try:
        with request.urlopen(req, timeout=20) as resp:
            if resp.status >= 400:
                raise SmokeError(f"Request failed ({resp.status}): {url}")
            return resp.read()
    except error.HTTPError as exc:  # pragma: no cover - network boundary
        raise SmokeError(f"HTTP error {exc.code} for {url}: {exc.read().decode('utf-8', errors='ignore')}") from exc
    except error.URLError as exc:  # pragma: no cover - network boundary
        raise SmokeError(f"Network error for {url}: {exc.reason}") from exc


def _headers(token: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-API-KEY"] = token
    return headers


def fetch_dossiers(api_url: str, token: str | None, status: str, limit: int) -> list[dict[str, Any]]:
    params = parse.urlencode({"status": status, "limit": str(limit), "include_manifest": "false"})
    url = f"{api_url.rstrip('/')}/reports/dossiers?{params}"
    body = _http_request("GET", url, headers=_headers(token))
    payload = json.loads(body)
    items = payload.get("items")
    if not isinstance(items, list):
        raise SmokeError(f"Unexpected dossier list payload: {payload}")
    if not items:
        raise SmokeError("No dossiers returned; ensure queue has completed entries")
    return items


def select_plan(items: Sequence[Mapping[str, Any]], plan_id: str | None) -> Mapping[str, Any]:
    if plan_id:
        for item in items:
            if str(item.get("plan_id")) == plan_id:
                return item
        raise SmokeError(f"Requested plan_id {plan_id} not found in list response")
    return items[0]


def verify_plan(api_url: str, token: str | None, plan_id: str) -> dict[str, Any]:
    url = f"{api_url.rstrip('/')}/reports/dossiers/{plan_id}/verify"
    body = _http_request("POST", url, headers=_headers(token))
    payload = json.loads(body)
    if payload.get("plan_id") != plan_id:
        raise SmokeError(f"Verification response plan_id mismatch: {payload}")
    return payload


def fetch_signature_manifest(api_url: str, token: str | None, plan_id: str) -> Mapping[str, Any]:
    url = f"{api_url.rstrip('/')}/reports/dossiers/{plan_id}/signature_manifest"
    body = _http_request("GET", url, headers=_headers(token))
    payload = json.loads(body)
    if payload.get("algorithm") is None:
        raise SmokeError(f"Missing algorithm in signature manifest for {plan_id}")
    return payload


def _hash_file(path: Path, algorithm: str) -> str:
    import hashlib

    try:
        hasher = getattr(hashlib, algorithm)
    except AttributeError as exc:  # pragma: no cover - invalid algorithm
        raise SmokeError(f"Unsupported hash algorithm: {algorithm}") from exc
    h = hasher()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_artifact_path(raw_path: str | Path, base_dir: Path) -> Path:
    """Return an absolute path for ``raw_path`` without double-prefixing ``base_dir``.

    Some manifests already embed paths rooted at ``data/reports/dossiers``; in those
    cases the path exists relative to the working directory and should not be
    re-joined to ``base_dir``.
    """

    path = Path(raw_path)
    if path.is_absolute():
        return path
    if path.exists():
        return path.resolve()
    return (base_dir / path).resolve()


def verify_against_manifest(signature_manifest: Mapping[str, Any], base_dir: Path) -> None:
    algorithm = signature_manifest.get("algorithm", "sha256")
    artifacts = signature_manifest.get("artifacts") or []
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            continue
        rel_path = artifact.get("path")
        expected_hash = artifact.get("hash")
        if not rel_path or not expected_hash:
            continue
        path = _resolve_artifact_path(str(rel_path), base_dir)
        if not path.exists():
            raise SmokeError(f"Artifact missing for hash verification: {path}")
        actual_hash = _hash_file(path, algorithm)
        if actual_hash != expected_hash:
            raise SmokeError(f"Hash mismatch for {path}: expected {expected_hash}, got {actual_hash}")


def validate_downloads(item: Mapping[str, Any], verification: Mapping[str, Any]) -> VerificationResult:
    downloads = item.get("downloads") or {}
    local = downloads.get("local") or {}
    manifest_path = Path(local["manifest"]) if local.get("manifest") else None
    signature_path = Path(local["signature_manifest"]) if local.get("signature_manifest") else None

    missing_paths: list[str] = []
    for label, path_obj in ("manifest", manifest_path), ("signature", signature_path):
        if path_obj and not path_obj.exists():
            missing_paths.append(f"{label}:{path_obj}")
    if missing_paths:
        raise SmokeError(f"Missing local artifacts: {', '.join(missing_paths)}")

    return VerificationResult(
        plan_id=str(item.get("plan_id")),
        all_verified=bool(verification.get("all_verified")),
        missing_count=int(verification.get("missing_count", 0)),
        mismatch_count=int(verification.get("mismatch_count", 0)),
        manifest_path=manifest_path,
        signature_path=signature_path,
    )


def download_via_api(api_url: str, token: str | None, downloads: Mapping[str, Any]) -> None:
    api_urls = downloads.get("api") or {}
    for key in ("manifest", "signature"):
        url_path = api_urls.get(key)
        if not url_path:
            continue
        full_url = f"{api_url.rstrip('/')}{url_path}"
        _http_request("GET", full_url, headers=_headers(token))


def run_smoke(args: argparse.Namespace) -> VerificationResult:
    dossiers = fetch_dossiers(args.api_url, args.token, args.status, args.limit)
    selected = select_plan(dossiers, args.plan_id)
    verification = verify_plan(args.api_url, args.token, str(selected.get("plan_id")))
    download_via_api(args.api_url, args.token, selected.get("downloads") or {})
    signature_manifest = fetch_signature_manifest(args.api_url, args.token, str(selected.get("plan_id")))
    manifest_path = selected.get("manifest_path") or (selected.get("downloads", {}).get("local", {}) or {}).get(
        "manifest"
    )
    base_dir = Path(manifest_path).parent if manifest_path else Path.cwd()
    verify_against_manifest(signature_manifest, base_dir)
    result = validate_downloads(selected, verification)
    if not result.all_verified:
        raise SmokeError(
            "Verification reported mismatches or missing artifacts: "
            f"missing={result.missing_count}, mismatch={result.mismatch_count}"
        )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run_smoke(args)
    except SmokeError as exc:  # pragma: no cover - CLI boundary
        print(f"SMOKE FAILED: {exc}", file=sys.stderr)
        return 1
    print(
        "SMOKE OK: plan=%s verified, manifest=%s, signature=%s"
        % (result.plan_id, result.manifest_path or "<none>", result.signature_path or "<none>")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
