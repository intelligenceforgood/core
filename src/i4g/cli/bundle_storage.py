from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

try:
    from google.cloud import storage
except ImportError as exc:  # pragma: no cover - optional dependency
    storage = None
    _import_error = exc
else:
    _import_error = None

SECONDS_PER_DAY = 24 * 60 * 60


@dataclass
class ProvisionResult:
    bucket: str
    project: str
    location: str
    storage_class: str
    versioning_enabled: bool
    uniform_access: bool
    retention_seconds: Optional[int]
    delete_noncurrent_after_days: Optional[int]
    iam_members: List[str]


def _require_storage() -> None:
    if storage is None:
        raise RuntimeError("google-cloud-storage is required for this command") from _import_error


def provision_bucket(
    bucket_name: str,
    project: str,
    location: str,
    storage_class: str,
    retention_days: Optional[int],
    delete_noncurrent_days: Optional[int],
    iam_members: List[str],
) -> ProvisionResult:
    """Create or update a GCS bucket with versioning, lifecycle, and IAM bindings."""

    _require_storage()
    client = storage.Client(project=project)
    bucket = client.bucket(bucket_name)

    if bucket.exists(client=client):
        bucket = client.get_bucket(bucket_name)
    else:
        bucket.storage_class = storage_class
        bucket.location = location
        bucket.versioning_enabled = True
        bucket.iam_configuration.uniform_bucket_level_access_enabled = True
        if retention_days:
            bucket.retention_period = retention_days * SECONDS_PER_DAY
        bucket = client.create_bucket(bucket)

    mutated = False
    if not bucket.versioning_enabled:
        bucket.versioning_enabled = True
        mutated = True
    if not bucket.iam_configuration.uniform_bucket_level_access_enabled:
        bucket.iam_configuration.uniform_bucket_level_access_enabled = True
        mutated = True
    if retention_days:
        desired_retention = retention_days * SECONDS_PER_DAY
        if bucket.retention_period != desired_retention:
            bucket.retention_period = desired_retention
            mutated = True

    # Replace lifecycle with a single delete rule for noncurrent versions when requested.
    if delete_noncurrent_days:
        bucket.clear_lifecycle_rules()
        bucket.add_lifecycle_delete_rule(age=delete_noncurrent_days, is_live=False)
        mutated = True

    if mutated:
        bucket.patch()

    if iam_members:
        policy = bucket.get_iam_policy(requested_policy_version=3)
        target_role = "roles/storage.objectAdmin"
        binding = next((item for item in policy.bindings if item.get("role") == target_role), None)
        if binding is None:
            binding = {"role": target_role, "members": []}
            policy.bindings.append(binding)

        existing_members = set(binding.get("members", []))
        for member in iam_members:
            if member not in existing_members:
                binding.setdefault("members", []).append(member)
                existing_members.add(member)

        bucket.set_iam_policy(policy)

    return ProvisionResult(
        bucket=bucket.name,
        project=bucket.project or project,
        location=bucket.location,
        storage_class=bucket.storage_class,
        versioning_enabled=bucket.versioning_enabled,
        uniform_access=bucket.iam_configuration.uniform_bucket_level_access_enabled,
        retention_seconds=bucket.retention_period,
        delete_noncurrent_after_days=delete_noncurrent_days,
        iam_members=iam_members,
    )


__all__ = ["provision_bucket", "ProvisionResult"]
