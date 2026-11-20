from __future__ import annotations

import secrets
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models as m
from app.core.audit import audit
from app.core.errors import bad_request, conflict, not_found
from app.core.security import hash_token
from app.deps import client_ip, current_user, get_session, require_role

router = APIRouter(tags=["workspaces"])


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    timezone: str = Field(default="Europe/Moscow", max_length=64)


class WorkspacePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = Field(default=None, max_length=64)
    settings: dict | None = None


class MemberIn(BaseModel):
    email: EmailStr
    role: str = Field(default="developer", pattern="^(admin|developer|viewer)$")


class RolePatch(BaseModel):
    role: str = Field(pattern="^(admin|developer|viewer)$")


class AcceptIn(BaseModel):
    token: str = Field(max_length=200)


def _check_tz(tz: str) -> None:
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise bad_request(f"неизвестный часовой пояс {tz}") from exc


def ws_out(w: m.Workspace, role: str | None = None) -> dict:
    return {"id": w.id, "name": w.name, "timezone": w.timezone, "settings": w.settings or {}, "role": role,
            "created_at": w.created_at}


@router.get("/workspaces")
def list_workspaces(user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> list[dict]:
    rows = s.execute(select(m.Workspace, m.Membership.role).join(m.Membership, m.Membership.workspace_id ==
                                                                   m.Workspace.id)
                     .where(m.Membership.user_id == user.id).order_by(m.Membership.created_at)).all()
    return [ws_out(w, r) for w, r in rows]


@router.post("/workspaces", status_code=201)
def create_workspace(body: WorkspaceIn, request: Request, user: m.User = Depends(current_user),
                     s: Session = Depends(get_session)) -> dict:
    _check_tz(body.timezone)
    ws = m.Workspace(name=body.name, timezone=body.timezone)
    s.add(ws)
    s.flush()
    s.add(m.Membership(workspace_id=ws.id, user_id=user.id, role="admin"))
    audit(s, "workspace.create", user_id=user.id, workspace_id=ws.id, target=body.name, ip=client_ip(request))
    s.commit()
    return ws_out(ws, "admin")


@router.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    mem = require_role(s, user, workspace_id)
    return ws_out(s.get(m.Workspace, workspace_id), mem.role)


@router.patch("/workspaces/{workspace_id}")
def patch_workspace(workspace_id: str, body: WorkspacePatch, user: m.User = Depends(current_user),
                    s: Session = Depends(get_session)) -> dict:
    require_role(s, user, workspace_id, "admin")
    ws = s.get(m.Workspace, workspace_id)
    if body.name is not None:
        ws.name = body.name
    if body.timezone is not None:
        _check_tz(body.timezone)
        ws.timezone = body.timezone
    if body.settings is not None:
        ws.settings = {**(ws.settings or {}), **body.settings}
    audit(s, "workspace.update", user_id=user.id, workspace_id=workspace_id, details=body.model_dump(exclude_none=True))
    s.commit()
    return ws_out(ws, "admin")


@router.get("/workspaces/{workspace_id}/members")
def list_members(workspace_id: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    require_role(s, user, workspace_id)
    rows = s.execute(select(m.User, m.Membership.role).join(m.Membership, m.Membership.user_id == m.User.id)
                     .where(m.Membership.workspace_id == workspace_id)).all()
    invites = s.scalars(select(m.Invitation).where(m.Invitation.workspace_id == workspace_id,
                                                   m.Invitation.accepted_at.is_(None))).all()
    return {"members": [{"user_id": u.id, "email": u.email, "display_name": u.display_name, "role": r}
                        for u, r in rows],
            "invitations": [{"id": i.id, "email": i.email, "role": i.role, "created_at": i.created_at}
                            for i in invites]}


@router.post("/workspaces/{workspace_id}/members", status_code=201)
def add_member(workspace_id: str, body: MemberIn, request: Request, user: m.User = Depends(current_user),
               s: Session = Depends(get_session)) -> dict:
    require_role(s, user, workspace_id, "admin")
    email = body.email.lower()
    target = s.scalars(select(m.User).where(m.User.email == email)).first()
    audit(s, "workspace.member_add", user_id=user.id, workspace_id=workspace_id, target=email,
          details={"role": body.role}, ip=client_ip(request))
    if target is not None:
        if s.scalars(select(m.Membership).where(m.Membership.workspace_id == workspace_id,
                                                m.Membership.user_id == target.id)).first():
            raise conflict("пользователь уже участник")
        s.add(m.Membership(workspace_id=workspace_id, user_id=target.id, role=body.role))
        s.commit()
        return {"status": "added", "user_id": target.id, "role": body.role}
    raw = "inv_" + secrets.token_urlsafe(24)
    s.add(m.Invitation(workspace_id=workspace_id, email=email, role=body.role, token_hash=hash_token(raw),
                       created_by=user.id))
    s.commit()
    return {"status": "invited", "email": email, "role": body.role, "invite_token": raw}


@router.post("/invitations/accept")
def accept_invitation(body: AcceptIn, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    inv = s.scalars(select(m.Invitation).where(m.Invitation.token_hash == hash_token(body.token))).first()
    if inv is None or inv.accepted_at is not None or inv.email != user.email:
        raise not_found("приглашение")
    if not s.scalars(select(m.Membership).where(m.Membership.workspace_id == inv.workspace_id,
                                                m.Membership.user_id == user.id)).first():
        s.add(m.Membership(workspace_id=inv.workspace_id, user_id=user.id, role=inv.role))
    inv.accepted_at = datetime.now(UTC)
    audit(s, "workspace.invite_accept", user_id=user.id, workspace_id=inv.workspace_id, target=user.email)
    s.commit()
    return {"workspace_id": inv.workspace_id, "role": inv.role}


def _admins(s: Session, workspace_id: str) -> int:
    return s.scalar(select(func.count()).select_from(m.Membership).where(m.Membership.workspace_id == workspace_id,
                                                                         m.Membership.role == "admin")) or 0


@router.patch("/workspaces/{workspace_id}/members/{user_id}")
def change_role(workspace_id: str, user_id: str, body: RolePatch, user: m.User = Depends(current_user),
                s: Session = Depends(get_session)) -> dict:
    require_role(s, user, workspace_id, "admin")
    mem = s.scalars(select(m.Membership).where(m.Membership.workspace_id == workspace_id,
                                               m.Membership.user_id == user_id)).first()
    if mem is None:
        raise not_found("участник")
    if mem.role == "admin" and body.role != "admin" and _admins(s, workspace_id) <= 1:
        raise bad_request("нельзя понизить последнего администратора", "last_admin")
    mem.role = body.role
    audit(s, "workspace.role_change", user_id=user.id, workspace_id=workspace_id, target=user_id,
          details={"role": body.role})
    s.commit()
    return {"user_id": user_id, "role": body.role}


@router.delete("/workspaces/{workspace_id}/members/{user_id}", status_code=204)
def remove_member(workspace_id: str, user_id: str, user: m.User = Depends(current_user),
                  s: Session = Depends(get_session)) -> Response:
    require_role(s, user, workspace_id, "admin")
    mem = s.scalars(select(m.Membership).where(m.Membership.workspace_id == workspace_id,
                                               m.Membership.user_id == user_id)).first()
    if mem is None:
        raise not_found("участник")
    if mem.role == "admin" and _admins(s, workspace_id) <= 1:
        raise bad_request("нельзя удалить последнего администратора", "last_admin")
    s.delete(mem)
    audit(s, "workspace.member_remove", user_id=user.id, workspace_id=workspace_id, target=user_id)
    s.commit()
    return Response(status_code=204)


@router.get("/workspaces/{workspace_id}/audit")
def get_audit(workspace_id: str, limit: int = 200, user: m.User = Depends(current_user),
              s: Session = Depends(get_session)) -> list[dict]:
    require_role(s, user, workspace_id, "admin")
    rows = s.scalars(select(m.AuditLog).where(m.AuditLog.workspace_id == workspace_id)
                     .order_by(m.AuditLog.created_at.desc()).limit(min(limit, 1000))).all()
    return [{"id": a.id, "action": a.action, "user_id": a.user_id, "target": a.target, "details": a.details,
             "ip": a.ip, "created_at": a.created_at} for a in rows]
