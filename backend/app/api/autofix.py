"""AI AutoFix API (12A.3): generate + validate a fix for one finding, inspect it, download the masked .patch, open a
PR/MR (only for allowlisted repositories with allow_write; organizer repository → 403, enforced in code)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.ai.providers.base import build_provider
from app.ai.settings_service import provider_config_for
from app.api.runs import _findings
from app.autofix.coverage import coverage
from app.autofix.pr.scm import PrError
from app.autofix.pull_request import PrForbidden, create_pr, resolve_target
from app.autofix.service import AutofixError, generate
from app.autofix.source import SourceUnavailable
from app.config import get_settings
from app.core.audit import audit
from app.core.errors import ApiError, not_found
from app.core.masking import Masker
from app.core.repo_guard import RepoGuardError
from app.deps import client_ip, current_user, get_session, load_scoped

router = APIRouter(tags=["autofix"])


def autofix_out(a: m.Autofix, can_pr: bool | None = None, pr_reason: str | None = None) -> dict:
    return {"id": a.id, "run_id": a.run_id, "finding_id": a.finding_id, "kind": a.kind, "status": a.status,
            "reason": a.reason, "provider": a.provider, "model": a.model, "proposal": a.proposal, "steps": a.steps,
            "patch": a.patch, "pr_url": a.pr_url, "created_at": a.created_at, "can_create_pr": can_pr,
            "pr_unavailable_reason": pr_reason}


def _pr_availability(s: Session, run: m.Run, a: m.Autofix) -> tuple[bool, str | None]:
    if a.status != "validated":
        return False, "PR можно создать только из проверенного (validated) исправления"
    try:
        resolve_target(s, run)
    except PrForbidden as exc:
        return False, str(exc)
    return True, None


def _finding(s: Session, run: m.Run, fid: str):  # noqa: ANN202
    f = next((x for x in _findings(s, run.id) if x.id == fid), None)
    if f is None:
        raise not_found("находка")
    return f


@router.get("/autofix/coverage")
def autofix_coverage(user: m.User = Depends(current_user)) -> dict:
    return coverage()


class AutofixIn(BaseModel):
    language: str | None = Field(default=None, pattern="^(ru|en)$")


@router.post("/runs/{run_id}/findings/{finding_id}/autofix", status_code=201)
async def start_autofix(run_id: str, finding_id: str, request: Request, body: AutofixIn | None = None,
                        user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    run = load_scoped(s, m.Run, run_id, user, "developer", "запуск")
    if run.status != "success":
        raise ApiError(409, "run_not_finished", "AutoFix доступен для успешно завершённого запуска")
    f = _finding(s, run, finding_id)
    masker = Masker()
    cfg = provider_config_for(s, run.workspace_id, None, masker) if f.autofix == "llm" else None
    provider = build_provider(cfg) if cfg is not None else None
    ws = s.get(m.Workspace, run.workspace_id)
    lang = (body.language if body and body.language else None) or (ws.settings or {}).get("language", "ru")
    try:
        out = await generate(s, run, f, provider, lang)
    except AutofixError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from exc
    except RepoGuardError as exc:
        raise ApiError(409, "source_unavailable", str(exc)) from exc
    v = out.validation
    row = m.Autofix(run_id=run.id, finding_id=f.id, kind=out.kind, provider=out.provider, model=out.model,
                    status=v.status, reason=(out.masker or masker).mask(v.reason) if v.reason else None, patch=out.patch or None,
                    proposal=out.stored_proposal(), steps=(out.masker or masker).mask_obj(v.steps),
                    created_by=user.id)
    s.add(row)
    audit(s, "autofix.generate", user_id=user.id, workspace_id=run.workspace_id, target=f"{run.id}:{f.id}",
          details={"status": v.status, "kind": out.kind}, ip=client_ip(request))
    s.commit()
    return autofix_out(row, *_pr_availability(s, run, row))


@router.get("/runs/{run_id}/autofixes")
def list_autofixes(run_id: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> list:
    run = load_scoped(s, m.Run, run_id, user, what="запуск")
    rows = s.scalars(select(m.Autofix).where(m.Autofix.run_id == run.id).order_by(m.Autofix.created_at.desc()))
    return [autofix_out(a) for a in rows]


def _load(s: Session, autofix_id: str, user: m.User, role: str = "viewer") -> tuple[m.Autofix, m.Run]:
    a = s.get(m.Autofix, autofix_id)
    if a is None:
        raise not_found("AutoFix")
    run = load_scoped(s, m.Run, a.run_id, user, role, "AutoFix")
    return a, run


@router.get("/autofixes/{autofix_id}")
def get_autofix(autofix_id: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    a, run = _load(s, autofix_id, user)
    return autofix_out(a, *_pr_availability(s, run, a))


@router.get("/autofixes/{autofix_id}/patch")
def download_patch(autofix_id: str, user: m.User = Depends(current_user),
                   s: Session = Depends(get_session)) -> PlainTextResponse:
    a, _ = _load(s, autofix_id, user)
    if not a.patch:
        raise ApiError(409, "no_patch", "у исправления нет патча (не прошло валидацию)")
    return PlainTextResponse(a.patch, media_type="text/x-diff", headers={
        "Content-Disposition": f'attachment; filename="autofix-{a.finding_id}.patch"'})


class PrIn(BaseModel):
    target_branch: str | None = Field(default=None, max_length=200)


@router.post("/autofixes/{autofix_id}/pull-request")
async def pull_request(autofix_id: str, request: Request, body: PrIn | None = None,
                       user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    a, run = _load(s, autofix_id, user, "developer")
    if a.status != "validated":
        raise ApiError(409, "not_validated", "PR создаётся только из проверенного (validated) исправления")
    f = _finding(s, run, a.finding_id)
    run_url = f"{get_settings().public_url.rstrip('/')}/runs/{run.id}"
    try:
        res = await create_pr(s, run, a, f, run_url, body.target_branch if body else None)
    except PrForbidden as exc:
        raise ApiError(403, "write_forbidden", str(exc)) from exc
    except (PrError, SourceUnavailable, RepoGuardError, ValueError) as exc:
        raise ApiError(502 if isinstance(exc, PrError) else 409, "pr_failed", Masker().mask(str(exc))) from exc
    a.pr_url = res.url
    audit(s, "autofix.pull_request", user_id=user.id, workspace_id=run.workspace_id, target=a.id,
          details={"url": res.url, "branch": res.branch, "created": res.created}, ip=client_ip(request))
    s.commit()
    return {"url": res.url, "number": res.number, "branch": res.branch, "created": res.created}


@router.post("/autofixes/{autofix_id}/recheck", status_code=202)
def recheck(autofix_id: str, request: Request, user: m.User = Depends(current_user),
            s: Session = Depends(get_session)) -> dict:
    """Apply the validated fix to a copy of the run's sources and run the same workflow (graph snapshot) on it."""
    import copy

    from app.api.projects import store_upload
    from app.autofix.pull_request import patched_archive
    from app.engine import runs as run_service

    a, run = _load(s, autofix_id, user, "developer")
    if a.status != "validated":
        raise ApiError(409, "not_validated", "перепроверить можно только проверенное (validated) исправление")
    f = _finding(s, run, a.finding_id)
    try:
        data = patched_archive(s, run, a, f)
    except (SourceUnavailable, RepoGuardError, ValueError) as exc:
        raise ApiError(409, "source_unavailable", Masker().mask(str(exc))) from exc
    up = store_upload(s, run.workspace_id, user.id, f"autofix-{a.finding_id}.zip", data)
    graph = copy.deepcopy(run.graph_snapshot)
    for node in graph.get("nodes", []):
        if node.get("type") == "source.repo":
            node["config"] = {"mode": "upload", "upload_id": up.id}
    wf = s.get(m.Workflow, run.workflow_id) if run.workflow_id else None
    if wf is None:
        raise ApiError(409, "workflow_missing", "сценарий исходного запуска удалён")
    new = run_service.create_run(s, wf, trigger_type="manual", triggered_by=user.id, trigger_node_id=run.trigger_node_id,
                                 payload={"recheck_of": run.id, "autofix_id": a.id}, project_id=run.project_id,
                                 graph=graph)
    audit(s, "autofix.recheck", user_id=user.id, workspace_id=run.workspace_id, target=a.id,
          details={"run_id": new.id}, ip=client_ip(request))
    s.commit()
    return {"run_id": new.id, "status": new.status}
