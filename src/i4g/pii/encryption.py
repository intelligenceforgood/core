"""Fernet encryption helpers for victim intake PII fields.

Provides symmetric encrypt/decrypt using a single Fernet key supplied
via the ``I4G_CRYPTO__PII_KEY`` environment variable.  Key rotation with
``MultiFernet`` can be added later if needed.
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

LOGGER = logging.getLogger(__name__)


def build_fernet(raw_key: str | None) -> Fernet | None:
    """Construct a :class:`Fernet` instance from a raw key string.

    Accepts either a 44-character URL-safe base64 key or a shorter
    passphrase that will be base64-encoded automatically.

    Args:
        raw_key: The raw key material. ``None`` or empty disables encryption.

    Returns:
        A configured :class:`Fernet` instance, or ``None`` when no key is
        provided or the key is invalid.
    """
    if not raw_key:
        return None
    candidate = raw_key.strip()
    try:
        key_bytes = candidate.encode("utf-8")
        if len(candidate) != 44:
            # Derive a 32-byte key via SHA-256, then base64-encode for Fernet
            derived = hashlib.sha256(key_bytes).digest()
            key_bytes = base64.urlsafe_b64encode(derived)
        return Fernet(key_bytes)
    except (ValueError, InvalidToken):
        LOGGER.warning("Invalid Fernet key — encryption disabled.")
        return None


def encrypt_value(plaintext: str | None, raw_key: str | None) -> str | None:
    """Encrypt a plaintext string, returning the ciphertext as a UTF-8 string.

    Args:
        plaintext: Value to encrypt.
        raw_key: Raw key material passed to :func:`build_fernet`.

    Returns:
        Encrypted value (base64-encoded token string), or the original
        plaintext when encryption is disabled or input is ``None``.
    """
    if plaintext is None or not raw_key:
        return plaintext
    fernet = build_fernet(raw_key)
    if fernet is None:
        return plaintext
    return fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(ciphertext: str | None, raw_key: str | None) -> str | None:
    """Decrypt a Fernet-encrypted string back to plaintext.

    Args:
        ciphertext: Previously encrypted value.
        raw_key: Raw key material passed to :func:`build_fernet`.

    Returns:
        Decrypted plaintext, or the original ciphertext when decryption is
        disabled or input is ``None``.  Returns ``None`` if decryption fails
        (e.g. wrong key).
    """
    if ciphertext is None or not raw_key:
        return ciphertext
    fernet = build_fernet(raw_key)
    if fernet is None:
        return ciphertext
    try:
        return fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        LOGGER.warning("Fernet decryption failed — returning None.")
        return None
