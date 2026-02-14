"""Evidence storage helpers for intake uploads."""

from __future__ import annotations

import hashlib
import io
import os
from dataclasses import dataclass
from pathlib import Path

from i4g.settings import get_settings

try:  # pragma: no cover - optional dependency when running in local mode
    from google.cloud import storage
except ImportError:  # pragma: no cover - local/dev environments may not install GCS client
    storage = None


@dataclass
class StoredAttachment:
    """Metadata describing a persisted intake attachment."""

    attachment_id: str
    file_name: str
    content_type: str | None
    size_bytes: int
    checksum_sha256: str
    storage_uri: str
    backend: str


class EvidenceStorage:
    """Persist evidence artifacts to the configured storage backend."""

    def __init__(self, *, local_dir: Path | None = None) -> None:
        self._settings = get_settings()
        storage_settings = self._settings.storage

        if storage_settings.evidence_bucket:
            if storage is None:
                raise RuntimeError("google-cloud-storage required for GCS evidence backend")
            self._backend = "gcs"
            self._bucket_name = storage_settings.evidence_bucket
            self._client = storage.Client(project=self._settings.secrets.project)
            self._bucket = self._client.bucket(self._bucket_name)
            self._local_dir = None
        else:
            self._backend = "local"
            base_dir = local_dir or Path(storage_settings.evidence_local_dir)
            try:
                base_dir.mkdir(parents=True, exist_ok=True)
            except PermissionError:
                fallback_dir = self._settings.runtime.fallback_dir
                fallback_dir.mkdir(parents=True, exist_ok=True)
                base_dir = fallback_dir
            self._local_dir = base_dir
            self._bucket_name = None
            self._client = None
            self._bucket = None

    def save(self, intake_id: str, file_name: str, data: bytes, content_type: str | None) -> StoredAttachment:
        """Persist a single attachment and return metadata."""

        if not file_name:
            file_name = "uploaded_evidence"

        clean_name = os.path.basename(file_name)
        checksum = hashlib.sha256(data).hexdigest()
        size_bytes = len(data)

        if self._backend == "local":
            assert self._local_dir is not None  # mypy safeguard
            intake_dir = self._local_dir / intake_id
            intake_dir.mkdir(parents=True, exist_ok=True)
            path = intake_dir / clean_name
            with path.open("wb") as handle:
                handle.write(data)
            storage_uri = str(path)
        else:
            assert self._bucket is not None  # mypy safeguard
            blob_path = f"intake/{intake_id}/{clean_name}"
            blob = self._bucket.blob(blob_path)
            stream = io.BytesIO(data)
            blob.upload_from_file(stream, rewind=True, content_type=content_type)
            storage_uri = f"gs://{self._bucket_name}/{blob_path}"

        attachment_id = hashlib.sha256(f"{intake_id}:{clean_name}:{checksum}".encode()).hexdigest()
        return StoredAttachment(
            attachment_id=attachment_id,
            file_name=clean_name,
            content_type=content_type,
            size_bytes=size_bytes,
            checksum_sha256=checksum,
            storage_uri=storage_uri,
            backend=self._backend,
        )

    def delete(self, storage_uri: str) -> bool:
        """Delete an evidence artifact by its storage URI.

        Args:
            storage_uri: The URI returned by :meth:`save` (local path or ``gs://`` URI).

        Returns:
            ``True`` if the artifact was deleted, ``False`` if not found.
        """
        if storage_uri.startswith("gs://"):
            return self._delete_gcs(storage_uri)
        return self._delete_local(storage_uri)

    def delete_by_prefix(self, prefix: str) -> int:
        """Delete all evidence artifacts under a storage prefix.

        For local storage, ``prefix`` is a directory path. For GCS, it is a
        blob prefix (e.g. ``intake/{intake_id}``).

        Returns:
            Number of artifacts deleted.
        """
        if self._backend == "gcs":
            return self._delete_gcs_prefix(prefix)
        return self._delete_local_dir(prefix)

    # -- private helpers --

    def _delete_local(self, path_str: str) -> bool:
        path = Path(path_str)
        if path.is_file():
            path.unlink()
            return True
        return False

    def _delete_local_dir(self, dir_path: str) -> int:
        import shutil

        path = Path(dir_path)
        if not path.is_dir():
            return 0
        count = sum(1 for _ in path.rglob("*") if _.is_file())
        shutil.rmtree(path)
        return count

    def _delete_gcs(self, uri: str) -> bool:
        if self._bucket is None:
            return False
        # parse gs://bucket/path → path
        blob_path = uri.split(f"gs://{self._bucket_name}/", 1)[-1]
        blob = self._bucket.blob(blob_path)
        if blob.exists():
            blob.delete()
            return True
        return False

    def _delete_gcs_prefix(self, prefix: str) -> int:
        if self._bucket is None:
            return 0
        blobs = list(self._bucket.list_blobs(prefix=prefix))
        for blob in blobs:
            blob.delete()
        return len(blobs)
