from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models as m
from app.config import get_settings
from app.core.audit import audit
from app.core.errors import ApiError, conflict, unauthorized
from app.core.registration import consume_registration_code, send_registration_code
from app.core.security import (
    RefreshError,
    create_access_token,
    dummy_verify,
    hash_password,
    issue_refresh,
    revoke_refresh,
    rotate_refresh,
    verify_password,
)
from app.deps import client_ip, current_user, get_session

router = APIRouter(prefix="/auth", tags=["auth"])

_attempts: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()


def reset_rate_limits() -> None:
    with _lock:
        _attempts.clear()


def _rate_limit(key: str) -> None:
    limit = get_settings().login_rate_limit
    now = time.monotonic()
    with _lock:
        q = _attempts[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= limit:
            raise ApiError(429, "rate_limited", "слишком много попыток входа, повторите через минуту")
        q.append(now)


class RegistrationEmail(BaseModel):
    email: EmailStr
    locale: str = Field(default="ru", pattern="^(ru|en)$")


class RegisterIn(RegistrationEmail):
    code: str = Field(pattern=r"^[0-9]{6}$", min_length=6, max_length=6)
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(default="", max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)


class RefreshIn(BaseModel):
    refresh_token: str = Field(max_length=200)


def _tokens(s: Session, user: m.User, family: str | None = None) -> dict:
    refresh = issue_refresh(s, user.id, family)
    s.commit()
    return {"access_token": create_access_token(user.id), "refresh_token": refresh, "token_type": "bearer",
            "expires_in": get_settings().access_token_minutes * 60}


def user_out(u: m.User) -> dict:
    return {"id": u.id, "email": u.email, "display_name": u.display_name, "locale": u.locale,
            "is_platform_admin": u.is_platform_admin}


@router.post("/registration-code", status_code=204)
async def registration_code(body: RegistrationEmail, request: Request, s: Session = Depends(get_session)) -> Response:
    email = body.email.lower()
    _rate_limit(f"registration-code:{client_ip(request)}")
    if s.scalar(select(m.User.id).where(m.User.email == email)):
        raise conflict("пользователь с таким e-mail уже существует", "email_taken")
    await send_registration_code(s, email, body.locale)
    return Response(status_code=204)


@router.post("/register", status_code=201)
def register(body: RegisterIn, request: Request, s: Session = Depends(get_session)) -> dict:
    email = body.email.lower()
    if s.scalars(select(m.User).where(m.User.email == email)).first():
        raise conflict("пользователь с таким e-mail уже существует", "email_taken")
    consume_registration_code(s, email, body.code)
    first = (s.scalar(select(func.count()).select_from(m.User)) or 0) == 0
    user = m.User(email=email, password_hash=hash_password(body.password),
                  display_name=body.display_name or email.split("@")[0], locale=body.locale, is_platform_admin=first)
    ws = m.Workspace(name=f"{user.display_name}: личное пространство")
    s.add_all([user, ws])
    s.flush()
    s.add(m.Membership(workspace_id=ws.id, user_id=user.id, role="admin"))
    audit(s, "auth.register", user_id=user.id, workspace_id=ws.id, target=email, ip=client_ip(request))
    return {**_tokens(s, user), "user": user_out(user)}


@router.post("/login")
def login(body: LoginIn, request: Request, s: Session = Depends(get_session)) -> dict:
    email = body.email.lower()
    _rate_limit(f"{client_ip(request)}|{email}")
    user = s.scalars(select(m.User).where(m.User.email == email)).first()
    if user is None:
        dummy_verify()
        raise unauthorized("неверный e-mail или пароль", "invalid_credentials")
    if not verify_password(body.password, user.password_hash) or not user.is_active:
        audit(s, "auth.login_failed", user_id=user.id, target=email, ip=client_ip(request))
        s.commit()
        raise unauthorized("неверный e-mail или пароль", "invalid_credentials")
    audit(s, "auth.login", user_id=user.id, target=email, ip=client_ip(request))
    return {**_tokens(s, user), "user": user_out(user)}


@router.post("/refresh")
def refresh(body: RefreshIn, s: Session = Depends(get_session)) -> dict:
    try:
        user_id, new_raw = rotate_refresh(s, body.refresh_token)
    except RefreshError as exc:
        raise unauthorized("сессия недействительна, войдите заново", "invalid_refresh") from exc
    user = s.get(m.User, user_id)
    if user is None or not user.is_active:
        raise unauthorized("пользователь отключён", "invalid_refresh")
    s.commit()
    return {"access_token": create_access_token(user.id), "refresh_token": new_raw, "token_type": "bearer",
            "expires_in": get_settings().access_token_minutes * 60, "user": user_out(user)}


@router.post("/logout", status_code=204)
def logout(body: RefreshIn, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> Response:
    revoke_refresh(s, body.refresh_token)
    audit(s, "auth.logout", user_id=user.id)
    s.commit()
    return Response(status_code=204)


class MeUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    locale: str | None = Field(default=None, pattern="^(ru|en)$")


@router.get("/me")
def me(user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    rows = s.execute(select(m.Workspace, m.Membership.role).join(m.Membership, m.Membership.workspace_id ==
                                                                   m.Workspace.id)
                     .where(m.Membership.user_id == user.id).order_by(m.Membership.created_at)).all()
    return {"user": user_out(user),
            "workspaces": [{"id": w.id, "name": w.name, "role": r, "timezone": w.timezone} for w, r in rows]}


@router.patch("/me")
def update_me(body: MeUpdate, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    u = s.get(m.User, user.id)
    if body.display_name is not None:
        u.display_name = body.display_name
    if body.locale is not None:
        u.locale = body.locale
    s.commit()
    return user_out(u)
