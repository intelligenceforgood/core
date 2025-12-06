"""Tests for Drive ACL fetch helper."""

from __future__ import annotations

from i4g.reports.dossier_uploads import DossierUploader


class _ListStub:
    def __init__(self, payload: dict[str, object]):
        self.payload = payload

    def execute(self) -> dict[str, object]:
        return self.payload


class _DriveServiceStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, str | None, bool | None]] = []

    def files(self) -> "_DriveServiceStub":
        return self

    def permissions(self) -> "_DriveServiceStub":
        return self

    def get(self, *, fileId: str, fields: str, supportsAllDrives: bool = True) -> _ListStub:
        self.calls.append(("get", fileId, fields, supportsAllDrives))
        return _ListStub(
            {
                "id": fileId,
                "name": "LEA Shared",
                "webViewLink": f"https://drive.google.com/drive/folders/{fileId}",
                "driveId": "drive-1",
            }
        )

    def list(self, *, fileId: str, fields: str, supportsAllDrives: bool = True) -> _ListStub:
        self.calls.append(("list", fileId, fields, supportsAllDrives))
        return _ListStub(
            {
                "permissions": [
                    {
                        "id": "perm-1",
                        "type": "group",
                        "role": "reader",
                        "displayName": "LEA Analysts",
                    }
                ]
            }
        )


def test_fetch_acl_returns_permissions() -> None:
    drive = _DriveServiceStub()
    uploader = DossierUploader(drive_parent_id="folder-123", drive_service=drive)

    summary, warnings = uploader.fetch_acl()

    assert warnings == []
    assert summary is not None
    assert summary["folder_id"] == "folder-123"
    assert summary["name"] == "LEA Shared"
    assert summary["permissions"][0]["role"] == "reader"
    assert drive.calls[0][0] == "get"
    assert drive.calls[1][0] == "list"


def test_fetch_acl_missing_folder_id_returns_warning() -> None:
    uploader = DossierUploader(drive_parent_id=None, drive_service=None)

    summary, warnings = uploader.fetch_acl(folder_id=None)

    assert summary is None
    assert warnings
