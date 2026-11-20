from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.config import get_settings
from app.core.audit import audit
from app.core.crypto import get_box
from app.core.errors import ApiError, bad_request
from app.core.repo_guard import RepoGuardError, check_git_url, check_ref, check_scan_path
from app.deps import client_ip, current_user, get_session, load_scoped, resolve_workspace
from app.engine.services import allowlist_for

router = APIRouter(tags=["projects"])
ARCHIVE_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")


class ProjectIn(BaseModel):
    workspace_id: str | None = None
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    source_mode: str = Field(default="upload", pattern="^(upload|git_url|path)$")
    git_url: str | None = Field(default=None, max_length=500)
    ref: str | None = Field(default=None, max_length=200)
    path: str | None = Field(default=None, max_length=1000)
    subdir: str | None = Field(default=None, max_length=500)
    upload_id: str | None = None


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    source_mode: str | None = Field(default=None, pattern="^(upload|git_url|path)$")
    git_url: str | None = Field(default=None, max_length=500)
    ref: str | None = Field(default=None, max_length=200)
    path: str | None = Field(default=None, max_length=1000)
    subdir: str | None = Field(default=None, max_length=500)
    upload_id: str | None = None


def project_out(p: m.Project) -> dict:
    return {"id": p.id, "workspace_id": p.workspace_id, "name": p.name, "description": p.description,
            "source_mode": p.source_mode, "git_url": p.git_url, "ref": p.ref, "path": p.path, "subdir": p.subdir,
            "upload_id": p.upload_id, "created_at": p.created_at}


def check_source(s: Session, ws: str, p: m.Project) -> None:
    try:
        if p.source_mode == "git_url":
            if not p.git_url:
                raise bad_request("укажите git_url")
            p.git_url = check_git_url(p.git_url, allowlist_for(s, ws))
        elif p.source_mode == "path":
            check_scan_path(p.path or "", get_settings().scan_root_paths())
        elif p.source_mode == "upload" and p.upload_id:
            up = s.get(m.Upload, p.upload_id)
            if up is None or up.workspace_id != ws:
                raise bad_request("архив не найден")
        if p.ref:
            check_ref(p.ref)
    except RepoGuardError as exc:
        raise ApiError(422, "source_not_allowed", str(exc)) from exc


@router.get("/projects")
def list_projects(workspace_id: str | None = None, user: m.User = Depends(current_user),
                  s: Session = Depends(get_session)) -> list[dict]:
    ws = resolve_workspace(s, user, workspace_id)
    return [project_out(p) for p in s.scalars(select(m.Project).where(m.Project.workspace_id == ws)
                                              .order_by(m.Project.created_at.desc()))]


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    ws = resolve_workspace(s, user, body.workspace_id, "developer")
    p = m.Project(workspace_id=ws, **body.model_dump(exclude={"workspace_id"}))
    check_source(s, ws, p)
    s.add(p)
    s.commit()
    return project_out(p)


@router.get("/projects/{project_id}")
def get_project(project_id: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    return project_out(load_scoped(s, m.Project, project_id, user, what="проект"))


@router.patch("/projects/{project_id}")
def patch_project(project_id: str, body: ProjectPatch, user: m.User = Depends(current_user),
                  s: Session = Depends(get_session)) -> dict:
    p = load_scoped(s, m.Project, project_id, user, "developer", "проект")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    check_source(s, p.workspace_id, p)
    s.commit()
    return project_out(p)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> Response:
    p = load_scoped(s, m.Project, project_id, user, "developer", "проект")
    s.delete(p)
    s.commit()
    return Response(status_code=204)


def store_upload(s: Session, ws: str, user_id: str | None, filename: str, data: bytes) -> m.Upload:
    settings = get_settings()
    if not filename.lower().endswith(ARCHIVE_SUFFIXES):
        raise bad_request("поддерживаются архивы .zip, .tar, .tar.gz, .tgz", "unsupported_archive")
    if len(data) > settings.upload_max_bytes:
        raise ApiError(413, "payload_too_large", "архив слишком большой")
    up = m.Upload(workspace_id=ws, filename=filename[-300:], stored_path="", size=len(data),
                  sha256=hashlib.sha256(data).hexdigest(), encrypted=True, created_by=user_id,
                  expires_at=datetime.now(UTC) + timedelta(hours=settings.upload_retention_hours))
    s.add(up)
    s.flush()
    d = settings.data_dir / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{up.id}.bin"
    path.write_bytes(get_box().encrypt_bytes(data))
    up.stored_path = str(path)
    return up


@router.post("/uploads", status_code=201)
async def upload(request: Request, file: UploadFile = File(...), workspace_id: str | None = Form(default=None),
                 user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    ws = resolve_workspace(s, user, workspace_id, "developer")
    limit = get_settings().upload_max_bytes
    data = await file.read(limit + 1)
    up = store_upload(s, ws, user.id, file.filename or "upload.zip", data)
    audit(s, "upload.create", user_id=user.id, workspace_id=ws, target=up.filename, details={"size": up.size},
          ip=client_ip(request))
    s.commit()
    return {"id": up.id, "filename": up.filename, "size": up.size, "sha256": up.sha256, "expires_at": up.expires_at}
