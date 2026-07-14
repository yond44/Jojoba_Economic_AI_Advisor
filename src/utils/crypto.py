"""
Secret encryption for user-provided credentials (e.g. n8n API keys).
====================================================================

GOAL (from the product requirement)
------------------------------------
A user pastes their n8n API key so the app can deploy/activate workflows on
THEIR n8n instance. We must:
  1. never store the key in plaintext,
  2. never return it in any API response,
  3. never write it to logs,
  4. only decrypt it transiently, in memory, at the moment we call n8n.

HONEST SECURITY BOUNDARY (put this in your portfolio write-up — reviewers love it)
---------------------------------------------------------------------------------
This is encryption-at-rest with a server-held key, NOT zero-knowledge. Because
the server must decrypt the key to actually call n8n on a schedule, whoever
controls ENCRYPTION_KEY can decrypt. True "even the operator can't read it"
would require the key to live only in the user's browser — but then the server
could not run scheduled/automated deploys, which is the whole point here.

So the guarantee we DO provide:
  - ciphertext at rest (Fernet / AES-128-CBC + HMAC-SHA256, authenticated),
  - key derived from a dedicated ENCRYPTION_KEY (separate from JWT signing),
  - plaintext exists only inside a single function call, then is dropped,
  - responses expose only a masked hint ("••••ab12"), never the value.

DESIGN
------
Fernet needs a 32-byte urlsafe-base64 key. We derive it deterministically from
the configured secret via SHA-256, so operators only manage ONE secret string,
not a base64 Fernet key. Rotating ENCRYPTION_KEY invalidates old ciphertexts by
design — see rotate notes in BUILD_GUIDE.md.
"""
from __future__ import annotations

import base64
import hashlib
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from src.config.settings import get_settings

logger = logging.getLogger(__name__)


def _derive_fernet_key(secret: str) -> bytes:
    """Deterministically turn any secret string into a valid Fernet key.

    Fernet requires exactly 32 url-safe base64 bytes. SHA-256 gives us 32
    raw bytes from an arbitrary-length secret; base64 makes it Fernet-shaped.
    """
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


class SecretBox:
    """Thin wrapper around Fernet with our derivation + masking helpers."""

    def __init__(self, secret: Optional[str] = None):
        secret = secret or get_settings().encryption_secret
        if not secret or secret == "change-me-to-a-long-random-string":
            logger.warning(
                "⚠️ SecretBox is using a default/placeholder secret. Set a strong "
                "ENCRYPTION_KEY in production or stored secrets are trivially decryptable."
            )
        self._fernet = Fernet(_derive_fernet_key(secret))

    def encrypt(self, plaintext: str) -> str:
        """Return url-safe ciphertext (str) for storage."""
        if plaintext is None:
            raise ValueError("Cannot encrypt None")
        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt(self, token: str) -> str:
        """Return plaintext. Raises ValueError on tamper/wrong-key."""
        try:
            return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError(
                "Failed to decrypt secret — wrong ENCRYPTION_KEY or corrupted ciphertext."
            ) from exc

    @staticmethod
    def mask(plaintext: str, visible: int = 4) -> str:
        """Return a safe display hint like '••••cd34' (last N chars only)."""
        if not plaintext:
            return ""
        tail = plaintext[-visible:] if len(plaintext) > visible else plaintext
        return "••••" + tail


_box: Optional[SecretBox] = None


def get_secret_box() -> SecretBox:
    global _box
    if _box is None:
        _box = SecretBox()
    return _box


def encrypt_secret(plaintext: str) -> str:
    return get_secret_box().encrypt(plaintext)


def decrypt_secret(token: str) -> str:
    return get_secret_box().decrypt(token)


def mask_secret(plaintext: str, visible: int = 4) -> str:
    return SecretBox.mask(plaintext, visible)
