"""Upload helpers for dossier artifacts."""

from __future__ import annotations

import hashlib
import logging
import mimetypes
from pathlib import Path
from typing import Any, Mapping, Sequence

from i4g.reports.bundle_builder import DossierPlan
from i4g.settings import get_settings

LOGGER = logging.getLogger(__name__)


class _FallbackMediaUpload:
    """Lightweight stand-in for MediaFileUpload used in tests."""

    def __init__(self, filename: str, mimetype: str) -> None:
        self.filename = filename
        self.mimetype = mimetype


def _safe_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class DossierUploader:
    """Uploads dossier artifacts to Google Drive and returns hash metadata."""

    _DRIVE_SCOPES = (
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/cloud-platform",
    )

    def __init__(
        self,
        *,
        drive_parent_id: str | None = None,
        drive_service: Any | None = None,
        hash_algorithm: str | None = None,
    ) -> None:
        settings = get_settings()
        self._default_parent_id = drive_parent_id or settings.report.drive_parent_id
        self._hash_algorithm = hash_algorithm or settings.report.hash_algorithm
        self._drive_service = drive_service
        if self._drive_service is None and self._default_parent_id:
            self._drive_service = self._build_drive_client()

    def upload(
        self,
        artifacts: Sequence[tuple[str, Path]],
        plan: DossierPlan,
    ) -> tuple[list[Mapping[str, object]], list[str]]:
        """Upload artifacts to Drive and return upload rows + warnings."""

        parent_id = plan.shared_drive_parent_id or self._default_parent_id
        if not artifacts or not parent_id:
            return [], []

        if self._drive_service is None:
            self._drive_service = self._build_drive_client()
        if self._drive_service is None:
            warning = f"Drive upload skipped for plan {plan.plan_id}: Drive client unavailable"
            LOGGER.warning(warning)
            return [], [warning]

        rows: list[Mapping[str, object]] = []
        warnings: list[str] = []
        for label, path in artifacts:
            if not path or not Path(path).exists():
                warnings.append(f"Artifact {label} missing for upload")
                continue
            try:
                upload_info = self._upload_to_drive(path=Path(path), parent_id=parent_id)
            except Exception as exc:  # pragma: no cover - defensive logging
                warnings.append(f"Drive upload failed for {label}: {exc}")
                LOGGER.warning("Drive upload failed for %s: %s", label, exc)
                continue
            remote_ref = upload_info.get("link")
            if not remote_ref:
                warnings.append(f"Drive upload returned no link for {label}")
                continue
            local_hash = self._hash_file(Path(path), algorithm=self._hash_algorithm)
            remote_md5 = upload_info.get("md5")
            local_md5 = self._hash_file(Path(path), algorithm="md5")
            if remote_md5 and remote_md5 != local_md5:
                warnings.append(f"Drive MD5 mismatch for {label}: remote={remote_md5} local={local_md5}")
            rows.append(
                {
                    "label": label,
                    "remote_ref": remote_ref,
                    "hash": local_hash,
                    "algorithm": self._hash_algorithm,
                    "size_bytes": upload_info.get("size_bytes"),
                }
            )
        return rows, warnings

    def fetch_acl(self, folder_id: str | None = None) -> tuple[dict[str, object] | None, list[str]]:
        """Return Drive folder metadata and permissions for ACL previews."""

        target_id = folder_id or self._default_parent_id
        warnings: list[str] = []
        if not target_id:
            return None, ["Drive folder id not provided"]

        if self._drive_service is None:
            self._drive_service = self._build_drive_client()
        if self._drive_service is None:
            return None, ["Drive client unavailable"]

        folder_meta: dict[str, object] | None = None
        try:
            folder_meta = (
                self._drive_service.files()  # type: ignore[union-attr]
                .get(
                    fileId=target_id,
                    fields="id,name,webViewLink,driveId,parents",
                    supportsAllDrives=True,
                )
                .execute()
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            warnings.append(f"Unable to load folder metadata: {exc}")

        permissions: list[dict[str, object]] = []
        try:
            perm_response = (
                self._drive_service.permissions()  # type: ignore[union-attr]
                .list(
                    fileId=target_id,
                    supportsAllDrives=True,
                    fields="permissions(id,type,role,displayName,domain,emailAddress)",
                )
                .execute()
            )
            for perm in perm_response.get("permissions", []):
                principal = perm.get("displayName") or perm.get("domain") or perm.get("emailAddress")
                permissions.append(
                    {
                        "id": perm.get("id"),
                        "type": perm.get("type"),
                        "role": perm.get("role"),
                        "principal": principal,
                    }
                )
        except Exception as exc:  # pragma: no cover - defensive guard
            warnings.append(f"Unable to load folder permissions: {exc}")

        if folder_meta is None and not permissions:
            return None, warnings or ["Drive ACL unavailable"]

        summary = {
            "folder_id": (folder_meta or {}).get("id") or target_id,
            "name": (folder_meta or {}).get("name"),
            "link": (folder_meta or {}).get("webViewLink"),
            "drive_id": (folder_meta or {}).get("driveId"),
            "permissions": permissions,
        }
        return summary, warnings

    def _upload_to_drive(self, *, path: Path, parent_id: str) -> dict[str, object]:
        if not self._drive_service:
            raise RuntimeError("Drive service not initialized")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        media = self._build_media_upload(path=path, content_type=content_type)
        request = self._drive_service.files().create(  # type: ignore[union-attr]
            body={"name": path.name, "parents": [parent_id]},
            media_body=media,
            fields="id,webViewLink,webContentLink,md5Checksum,size",
            supportsAllDrives=True,
        )
        file_info = request.execute()
        link = file_info.get("webViewLink") or file_info.get("webContentLink")
        if not link and file_info.get("id"):
            link = f"https://drive.google.com/file/d/{file_info['id']}/view"
        return {
            "link": link,
            "md5": file_info.get("md5Checksum"),
            "size_bytes": _safe_int(file_info.get("size")),
        }

    def _build_drive_client(self):  # pragma: no cover - best-effort client construction
        try:
            import google.auth
            from googleapiclient.discovery import build
        except ImportError:
            LOGGER.warning("Drive client unavailable: google-auth or googleapiclient missing")
            return None
        try:
            credentials, _ = google.auth.default(scopes=list(self._DRIVE_SCOPES))
        except Exception:
            LOGGER.exception("Unable to load ADC credentials for Drive uploads")
            return None
        try:
            return build("drive", "v3", credentials=credentials, cache_discovery=False)
        except Exception:
            LOGGER.exception("Failed to build Drive client")
            return None

    def _build_media_upload(self, *, path: Path, content_type: str) -> Any:
        try:
            from googleapiclient.http import MediaFileUpload

            return MediaFileUpload(str(path), mimetype=content_type, resumable=False)
        except ImportError:  # pragma: no cover - fallback for test stubs
            return _FallbackMediaUpload(str(path), mimetype=content_type)

    def _hash_file(self, path: Path, *, algorithm: str) -> str:
        try:
            digest = hashlib.new(algorithm)
        except ValueError as exc:  # pragma: no cover - invalid algorithm surfaces upstream
            raise ValueError(f"Unsupported hash algorithm: {algorithm}") from exc
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


__all__ = ["DossierUploader"]
