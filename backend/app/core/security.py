"""Passwords (argon2), JWT access tokens, rotating refresh tokens with reuse detection, opaque token hashing."""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import select, update

from app import models as m
from app.config import get_settings

logger = logging.getLogger(__name__)
_hasher = PasswordHasher()
ALGO = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# constant-time dummy check to avoid user enumeration by timing
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


def dummy_verify() -> None:
    verify_password("not-the-password", _DUMMY_HASH)


@lru_cache
def jwt_secret() -> str:
    settings = get_settings()
    if settings.jwt_secret:
        return settings.jwt_secret
    if settings.env not in ("dev", "test"):
        raise RuntimeError("APP_JWT_SECRET is required outside dev/test")
    f = settings.data_dir / "dev_jwt_secret"
    f.parent.mkdir(parents=True, exist_ok=True)
    if not f.exists():
        f.write_text(base64.b64encode(os.urandom(32)).decode())
        logger.warning("APP_JWT_SECRET is not set: generated a dev secret in %s", f)
    return f.read_text().strip()


def create_access_token(user_id: str) -> str:
    now = datetime.now(UTC)
    payload = {"sub": user_id, "type": "access", "iat": now,
               "exp": now + timedelta(minutes=get_settings().access_token_minutes), "jti": secrets.token_hex(8)}
    return jwt.encode(payload, jwt_secret(), algorithm=ALGO)


def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, jwt_secret(), algorithms=[ALGO], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        return None
    return payload["sub"] if payload.get("type") == "access" else None


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_refresh(s, user_id: str, family_id: str | None = None) -> str:  # noqa: ANN001
    raw = "rt_" + secrets.token_urlsafe(48)
    s.add(m.RefreshToken(user_id=user_id, token_hash=hash_token(raw), family_id=family_id or secrets.token_hex(16),
                         expires_at=datetime.now(UTC) + timedelta(days=get_settings().refresh_token_days)))
    return raw


class RefreshError(Exception):
    pass


def rotate_refresh(s, raw: str) -> tuple[str, str]:  # noqa: ANN001
    """Exchange a refresh token for a new one. Reuse of a rotated/revoked token revokes the whole family."""
    row = s.scalars(select(m.RefreshToken).where(m.RefreshToken.token_hash == hash_token(raw))).first()
    now = datetime.now(UTC)
    if row is None:
        raise RefreshError("unknown refresh token")
    if row.revoked_at is not None:
        s.execute(update(m.RefreshToken).where(m.RefreshToken.family_id == row.family_id,
                                               m.RefreshToken.revoked_at.is_(None)).values(revoked_at=now))
        s.commit()
        raise RefreshError("refresh token reuse detected")
    if row.expires_at < now:
        raise RefreshError("refresh token expired")
    new_raw = issue_refresh(s, row.user_id, row.family_id)
    row.revoked_at = now
    row.replaced_by = hash_token(new_raw)[:16]
    return row.user_id, new_raw


def revoke_refresh(s, raw: str) -> None:  # noqa: ANN001
    row = s.scalars(select(m.RefreshToken).where(m.RefreshToken.token_hash == hash_token(raw))).first()
    if row is not None:
        s.execute(update(m.RefreshToken).where(m.RefreshToken.family_id == row.family_id,
                                               m.RefreshToken.revoked_at.is_(None))
                  .values(revoked_at=datetime.now(UTC)))


def new_api_token() -> tuple[str, str, str]:
    """Returns (raw token shown once, sha256 hash stored, display prefix)."""
    raw = "aisw_" + secrets.token_urlsafe(32)
    return raw, hash_token(raw), raw[:10]
