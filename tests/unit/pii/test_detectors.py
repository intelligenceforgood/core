"""Tests for regex-based PII detectors (F1, F6)."""

import pytest

from i4g.pii.detectors import (
    PiiMatch,
    detect_addresses,
    detect_all,
    detect_credit_cards,
    detect_dobs,
    detect_emails,
    detect_ipv4,
    detect_phones,
    detect_ssns,
)


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


class TestDetectEmails:
    def test_simple_email(self):
        matches = detect_emails("Contact me at alice@example.com for details.")
        assert len(matches) == 1
        assert matches[0].value == "alice@example.com"
        assert matches[0].prefix == "EID"

    def test_multiple_emails(self):
        text = "From bob@corp.io to alice@example.com cc admin@test.org"
        matches = detect_emails(text)
        assert len(matches) == 3

    def test_no_email(self):
        assert detect_emails("No personal info here.") == []


# ---------------------------------------------------------------------------
# IPv4
# ---------------------------------------------------------------------------


class TestDetectIPv4:
    def test_valid_ipv4(self):
        matches = detect_ipv4("Server at 192.168.1.1 responded.")
        assert len(matches) == 1
        assert matches[0].value == "192.168.1.1"
        assert matches[0].prefix == "IPA"

    def test_rejects_out_of_range(self):
        matches = detect_ipv4("Address 999.999.999.999 is invalid.")
        assert len(matches) == 0

    def test_multiple_ips(self):
        text = "Nodes: 10.0.0.1, 10.0.0.2, 172.16.0.1"
        matches = detect_ipv4(text)
        assert len(matches) == 3


# ---------------------------------------------------------------------------
# SSN
# ---------------------------------------------------------------------------


class TestDetectSSNs:
    def test_dashed_ssn(self):
        matches = detect_ssns("SSN: 123-45-6789")
        assert len(matches) == 1
        assert matches[0].prefix == "TIN"
        assert matches[0].value == "123-45-6789"

    def test_space_separated_ssn(self):
        matches = detect_ssns("SSN: 123 45 6789")
        assert len(matches) == 1

    def test_plain_ssn(self):
        matches = detect_ssns("SSN: 123456789")
        assert len(matches) == 1

    def test_rejects_invalid_area_000(self):
        assert detect_ssns("SSN: 000-12-3456") == []

    def test_rejects_invalid_area_666(self):
        assert detect_ssns("SSN: 666-12-3456") == []

    def test_rejects_area_9xx(self):
        assert detect_ssns("SSN: 900-12-3456") == []


# ---------------------------------------------------------------------------
# Credit Card
# ---------------------------------------------------------------------------


class TestDetectCreditCards:
    def test_visa(self):
        # Valid Visa test number
        matches = detect_credit_cards("Card: 4111 1111 1111 1111")
        assert len(matches) == 1
        assert matches[0].prefix == "CCN"

    def test_mastercard(self):
        matches = detect_credit_cards("Card: 5500-0000-0000-0004")
        assert len(matches) == 1
        assert matches[0].prefix == "CCN"

    def test_fails_luhn(self):
        # Invalid checksum
        matches = detect_credit_cards("Card: 4111 1111 1111 1112")
        assert len(matches) == 0

    def test_amex(self):
        matches = detect_credit_cards("Card: 378282246310005")
        assert len(matches) == 1


# ---------------------------------------------------------------------------
# Phone
# ---------------------------------------------------------------------------


class TestDetectPhones:
    def test_us_format(self):
        matches = detect_phones("Call me at (555) 012-3456.")
        assert len(matches) == 1
        assert matches[0].prefix == "PHN"

    def test_international(self):
        matches = detect_phones("Reach: +44 20 7946 0958")
        assert len(matches) == 1

    def test_short_number_rejected(self):
        # 6 digits or fewer should not match
        matches = detect_phones("Ref: 123456")
        assert len(matches) == 0


# ---------------------------------------------------------------------------
# DOB
# ---------------------------------------------------------------------------


class TestDetectDOBs:
    def test_iso_format(self):
        matches = detect_dobs("Born: 1990-05-15")
        assert len(matches) == 1
        assert matches[0].prefix == "DOB"

    def test_us_format(self):
        matches = detect_dobs("DOB: 05/15/1990")
        assert len(matches) == 1

    def test_day_month_year(self):
        matches = detect_dobs("Birthday: 15-Jan-1990")
        assert len(matches) == 1


# ---------------------------------------------------------------------------
# Address
# ---------------------------------------------------------------------------


class TestDetectAddresses:
    def test_street_address(self):
        matches = detect_addresses("Lives at 123 Main Street, Springfield.")
        assert len(matches) == 1
        assert matches[0].prefix == "ADR"

    def test_with_unit(self):
        matches = detect_addresses("Office: 456 Oak Ave Apt 5B")
        assert len(matches) == 1

    def test_no_address(self):
        assert detect_addresses("Just some text.") == []


# ---------------------------------------------------------------------------
# detect_all (composite)
# ---------------------------------------------------------------------------


class TestDetectAll:
    def test_mixed_pii(self):
        text = "SSN 123-45-6789, email test@example.com, IP 10.0.0.1"
        matches = detect_all(text)
        prefixes = {m.prefix for m in matches}
        assert "TIN" in prefixes
        assert "EID" in prefixes
        assert "IPA" in prefixes

    def test_no_overlapping_spans(self):
        text = "SSN 123-45-6789 and phone (555) 012-3456 and card 4111 1111 1111 1111"
        matches = detect_all(text)
        spans = [(m.start, m.end) for m in matches]
        # Verify no two spans overlap
        for i, (s1, e1) in enumerate(spans):
            for s2, e2 in spans[i + 1 :]:
                assert e1 <= s2 or e2 <= s1, f"Overlap: ({s1},{e1}) and ({s2},{e2})"

    def test_empty_text(self):
        assert detect_all("") == []
