#!/usr/bin/env python3
"""Verify that a workload can read a vault secret via Workload Identity.

This script impersonates a target service account, fetches a Secret Manager
version, and prints a non-sensitive summary (version name and payload length).
Use it to validate that the app runtime service account can reach secrets in
the vault project via Workload Identity Federation (WIF).

Examples:
    python scripts/infra/verify_vault_secret_access.py \
        --project i4g-pii-vault-dev \
        --service-account sa-app@i4g-dev.iam.gserviceaccount.com \
        --secret-id tokenization-pepper

    python scripts/infra/verify_vault_secret_access.py \
        --project i4g-pii-vault-dev \
        --service-account sa-app@i4g-dev.iam.gserviceaccount.com \
        --secret-id tokenization-pepper \
        --print-secret
"""

from __future__ import annotations

import argparse
from typing import List

import google.auth
from google.api_core import exceptions
from google.auth import exceptions as auth_exceptions
from google.auth import impersonated_credentials
from google.auth.transport.requests import Request
from google.cloud import secretmanager

SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify WIF access to a vault Secret Manager secret")
    parser.add_argument("--project", required=True, help="Vault project that owns the secret (e.g., i4g-pii-vault-dev)")
    parser.add_argument("--secret-id", required=True, help="Secret ID to read (version defaults to 'latest')")
    parser.add_argument("--version", default="latest", help="Secret version to read (default: latest)")
    parser.add_argument(
        "--service-account",
        required=True,
        help="Service account email to impersonate (must have token creator binding on caller)",
    )
    parser.add_argument(
        "--print-secret",
        action="store_true",
        help="Print the secret payload (use only in secure terminals; otherwise length is shown)",
    )
    return parser.parse_args()


def build_impersonated_credentials(service_account: str, scopes: List[str]) -> impersonated_credentials.Credentials:
    source_credentials, _ = google.auth.default(scopes=scopes)
    return impersonated_credentials.Credentials(
        source_credentials=source_credentials,
        target_principal=service_account,
        target_scopes=scopes,
        lifetime=3600,
    )


def access_secret(
    client: secretmanager.SecretManagerServiceClient,
    project: str,
    secret_id: str,
    version: str,
) -> secretmanager.AccessSecretVersionResponse:
    name = client.secret_version_path(project, secret_id, version)
    return client.access_secret_version(request={"name": name})


def main() -> None:
    args = parse_args()
    try:
        impersonated = build_impersonated_credentials(args.service_account, SCOPES)
        impersonated.refresh(Request())
    except (exceptions.PermissionDenied, auth_exceptions.RefreshError) as exc:
        raise SystemExit(
            "Permission denied when creating impersonated credentials. Ensure the caller has token creator on the "
            f"target service account {args.service_account}."
        ) from exc

    client = secretmanager.SecretManagerServiceClient(credentials=impersonated)
    try:
        response = access_secret(client, args.project, args.secret_id, args.version)
    except exceptions.PermissionDenied as exc:
        raise SystemExit(
            "Permission denied when accessing the secret. Verify the impersonated service account has secretAccessor "
            f"on projects/{args.project}/secrets/{args.secret_id}."
        ) from exc
    except exceptions.NotFound as exc:
        raise SystemExit(
            f"Secret or version not found: projects/{args.project}/secrets/{args.secret_id}/versions/{args.version}"
        ) from exc

    payload = response.payload.data
    print(f"Read {len(payload)} bytes from {response.name} as {args.service_account}")
    if args.print_secret:
        print("\nSecret value (handle carefully):\n" + payload.decode("utf-8"))


if __name__ == "__main__":
    main()
