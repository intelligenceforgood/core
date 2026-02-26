"""Unit tests for SSI investigation, wallet, and evidence endpoints (Phase C).

Tests use a disposable in-memory SQLite database via monkeypatch so they
never pollute the development/production datastore.  All ``SsiStore``
calls are backed by a real store instance pointing at the temporary DB.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from fastapi.testclient import TestClient

from i4g.api.app import app
from i4g.store.ssi_store import SsiStore
from i4g.store.sql import METADATA

client = TestClient(app)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect all SSI SQL access to a disposable per-test SQLite database.

    Patches ``build_ssi_store`` in every SSI API module so each test
    gets a fresh, empty database with all tables created.
    """
    db_path = tmp_path / "test.db"
    engine = sa.create_engine(f"sqlite:///{db_path}", future=True)
    METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    store = SsiStore(session_factory=factory)

    monkeypatch.setattr("i4g.api.ssi_investigations.build_ssi_store", lambda **kw: store)
    monkeypatch.setattr("i4g.api.ssi_wallets.build_ssi_store", lambda **kw: store)
    monkeypatch.setattr("i4g.api.ssi_evidence.build_ssi_store", lambda **kw: store)
    yield store
    engine.dispose()


@pytest.fixture()
def store(_isolated_db: SsiStore) -> SsiStore:
    """Convenience alias for the test SsiStore instance."""
    return _isolated_db


def _seed_scan(store: SsiStore, **overrides: Any) -> str:
    """Insert a scan and return scan_id."""
    defaults: dict[str, Any] = {
        "url": "https://scam.example.com",
        "scan_type": "full",
        "domain": "scam.example.com",
    }
    defaults.update(overrides)
    return store.create_scan(**defaults)


def _seed_wallets(store: SsiStore, scan_id: str, count: int = 3) -> list[str]:
    """Insert *count* wallets and return wallet_ids."""
    ids = []
    for i in range(count):
        wid = store.add_wallet(
            scan_id=scan_id,
            token_symbol="ETH",
            network_short="ERC20",
            wallet_address=f"0x{'0' * 39}{i}",
            source="js",
            confidence=0.9,
            site_url="https://scam.example.com",
        )
        ids.append(wid)
    return ids


# =========================================================================
# C.1 — Investigation history / detail
# =========================================================================


class TestListInvestigations:
    """Tests for ``GET /investigations/ssi/history``."""

    def test_empty_list(self) -> None:
        """An empty database returns zero items."""
        resp = client.get("/investigations/ssi/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["count"] == 0

    def test_returns_scans(self, store: SsiStore) -> None:
        """Inserted scans appear in the history list."""
        _seed_scan(store)
        _seed_scan(store, url="https://phishing.example.com", domain="phishing.example.com")
        resp = client.get("/investigations/ssi/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["items"]) == 2

    def test_filter_by_domain(self, store: SsiStore) -> None:
        """Domain filter narrows results."""
        _seed_scan(store, domain="scam.example.com")
        _seed_scan(store, url="https://legit.example.com", domain="legit.example.com")
        resp = client.get("/investigations/ssi/history", params={"domain": "scam.example.com"})
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["domain"] == "scam.example.com"

    def test_filter_by_status(self, store: SsiStore) -> None:
        """Status filter narrows results."""
        scan_id = _seed_scan(store)
        store.complete_scan(scan_id, status="completed")
        _seed_scan(store)  # still "running"
        resp = client.get("/investigations/ssi/history", params={"status": "completed"})
        data = resp.json()
        assert data["count"] == 1

    def test_pagination(self, store: SsiStore) -> None:
        """Limit and offset work correctly."""
        for _ in range(5):
            _seed_scan(store)
        resp = client.get("/investigations/ssi/history", params={"limit": 2, "offset": 0})
        data = resp.json()
        assert data["count"] == 2
        assert data["limit"] == 2
        assert data["offset"] == 0

    def test_datetimes_serialized(self, store: SsiStore) -> None:
        """Datetime fields are serialized to ISO-8601 strings."""
        _seed_scan(store)
        resp = client.get("/investigations/ssi/history")
        item = resp.json()["items"][0]
        # created_at should be a string, not a dict/raw datetime
        assert isinstance(item["created_at"], str)
        assert "T" in item["created_at"]


class TestListActiveInvestigations:
    """Tests for ``GET /investigations/ssi/active``."""

    def test_returns_empty_stub(self) -> None:
        """Active endpoint returns empty stub."""
        resp = client.get("/investigations/ssi/active")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] == []
        assert data["count"] == 0


class TestGetInvestigation:
    """Tests for ``GET /investigations/ssi/{scan_id}``."""

    def test_not_found(self) -> None:
        """Non-existent scan_id returns 404."""
        resp = client.get("/investigations/ssi/nonexistent-id")
        assert resp.status_code == 404

    def test_returns_detail(self, store: SsiStore) -> None:
        """Existing scan returns full detail with wallets, PII, and agent actions."""
        scan_id = _seed_scan(store)
        _seed_wallets(store, scan_id, count=2)
        store.add_pii_exposure(scan_id=scan_id, field_type="email", field_label="email")
        store.log_agent_action(scan_id=scan_id, state="completed", sequence=1, action_type="click")

        resp = client.get(f"/investigations/ssi/{scan_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scan"]["scan_id"] == scan_id
        assert len(data["wallets"]) == 2
        assert len(data["piiExposures"]) == 1
        assert len(data["agentActions"]) == 1

    def test_empty_related_records(self, store: SsiStore) -> None:
        """Scan with no wallets/PII/actions returns empty lists."""
        scan_id = _seed_scan(store)
        resp = client.get(f"/investigations/ssi/{scan_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["wallets"] == []
        assert data["piiExposures"] == []
        assert data["agentActions"] == []


# =========================================================================
# C.2 — Wallet search & export
# =========================================================================


class TestSearchWallets:
    """Tests for ``GET /investigations/ssi/wallets``."""

    def test_empty_search(self) -> None:
        """Empty database returns zero wallets."""
        resp = client.get("/investigations/ssi/wallets")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["count"] == 0

    def test_search_returns_wallets(self, store: SsiStore) -> None:
        """Inserted wallets appear in search."""
        scan_id = _seed_scan(store)
        _seed_wallets(store, scan_id, count=3)
        resp = client.get("/investigations/ssi/wallets")
        data = resp.json()
        assert data["count"] > 0

    def test_filter_by_address(self, store: SsiStore) -> None:
        """Address filter returns matching wallet."""
        scan_id = _seed_scan(store)
        address = "0x" + "a" * 40
        store.add_wallet(
            scan_id=scan_id,
            token_symbol="ETH",
            network_short="ERC20",
            wallet_address=address,
        )
        resp = client.get("/investigations/ssi/wallets", params={"address": address})
        data = resp.json()
        assert data["count"] == 1

    def test_filter_by_token(self, store: SsiStore) -> None:
        """Token symbol filter works."""
        scan_id = _seed_scan(store)
        store.add_wallet(
            scan_id=scan_id, token_symbol="BTC", network_short="BTC", wallet_address="1A2b3C"
        )
        store.add_wallet(
            scan_id=scan_id, token_symbol="ETH", network_short="ERC20", wallet_address="0x123"
        )
        resp = client.get("/investigations/ssi/wallets", params={"token_symbol": "BTC"})
        data = resp.json()
        assert data["count"] == 1


class TestExportWalletsCsv:
    """Tests for ``GET /investigations/ssi/{scan_id}/wallets.csv``."""

    def test_not_found(self) -> None:
        """Non-existent scan returns 404."""
        resp = client.get("/investigations/ssi/nonexistent/wallets.csv")
        assert resp.status_code == 404

    def test_no_wallets(self, store: SsiStore) -> None:
        """Scan with no wallets returns 404."""
        scan_id = _seed_scan(store)
        resp = client.get(f"/investigations/ssi/{scan_id}/wallets.csv")
        assert resp.status_code == 404

    def test_csv_export(self, store: SsiStore) -> None:
        """CSV export contains header and data rows."""
        scan_id = _seed_scan(store)
        _seed_wallets(store, scan_id, count=2)
        resp = client.get(f"/investigations/ssi/{scan_id}/wallets.csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        lines = resp.text.strip().split("\n")
        assert len(lines) == 3  # header + 2 data rows
        assert "Wallet Address" in lines[0]

    def test_csv_content_disposition(self, store: SsiStore) -> None:
        """Response has a Content-Disposition header with filename."""
        scan_id = _seed_scan(store)
        _seed_wallets(store, scan_id, count=1)
        resp = client.get(f"/investigations/ssi/{scan_id}/wallets.csv")
        assert "attachment" in resp.headers.get("content-disposition", "")
        assert scan_id[:8] in resp.headers.get("content-disposition", "")


class TestExportWalletsXlsx:
    """Tests for ``GET /investigations/ssi/{scan_id}/wallets.xlsx``."""

    def test_not_found(self) -> None:
        """Non-existent scan returns 404."""
        resp = client.get("/investigations/ssi/nonexistent/wallets.xlsx")
        assert resp.status_code == 404

    def test_no_wallets(self, store: SsiStore) -> None:
        """Scan with no wallets returns 404."""
        scan_id = _seed_scan(store)
        resp = client.get(f"/investigations/ssi/{scan_id}/wallets.xlsx")
        assert resp.status_code == 404

    def test_xlsx_export_or_not_implemented(self, store: SsiStore) -> None:
        """XLSX export succeeds if openpyxl is installed, else returns 501."""
        scan_id = _seed_scan(store)
        _seed_wallets(store, scan_id, count=2)
        resp = client.get(f"/investigations/ssi/{scan_id}/wallets.xlsx")
        # openpyxl may or may not be installed
        assert resp.status_code in (200, 501)
        if resp.status_code == 200:
            assert "spreadsheetml" in resp.headers.get("content-type", "")

    def test_xlsx_without_openpyxl(self, store: SsiStore, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns 501 when openpyxl is not available."""
        scan_id = _seed_scan(store)
        _seed_wallets(store, scan_id, count=1)
        # Simulate openpyxl not being installed
        monkeypatch.setattr(
            "i4g.api.ssi_wallets._wallet_rows_to_xlsx",
            MagicMock(side_effect=RuntimeError("openpyxl is required for XLSX export.")),
        )
        resp = client.get(f"/investigations/ssi/{scan_id}/wallets.xlsx")
        assert resp.status_code == 501


# =========================================================================
# C.3 — Evidence & reports
# =========================================================================


class TestDownloadEvidenceBundle:
    """Tests for ``GET /investigations/ssi/{scan_id}/evidence-bundle``."""

    def test_not_found(self) -> None:
        """Non-existent scan returns 404."""
        resp = client.get("/investigations/ssi/nonexistent/evidence-bundle")
        assert resp.status_code == 404

    def test_no_evidence_path(self, store: SsiStore) -> None:
        """Scan with no evidence_path returns 404."""
        scan_id = _seed_scan(store)
        resp = client.get(f"/investigations/ssi/{scan_id}/evidence-bundle")
        assert resp.status_code == 404

    def test_local_evidence_zip(self, store: SsiStore, tmp_path: Path) -> None:
        """Local evidence ZIP is served from disk."""
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        zip_path = evidence_dir / "evidence.zip"
        zip_path.write_bytes(b"PK\x03\x04fake-zip-content")

        scan_id = _seed_scan(store)
        store.update_scan(scan_id, evidence_path=str(evidence_dir))

        resp = client.get(f"/investigations/ssi/{scan_id}/evidence-bundle")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"

    def test_missing_evidence_dir(self, store: SsiStore) -> None:
        """Non-existent evidence directory returns 404."""
        scan_id = _seed_scan(store)
        store.update_scan(scan_id, evidence_path="/nonexistent/path")
        resp = client.get(f"/investigations/ssi/{scan_id}/evidence-bundle")
        assert resp.status_code == 404

    def test_gcs_redirect(self, store: SsiStore, monkeypatch: pytest.MonkeyPatch) -> None:
        """GCS evidence path redirects to signed URL."""
        scan_id = _seed_scan(store)
        store.update_scan(scan_id, evidence_path="gs://my-bucket/ssi/evidence/scan-123")

        monkeypatch.setattr(
            "i4g.api.ssi_evidence._generate_signed_url",
            lambda bucket, blob, **kw: f"https://storage.googleapis.com/signed/{blob}",
        )

        resp = client.get(
            f"/investigations/ssi/{scan_id}/evidence-bundle",
            follow_redirects=False,
        )
        assert resp.status_code == 307
        assert "signed" in resp.headers["location"]


class TestDownloadLeaPackage:
    """Tests for ``GET /investigations/ssi/{scan_id}/lea-package``."""

    def test_not_found(self) -> None:
        """Non-existent scan returns 404."""
        resp = client.get("/investigations/ssi/nonexistent/lea-package")
        assert resp.status_code == 404

    def test_no_evidence_files(self, store: SsiStore, tmp_path: Path) -> None:
        """Empty evidence directory returns 404 (no LEA files)."""
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()

        scan_id = _seed_scan(store)
        store.update_scan(scan_id, evidence_path=str(evidence_dir))

        resp = client.get(f"/investigations/ssi/{scan_id}/lea-package")
        assert resp.status_code == 404

    def test_lea_package_with_files(self, store: SsiStore, tmp_path: Path) -> None:
        """LEA package includes available evidence files."""
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "report.pdf").write_bytes(b"%PDF-fake")
        (evidence_dir / "stix_bundle.json").write_text('{"type":"bundle"}')
        (evidence_dir / "evidence.zip").write_bytes(b"PK\x03\x04fake")

        scan_id = _seed_scan(store)
        store.update_scan(scan_id, evidence_path=str(evidence_dir))

        resp = client.get(f"/investigations/ssi/{scan_id}/lea-package")
        assert resp.status_code == 200
        assert "application/zip" in resp.headers["content-type"]

        # Verify the ZIP contains chain_of_custody.json
        import io
        import zipfile

        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        names = zf.namelist()
        assert "chain_of_custody.json" in names
        assert "report.pdf" in names
        assert "stix_bundle.json" in names

        custody = json.loads(zf.read("chain_of_custody.json"))
        assert custody["scan_id"] == scan_id
        assert custody["files_included"] == 3


class TestDownloadReportPdf:
    """Tests for ``GET /investigations/ssi/{scan_id}/report.pdf``."""

    def test_not_found(self) -> None:
        """Non-existent scan returns 404."""
        resp = client.get("/investigations/ssi/nonexistent/report.pdf")
        assert resp.status_code == 404

    def test_no_evidence_path(self, store: SsiStore) -> None:
        """Scan without evidence_path returns 404."""
        scan_id = _seed_scan(store)
        resp = client.get(f"/investigations/ssi/{scan_id}/report.pdf")
        assert resp.status_code == 404

    def test_local_pdf(self, store: SsiStore, tmp_path: Path) -> None:
        """Local PDF report is served from disk."""
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "report.pdf").write_bytes(b"%PDF-1.4 fake content")

        scan_id = _seed_scan(store)
        store.update_scan(scan_id, evidence_path=str(evidence_dir))

        resp = client.get(f"/investigations/ssi/{scan_id}/report.pdf")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"

    def test_missing_pdf(self, store: SsiStore, tmp_path: Path) -> None:
        """Evidence directory exists but has no report.pdf → 404."""
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()

        scan_id = _seed_scan(store)
        store.update_scan(scan_id, evidence_path=str(evidence_dir))

        resp = client.get(f"/investigations/ssi/{scan_id}/report.pdf")
        assert resp.status_code == 404

    def test_gcs_redirect(self, store: SsiStore, monkeypatch: pytest.MonkeyPatch) -> None:
        """GCS evidence path redirects to signed URL for PDF."""
        scan_id = _seed_scan(store)
        store.update_scan(scan_id, evidence_path="gs://my-bucket/ssi/evidence/scan-123")

        monkeypatch.setattr(
            "i4g.api.ssi_evidence._generate_signed_url",
            lambda bucket, blob, **kw: f"https://storage.googleapis.com/signed/{blob}",
        )

        resp = client.get(
            f"/investigations/ssi/{scan_id}/report.pdf",
            follow_redirects=False,
        )
        assert resp.status_code == 307
        assert "report.pdf" in resp.headers["location"]
