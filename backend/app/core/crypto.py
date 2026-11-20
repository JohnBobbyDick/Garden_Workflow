"""AES-256-GCM encryption for stored credentials, with key versioning.

Ciphertext format: ``v<key_version>:<base64(nonce(12) || ciphertext || tag)>``. Old key versions stay
decryptable after rotation; new values are always encrypted with the current (highest) version."""

from __future__ import annotations

import base64
import binascii
import logging
import os
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)


class CryptoError(ValueError):
    pass


def _decode_key(b64: str) -> bytes:
    try:
        raw = base64.b64decode(b64.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise CryptoError("master key is not valid base64") from exc
    if len(raw) != 32:
        raise CryptoError("master key must be 32 bytes (AES-256)")
    return raw


class SecretBox:
    def __init__(self, keys: dict[int, str], current: int | None = None) -> None:
        if not keys:
            raise CryptoError("no master keys configured")
        self._keys = {v: AESGCM(_decode_key(k)) for v, k in keys.items()}
        self.current = current if current is not None else max(keys)
        if self.current not in self._keys:
            raise CryptoError("current key version is not configured")

    def encrypt(self, plaintext: str, aad: bytes = b"aisw") -> str:
        nonce = os.urandom(12)
        ct = self._keys[self.current].encrypt(nonce, plaintext.encode("utf-8"), aad)
        return f"v{self.current}:" + base64.b64encode(nonce + ct).decode()

    def encrypt_bytes(self, data: bytes, aad: bytes = b"aisw-blob") -> bytes:
        nonce = os.urandom(12)
        return f"v{self.current}:".encode() + nonce + self._keys[self.current].encrypt(nonce, data, aad)

    def decrypt_bytes(self, blob: bytes, aad: bytes = b"aisw-blob") -> bytes:
        head, sep, rest = blob.partition(b":")
        if not sep or not head.startswith(b"v") or not head[1:].isdigit():
            raise CryptoError("malformed encrypted blob")
        key = self._keys.get(int(head[1:]))
        if key is None:
            raise CryptoError("unknown key version")
        try:
            return key.decrypt(rest[:12], rest[12:], aad)
        except InvalidTag as exc:
            raise CryptoError("blob authentication failed") from exc

    def decrypt(self, token: str, aad: bytes = b"aisw") -> str:
        try:
            version_s, payload = token.split(":", 1)
            version = int(version_s.removeprefix("v"))
            blob = base64.b64decode(payload, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise CryptoError("malformed ciphertext") from exc
        key = self._keys.get(version)
        if key is None:
            raise CryptoError(f"unknown key version {version}")
        try:
            return key.decrypt(blob[:12], blob[12:], aad).decode("utf-8")
        except InvalidTag as exc:
            raise CryptoError("ciphertext authentication failed") from exc


def parse_master_keys(spec: str) -> dict[int, str]:
    """``"<b64>"`` → {1: b64}; ``"1:<b64>,2:<b64>"`` → versioned keys."""
    keys: dict[int, str] = {}
    for part in (p.strip() for p in spec.split(",") if p.strip()):
        head, sep, tail = part.partition(":")
        if sep and head.isdigit():
            keys[int(head)] = tail
        else:
            keys[1] = part
    return keys


@lru_cache
def get_box() -> SecretBox:
    from app.config import get_settings

    settings = get_settings()
    spec = settings.master_key
    if not spec:
        if settings.env not in ("dev", "test"):
            raise CryptoError("APP_MASTER_KEY is required outside dev/test")
        key_file = settings.data_dir / "dev_master_key"
        key_file.parent.mkdir(parents=True, exist_ok=True)
        if not key_file.exists():
            key_file.write_text(base64.b64encode(os.urandom(32)).decode())
            logger.warning("APP_MASTER_KEY is not set: generated a dev master key in %s (never use in production)",
                           key_file)
        spec = key_file.read_text().strip()
    return SecretBox(parse_master_keys(spec))
