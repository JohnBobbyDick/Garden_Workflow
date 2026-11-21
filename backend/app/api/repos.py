"""«Это учебный / собственный проект» (variant A of the workspace redesign): a person confirms that a public
repository is theirs or a training one, and it is added to the workspace allowlist (read-only) with an audit record.

Cloning still requires the allowlist (``clone_repo``); this endpoint is only the confirmed way onto it. Hosts that
resolve into private/loopback networks are refused, so the confirmation cannot be used to reach internal systems."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.core.audit import audit
from app.core.errors import ApiError
from app.core.repo_guard import RepoGuardError, is_readonly_repo, normalize_user_repo_url
from app.core.ssrf import SSRFError, check_url
from app.deps import client_ip, current_user, get_session, resolve_workspace

router = APIRouter(tags=["repos"])
RESOLVER = None  # tests substitute a fake DNS
CONFIRMATION = "учебный или собственный проект — проверка разрешена"


class AttestIn(BaseModel):
    workspace_id: str | None = None
    url: str = Field(max_length=500)
    confirm: bool = False


@router.post("/repos/attest")
def attest_repo(body: AttestIn, request: Request, user: m.User = Depends(current_user),
                s: Session = Depends(get_session)) -> dict:
    ws = resolve_workspace(s, user, body.workspace_id, "developer")
    if not body.confirm:
        raise ApiError(422, "confirmation_required", "подтвердите, что это учебный или собственный проект")
    try:
        url, ref, subdir = normalize_user_repo_url(body.url)
    except RepoGuardError as exc:
        raise ApiError(422, "invalid_repo_url", str(exc)) from exc
    try:
        check_url(url + "/", set(), RESOLVER)
    except SSRFError as exc:
        raise ApiError(422, "private_host", "адрес репозитория указывает во внутреннюю сеть — такой репозиторий "
                                            "проверить нельзя") from exc
    exists = s.scalars(select(m.RepoAllowlist).where(m.RepoAllowlist.workspace_id == ws,
                                                     m.RepoAllowlist.url == url)).first()
    if exists is None:
        s.add(m.RepoAllowlist(workspace_id=ws, url=url, allow_write=False, created_by=user.id))
    audit(s, "repo.attest", user_id=user.id, workspace_id=ws, target=url,
          details={"confirmation": CONFIRMATION, "ref": ref, "subdir": subdir, "added": exists is None}, ip=client_ip(request))
    s.commit()
    return {"url": url, "ref": ref, "subdir": subdir, "readonly": is_readonly_repo(url)}
