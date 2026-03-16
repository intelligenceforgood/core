"""Unit tests for URL normalization utility."""

from __future__ import annotations

import pytest

from i4g.utils.url_normalization import normalize_url


class TestBasicNormalization:
    """Test basic URL canonicalization."""

    def test_lowercase_scheme(self) -> None:
        assert normalize_url("HTTP://Example.Com/path") == "http://example.com/path"

    def test_lowercase_hostname(self) -> None:
        assert normalize_url("https://EXAMPLE.COM/Path") == "https://example.com/Path"

    def test_strip_trailing_slash(self) -> None:
        assert normalize_url("https://example.com/path/") == "https://example.com/path"

    def test_preserve_root_slash(self) -> None:
        assert normalize_url("https://example.com/") == "https://example.com/"

    def test_strip_default_http_port(self) -> None:
        assert normalize_url("http://example.com:80/path") == "http://example.com/path"

    def test_strip_default_https_port(self) -> None:
        assert normalize_url("https://example.com:443/path") == "https://example.com/path"

    def test_preserve_non_default_port(self) -> None:
        assert normalize_url("https://example.com:8443/path") == "https://example.com:8443/path"


class TestTrackingParamRemoval:
    """Test removal of common tracking parameters."""

    def test_remove_utm_params(self) -> None:
        url = "https://example.com/page?utm_source=google&utm_medium=cpc&key=val"
        assert normalize_url(url) == "https://example.com/page?key=val"

    def test_remove_fbclid(self) -> None:
        url = "https://example.com/page?fbclid=abc123&keep=yes"
        assert normalize_url(url) == "https://example.com/page?keep=yes"

    def test_remove_gclid(self) -> None:
        url = "https://example.com/page?gclid=xyz&data=1"
        assert normalize_url(url) == "https://example.com/page?data=1"

    def test_all_tracking_removed_leaves_no_query(self) -> None:
        url = "https://example.com/page?utm_source=a&fbclid=b"
        assert normalize_url(url) == "https://example.com/page"


class TestQueryParamSorting:
    """Test that query parameters are sorted alphabetically."""

    def test_sort_params(self) -> None:
        url = "https://example.com/search?z=1&a=2&m=3"
        assert normalize_url(url) == "https://example.com/search?a=2&m=3&z=1"


class TestFragmentRemoval:
    """Test that fragments are removed."""

    def test_remove_fragment(self) -> None:
        assert normalize_url("https://example.com/page#section") == "https://example.com/page"

    def test_remove_fragment_with_query(self) -> None:
        url = "https://example.com/page?q=1#top"
        assert normalize_url(url) == "https://example.com/page?q=1"


class TestIDNDomains:
    """Test internationalized domain name handling."""

    def test_idn_to_punycode(self) -> None:
        result = normalize_url("https://münchen.de/path")
        assert "xn--mnchen-3ya.de" in result

    def test_ascii_domain_unchanged(self) -> None:
        assert normalize_url("https://example.com/path") == "https://example.com/path"


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_no_scheme_prepends_https(self) -> None:
        assert normalize_url("example.com/path") == "https://example.com/path"

    def test_empty_string(self) -> None:
        assert normalize_url("") == ""

    def test_whitespace_only(self) -> None:
        assert normalize_url("   ") == "   "

    def test_preserves_www_prefix(self) -> None:
        result = normalize_url("https://www.example.com/path")
        assert result == "https://www.example.com/path"

    def test_strips_whitespace(self) -> None:
        assert normalize_url("  https://example.com/path  ") == "https://example.com/path"

    def test_percent_encoding_normalization(self) -> None:
        """Unnecessarily encoded characters should be decoded."""
        url = "https://example.com/%7Euser/path"
        result = normalize_url(url)
        assert result == "https://example.com/~user/path"


class TestIdempotency:
    """Test that normalize_url is idempotent."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/path?q=1&z=2",
            "HTTP://EXAMPLE.COM:443/PATH/",
            "https://www.example.com/page?utm_source=google&key=val#section",
            "example.com/path",
            "https://example.com/%7Euser",
        ],
    )
    def test_idempotent(self, url: str) -> None:
        once = normalize_url(url)
        twice = normalize_url(once)
        assert once == twice, f"Not idempotent: {once!r} != {twice!r}"
