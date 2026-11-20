from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.config import get_settings
from app.core.audit import audit
from app.core.errors import ApiError, bad_request
from app.core.repo_guard import RepoGuardError, check_git_url, is_readonly_repo, normalize_repo_url
from app.deps import client_ip, current_user, get_session, resolve_workspace

router = APIRouter(prefix="/settings", tags=["settings"])


class AllowEntry(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    allow_write: bool = False
    provider: str = Field(default="github", pattern="^(github|gitlab)$")
    api_base: str | None = Field(default=None, max_length=500)
    write_credential_id: str | None = None


class AllowlistIn(BaseModel):
    workspace_id: str | None = None
    entries: list[AllowEntry] = Field(default_factory=list, max_length=200)


def allow_out(s: Session, ws: str) -> dict:
    platform = [u.strip() for u in get_settings().default_allowlist.split(",") if u.strip()]
    rows = s.scalars(select(m.RepoAllowlist).where(m.RepoAllowlist.workspace_id == ws)
                     .order_by(m.RepoAllowlist.created_at)).all()
    return {"platform": [{"url": u, "allow_write": False, "readonly": True} for u in platform],
            "entries": [{"id": r.id, "url": r.url, "allow_write": r.allow_write, "provider": r.provider,
                         "api_base": r.api_base, "write_credential_id": r.write_credential_id,
                         "readonly": is_readonly_repo(r.url)} for r in rows]}


@router.get("/allowlist")
def get_allowlist(workspace_id: str | None = None, user: m.User = Depends(current_user),
                  s: Session = Depends(get_session)) -> dict:
    return allow_out(s, resolve_workspace(s, user, workspace_id))


@router.put("/allowlist")
def put_allowlist(body: AllowlistIn, request: Request, user: m.User = Depends(current_user),
                  s: Session = Depends(get_session)) -> dict:
    ws = resolve_workspace(s, user, body.workspace_id, "admin")
    seen: set[str] = set()
    for e in body.entries:
        try:
            norm = check_git_url(e.url, [e.url])  # https, no credentials/query; normalized form
        except RepoGuardError as exc:
            raise bad_request(str(exc), "invalid_repo_url") from exc
        if e.allow_write and is_readonly_repo(norm):
            raise ApiError(403, "readonly_repository",
                           "репозиторий организаторов и тестовые фикстуры доступны только для чтения")
        if e.write_credential_id:
            cred = s.get(m.Credential, e.write_credential_id)
            if cred is None or cred.workspace_id != ws:
                raise bad_request("секрет для записи не найден")
        if norm in seen:
            raise bad_request(f"повтор в списке: {norm}")
        seen.add(norm)
    old = {r.url: r for r in s.scalars(select(m.RepoAllowlist).where(m.RepoAllowlist.workspace_id == ws))}
    for url, r in old.items():
        if url not in seen:
            s.delete(r)
            audit(s, "allowlist.remove", user_id=user.id, workspace_id=ws, target=url, ip=client_ip(request))
    s.flush()
    for e in body.entries:
        norm = normalize_repo_url(e.url)
        r = old.get(norm)
        if r is None:
            r = m.RepoAllowlist(workspace_id=ws, url=norm, created_by=user.id)
            s.add(r)
            audit(s, "allowlist.add", user_id=user.id, workspace_id=ws, target=norm,
                  details={"allow_write": e.allow_write}, ip=client_ip(request))
        elif r.allow_write != e.allow_write:
            audit(s, "allowlist.write_flag", user_id=user.id, workspace_id=ws, target=norm,
                  details={"allow_write": e.allow_write}, ip=client_ip(request))
        r.allow_write, r.provider, r.api_base = e.allow_write, e.provider, e.api_base
        r.write_credential_id = e.write_credential_id
    s.commit()
    return allow_out(s, ws)
