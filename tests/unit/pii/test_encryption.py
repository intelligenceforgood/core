"""Unit tests for i4g.pii.encryption — Fernet helpers."""

from __future__ import annotations

from cryptography.fernet import Fernet

from i4g.pii.encryption import build_fernet, decrypt_value, encrypt_value

# ------------------------------------------------------------------
# build_fernet
# ------------------------------------------------------------------


class TestBuildFernet:
    def test_none_key_returns_none(self) -> None:
        assert build_fernet(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert build_fernet("") is None

    def test_valid_44char_base64_key(self) -> None:
        key = Fernet.generate_key().decode()
        assert len(key) == 44
        f = build_fernet(key)
        assert isinstance(f, Fernet)

    def test_short_passphrase_derived(self) -> None:
        """A passphrase shorter than 44 chars is base64-encoded automatically."""
        f = build_fernet("my-short-passphrase")
        assert isinstance(f, Fernet)


# ------------------------------------------------------------------
# encrypt_value / decrypt_value round-trip
# ------------------------------------------------------------------


class TestEncryptDecryptRoundTrip:
    KEY = Fernet.generate_key().decode()

    def test_round_trip(self) -> None:
        plaintext = "alice@example.com"
        ciphertext = encrypt_value(plaintext, self.KEY)
        assert ciphertext is not None
        assert ciphertext != plaintext
        assert decrypt_value(ciphertext, self.KEY) == plaintext

    def test_none_plaintext_passes_through(self) -> None:
        assert encrypt_value(None, self.KEY) is None

    def test_none_key_passes_through(self) -> None:
        assert encrypt_value("secret", None) == "secret"

    def test_decrypt_none_ciphertext(self) -> None:
        assert decrypt_value(None, self.KEY) is None

    def test_decrypt_none_key(self) -> None:
        assert decrypt_value("some-cipher", None) == "some-cipher"

    def test_wrong_key_returns_none(self) -> None:
        ciphertext = encrypt_value("hello", self.KEY)
        other_key = Fernet.generate_key().decode()
        assert decrypt_value(ciphertext, other_key) is None

    def test_empty_key_passes_through(self) -> None:
        assert encrypt_value("data", "") == "data"
        assert decrypt_value("data", "") == "data"
