"""Unit tests for victim-contact redaction in the ingestion pipeline."""

from __future__ import annotations

from i4g.store.ingest import redact_victim_contact


def test_redact_email_and_phone() -> None:
    """Exact matches of email/phone are replaced with markers."""
    text = "Victim alice@example.com reported losing funds. Call 555-0100 for details."
    result = redact_victim_contact(
        text,
        {"contact_email": "alice@example.com", "contact_phone": "555-0100"},
    )
    assert result == "Victim [VICTIM_EMAIL] reported losing funds. Call [VICTIM_PHONE] for details."


def test_redact_email_only() -> None:
    """Only email is redacted when phone is absent."""
    text = "Contact alice@example.com for more info."
    result = redact_victim_contact(text, {"contact_email": "alice@example.com", "contact_phone": None})
    assert result == "Contact [VICTIM_EMAIL] for more info."


def test_no_redaction_when_fields_empty() -> None:
    """Text is unchanged when no contact fields are provided."""
    text = "No victim info here."
    result = redact_victim_contact(text, {"contact_email": None, "contact_phone": None})
    assert result == text


def test_no_redaction_when_no_match() -> None:
    """Text is unchanged when contact values don't appear in text."""
    text = "Some unrelated case text."
    result = redact_victim_contact(text, {"contact_email": "other@example.com", "contact_phone": "999-9999"})
    assert result == text


def test_redact_multiple_occurrences() -> None:
    """All occurrences of the same contact value are replaced."""
    text = "alice@example.com said to contact alice@example.com again."
    result = redact_victim_contact(text, {"contact_email": "alice@example.com", "contact_phone": None})
    assert result == "[VICTIM_EMAIL] said to contact [VICTIM_EMAIL] again."
