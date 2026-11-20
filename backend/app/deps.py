"""FastAPI dependencies: DB session, current user, workspace membership/role checks (no IDOR)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.core.errors import forbidden, not_found, unauthorized
from app.core.security import decode_access_token
from app.db import get_db

ROLE_RANK = {"viewer": 1, "developer": 2, "admin": 3}


def get_session() -> Iterator[Session]:
    with get_db().session() as s:
        yield s


def bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def current_user(request: Request, s: Session = Depends(get_session)) -> m.User:
    token = bearer(request)
    if not token:
        raise unauthorized()
    user_id = decode_access_token(token)
    if user_id is None:
        raise unauthorized("токен недействителен или истёк", "invalid_token")
    user = s.get(m.User, user_id)
    if user is None or not user.is_active:
        raise unauthorized("пользователь не найден или отключён", "invalid_token")
    return user


def membership(s: Session, user: m.User, workspace_id: str) -> m.Membership | None:
    return s.scalars(select(m.Membership).where(m.Membership.workspace_id == workspace_id,
                                                m.Membership.user_id == user.id)).first()


def require_role(s: Session, user: m.User, workspace_id: str | None, role: str = "viewer") -> m.Membership:
    """Non-members get 404 (existence is not revealed); members with a lower role get 403."""
    if not workspace_id:
        raise not_found("рабочее пространство")
    mem = membership(s, user, workspace_id)
    if mem is None:
        raise not_found("рабочее пространство")
    if ROLE_RANK.get(mem.role, 0) < ROLE_RANK[role]:
        raise forbidden(f"нужна роль {role} или выше")
    return mem


def resolve_workspace(s: Session, user: m.User, workspace_id: str | None, role: str = "viewer") -> str:
    if workspace_id:
        require_role(s, user, workspace_id, role)
        return workspace_id
    mem = s.scalars(select(m.Membership).where(m.Membership.user_id == user.id)
                    .order_by(m.Membership.created_at)).first()
    if mem is None:
        raise not_found("рабочее пространство")
    if ROLE_RANK.get(mem.role, 0) < ROLE_RANK[role]:
        raise forbidden(f"нужна роль {role} или выше")
    return mem.workspace_id


def load_scoped[T](s: Session, model: type[T], obj_id: str, user: m.User, role: str = "viewer",
                what: str = "объект") -> T:
    obj = s.get(model, obj_id)
    if obj is None:
        raise not_found(what)
    try:
        require_role(s, user, obj.workspace_id, role)  # type: ignore[attr-defined]
    except Exception as exc:
        if getattr(exc, "status", None) == 404:
            raise not_found(what) from exc
        raise
    return obj


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""
