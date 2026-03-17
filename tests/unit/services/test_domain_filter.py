"""Unit tests for domain blocklist filtering."""

from __future__ import annotations

from i4g.services.domain_filter import (
    _extract_domain,
    get_merged_blocklist,
    is_domain_blocked,
)


class TestIsDomainBlocked:
    """Test domain blocklist matching."""

    def test_exact_match_blocks(self) -> None:
        assert is_domain_blocked("https://google.com/search", ["google.com"]) is True

    def test_subdomain_match_blocks(self) -> None:
        assert is_domain_blocked("https://mail.google.com/inbox", ["google.com"]) is True

    def test_deep_subdomain_match_blocks(self) -> None:
        assert is_domain_blocked("https://a.b.c.google.com/path", ["google.com"]) is True

    def test_unrelated_domain_passes(self) -> None:
        assert is_domain_blocked("https://scam-site.com", ["google.com"]) is False

    def test_partial_name_does_not_match(self) -> None:
        # "notgoogle.com" should NOT be blocked by "google.com"
        assert is_domain_blocked("https://notgoogle.com", ["google.com"]) is False

    def test_empty_blocklist_passes_all(self) -> None:
        assert is_domain_blocked("https://google.com", []) is False

    def test_multiple_blocklist_entries(self) -> None:
        blocklist = ["google.com", "facebook.com"]
        assert is_domain_blocked("https://facebook.com/page", blocklist) is True
        assert is_domain_blocked("https://twitter.com/post", blocklist) is False

    def test_url_without_scheme(self) -> None:
        assert is_domain_blocked("google.com/search", ["google.com"]) is True

    def test_case_insensitive(self) -> None:
        assert is_domain_blocked("https://GOOGLE.COM/search", ["google.com"]) is True

    def test_empty_url(self) -> None:
        assert is_domain_blocked("", ["google.com"]) is False


class TestExtractDomain:
    """Test the internal domain extraction helper."""

    def test_standard_url(self) -> None:
        assert _extract_domain("https://example.com/page") == "example.com"

    def test_url_with_port(self) -> None:
        assert _extract_domain("https://example.com:8443/api") == "example.com"

    def test_url_without_scheme(self) -> None:
        assert _extract_domain("example.com/path") == "example.com"

    def test_empty_string(self) -> None:
        assert _extract_domain("") is None


class TestGetMergedBlocklist:
    """Test blocklist merging."""

    def test_empty_settings_returns_defaults(self) -> None:
        result = get_merged_blocklist([])
        assert "google.com" in result
        assert "facebook.com" in result

    def test_custom_entries_added(self) -> None:
        result = get_merged_blocklist(["custom-domain.com"])
        assert "custom-domain.com" in result
        assert "google.com" in result  # defaults still present

    def test_deduplication(self) -> None:
        result = get_merged_blocklist(["google.com"])
        assert result.count("google.com") == 1

    def test_sorted_output(self) -> None:
        result = get_merged_blocklist(["zzz-domain.com", "aaa-domain.com"])
        assert result == sorted(result)
