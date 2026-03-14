"""Unit tests for infrastructure clustering job (S5-29)."""

from __future__ import annotations

from i4g.worker.jobs.infrastructure_clustering import _classify_edge_type


def test_classify_shared_ip() -> None:
    """Edge with ip_address entity is classified as shared_ip."""
    assert _classify_edge_type("ip_address", "domain") == "shared_ip"
    assert _classify_edge_type("domain", "ip_address") == "shared_ip"


def test_classify_shared_registrar() -> None:
    """Edge with registrar entity is classified as shared_registrar."""
    assert _classify_edge_type("registrar", "domain") == "shared_registrar"
    assert _classify_edge_type("domain", "registrar") == "shared_registrar"


def test_classify_shared_hosting() -> None:
    """Edge with hosting_provider or nameserver is shared_hosting."""
    assert _classify_edge_type("hosting_provider", "domain") == "shared_hosting"
    assert _classify_edge_type("domain", "nameserver") == "shared_hosting"


def test_classify_fallback_shared_case() -> None:
    """Non-infrastructure entity pairs default to shared_case."""
    assert _classify_edge_type("domain", "url") == "shared_case"
    assert _classify_edge_type("email_domain", "domain") == "shared_case"
