"""CI/CD integration: API tokens, CI run API (archive upload or allowlisted git URL), reports, YAML, CLI download."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.api.projects import store_upload
from app.api.runs import EXPORTS, _findings
from app.api.workflows import start_run
from app.ci.yaml_generator import github_actions, gitlab_ci
from app.config import REPO_ROOT, get_settings
from app.core.audit import audit
from app.core.errors import ApiError, bad_request, forbidden, not_found, unauthorized
from app.core.repo_guard import RepoGuardError, check_git_url, check_ref
from app.core.security import hash_token, new_api_token
from app.db import get_db
from app.deps import bearer, client_ip, current_user, get_session, load_scoped, resolve_workspace
from app.engine.services import allowlist_for
from app.export.submission_json import OFFICIAL_MIN_CONFIDENCE
from app.nodes.output.report_export import build_reports

router = APIRouter(tags=["ci"])
TERMINAL = {"success", "failed", "cancelled"}


# ---- API tokens -----------------------------------------------------------------------------------------------
class TokenIn(BaseModel):
    workspace_id: str | None = None
    name: str = Field(min_length=1, max_length=200)
    workflow_id: str | None = None


def token_out(t: m.ApiToken) -> dict:
    return {"id": t.id, "name": t.name, "prefix": t.prefix, "workflow_id": t.workflow_id, "created_at": t.created_at,
            "last_used_at": t.last_used_at, "revoked": t.revoked_at is not None}


@router.get("/api-tokens")
def list_tokens(workspace_id: str | None = None, user: m.User = Depends(current_user),
                s: Session = Depends(get_session)) -> list[dict]:
    ws = resolve_workspace(s, user, workspace_id, "developer")
    return [token_out(t) for t in s.scalars(select(m.ApiToken).where(m.ApiToken.workspace_id == ws)
                                            .order_by(m.ApiToken.created_at.desc()))]


@router.post("/api-tokens", status_code=201)
def create_token(body: TokenIn, request: Request, user: m.User = Depends(current_user),
                 s: Session = Depends(get_session)) -> dict:
    ws = resolve_workspace(s, user, body.workspace_id, "admin")
    if body.workflow_id:
        wf = s.get(m.Workflow, body.workflow_id)
        if wf is None or wf.workspace_id != ws:
            raise bad_request("сценарий не найден в этом рабочем пространстве")
    raw, hashed, prefix = new_api_token()
    t = m.ApiToken(workspace_id=ws, name=body.name, token_hash=hashed, prefix=prefix, workflow_id=body.workflow_id,
                   created_by=user.id)
    s.add(t)
    audit(s, "api_token.create", user_id=user.id, workspace_id=ws, target=body.name,
          details={"workflow_id": body.workflow_id, "prefix": prefix}, ip=client_ip(request))
    s.commit()
    return {**token_out(t), "token": raw}


@router.delete("/api-tokens/{token_id}", status_code=204)
def revoke_token(token_id: str, request: Request, user: m.User = Depends(current_user),
                 s: Session = Depends(get_session)) -> Response:
    t = load_scoped(s, m.ApiToken, token_id, user, "admin", "токен")
    t.revoked_at = datetime.now(UTC)
    audit(s, "api_token.revoke", user_id=user.id, workspace_id=t.workspace_id, target=t.name, ip=client_ip(request))
    s.commit()
    return Response(status_code=204)


def ci_token(request: Request, s: Session = Depends(get_session)) -> m.ApiToken:
    raw = bearer(request)
    if not raw or not raw.startswith("aisw_"):
        raise unauthorized("нужен API-токен платформы (Authorization: Bearer aisw_…)", "invalid_token")
    t = s.scalars(select(m.ApiToken).where(m.ApiToken.token_hash == hash_token(raw))).first()
    if t is None or t.revoked_at is not None:
        raise unauthorized("API-токен недействителен или отозван", "invalid_token")
    t.last_used_at = datetime.now(UTC)
    s.commit()
    return t


def _workflow_for(s: Session, tok: m.ApiToken, workflow_id: str) -> m.Workflow:
    wf = s.get(m.Workflow, workflow_id)
    if wf is None or wf.workspace_id != tok.workspace_id:
        raise not_found("сценарий")
    if tok.workflow_id and tok.workflow_id != wf.id:
        raise forbidden("токен ограничен другим сценарием")
    return wf


def _source_is_dynamic(wf: m.Workflow) -> bool:
    nodes = [n for n in (wf.graph or {}).get("nodes", []) if n.get("type") == "source.repo"]
    return bool(nodes) and all((n.get("config") or {}).get("mode", "project") == "project" for n in nodes)


def _trigger_node(wf: m.Workflow) -> str | None:
    nodes = (wf.graph or {}).get("nodes", [])
    for t in ("trigger.webhook", "trigger.manual"):
        for n in nodes:
            if n.get("type") == t and not n.get("disabled"):
                return n["id"]
    return None


def links(run_id: str) -> dict:
    base = get_settings().public_url.rstrip("/")
    return {"status": f"/api/v1/ci/runs/{run_id}", "report": f"/api/v1/ci/runs/{run_id}/report",
            "verdict": f"/api/v1/ci/runs/{run_id}/verdict", "ui": f"{base}/runs/{run_id}"}


# ---- CI runs ---------------------------------------------------------------------------------------------------
@router.post("/v1/ci/runs", status_code=202)
async def ci_create_run(request: Request, archive: UploadFile | None = File(default=None),
                        workflow_id: str | None = Form(default=None), provider: str = Form(default="ci"),
                        repo: str = Form(default=""), ref: str = Form(default=""), commit_sha: str = Form(default=""),
                        pr: str = Form(default=""), git_url: str = Form(default=""),
                        diff_context: str = Form(default=""), tok: m.ApiToken = Depends(ci_token),
                        s: Session = Depends(get_session)) -> dict:
    if not workflow_id:
        raise bad_request("укажите workflow_id")
    wf = _workflow_for(s, tok, workflow_id)
    if not _source_is_dynamic(wf):
        raise ApiError(422, "fixed_source", "в сценарии источник кода зафиксирован: для CI выберите в ноде "
                                            "«Исходный код» режим project")
    if archive is not None:
        data = await archive.read(get_settings().upload_max_bytes + 1)
        up = store_upload(s, wf.workspace_id, None, archive.filename or "ci.zip", data)
        source = {"mode": "upload", "upload_id": up.id}
    elif git_url:
        try:
            source = {"mode": "git_url", "git_url": check_git_url(git_url, allowlist_for(s, wf.workspace_id))}
            if ref:
                source["ref"] = check_ref(ref)
        except RepoGuardError as exc:
            raise ApiError(422, "source_not_allowed", str(exc)) from exc
    else:
        raise bad_request("передайте архив кода (archive) или git_url из allowlist")
    try:
        diff = json.loads(diff_context) if diff_context else None
    except ValueError as exc:
        raise bad_request("diff_context должен быть JSON") from exc
    payload = {"source": source, "provider": provider, "repo": repo[:200], "ref": ref[:200], "head_sha": commit_sha[:64],
               "pr_number": pr[:20], "diff_context": diff, "api_token": tok.prefix}
    run = start_run(s, wf, None, "ci", trigger_node_id=_trigger_node(wf), payload=payload)
    audit(s, "ci.run", workspace_id=wf.workspace_id, target=wf.name, details={"run_id": run.id, "provider": provider,
                                                                              "token": tok.prefix},
          ip=client_ip(request))
    s.commit()
    return {"id": run.id, "status": run.status, "links": links(run.id)}


def gate_of(run: m.Run) -> str | None:
    if run.status != "success":
        return None
    if run.gate:
        return run.gate
    return "fail" if (run.summary or {}).get("by_severity", {}).get("CRITICAL") else "pass"


def ci_status_out(run: m.Run) -> dict:
    return {"id": run.id, "status": run.status, "gate": gate_of(run), "verdict": run.verdict, "error": run.error,
            "summary": run.summary or {}, "score": run.score, "score_delta": run.score_delta, "links": links(run.id),
            "finished_at": run.finished_at}


def _ci_run(s: Session, tok: m.ApiToken, run_id: str) -> m.Run:
    run = s.get(m.Run, run_id)
    if run is None or run.workspace_id != tok.workspace_id or (tok.workflow_id and run.workflow_id != tok.workflow_id):
        raise not_found("запуск")
    return run


@router.get("/v1/ci/runs/{run_id}")
async def ci_run_status(run_id: str, wait: float = 0, tok: m.ApiToken = Depends(ci_token),
                        s: Session = Depends(get_session)) -> dict:
    run = _ci_run(s, tok, run_id)
    deadline = asyncio.get_running_loop().time() + min(max(wait, 0), 30)
    while run.status not in TERMINAL and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.5)
        with get_db().session() as ss:
            run = ss.get(m.Run, run_id)
    return ci_status_out(run)


@router.get("/v1/ci/runs/{run_id}/verdict")
def ci_run_verdict(run_id: str, tok: m.ApiToken = Depends(ci_token), s: Session = Depends(get_session)) -> JSONResponse:
    """HTTP 200 = PASS, 422 = FAIL (only new findings block when a diff-aware node ran; otherwise the gate)."""
    run = _ci_run(s, tok, run_id)
    if run.status not in TERMINAL:
        raise ApiError(409, "run_not_finished", "запуск ещё не завершён", {"status": run.status})
    if run.status != "success":
        raise ApiError(409, "run_failed", f"запуск завершился со статусом {run.status}", {"error": run.error})
    findings = _findings(s, run.id)
    v = dict(run.verdict or {})
    if v.get("verdict") not in ("PASS", "FAIL"):
        v = {"verdict": "FAIL" if gate_of(run) == "fail" else "PASS", "diff_available": False,
             "existing_count": 0, "basis": "gate"}
    new = [f for f in findings if f.diff_status == "new"] if v.get("diff_available") else []
    body = {**v, "new_findings": [{"id": f.id, "category": f.category, "class": f.cls, "severity": f.severity,
                                   "title": f.title, "path": f.path, "line": f.line, "end_line": f.end_line,
                                   "snippet": f.snippet, "advisory_id": f.advisory_id,
                                   "introduced_in_commit": f.introduced_in_commit} for f in new],
            "links": links(run.id)}
    return JSONResponse(jsonable_encoder(body), status_code=200 if v["verdict"] == "PASS" else 422)


@router.get("/v1/ci/runs/{run_id}/report")
def ci_run_report(run_id: str, format: str = "json", tok: m.ApiToken = Depends(ci_token),  # noqa: A002
                  s: Session = Depends(get_session)):
    run = _ci_run(s, tok, run_id)
    if run.status not in TERMINAL:
        raise ApiError(409, "run_not_finished", "запуск ещё выполняется")
    findings = _findings(s, run.id)
    if format == "json":
        return {**ci_status_out(run), "findings": [f.model_dump(by_alias=True, mode="json", exclude_none=True)
                                                   for f in findings if f.confidence >= OFFICIAL_MIN_CONFIDENCE]}
    key = {"submission": "submission.json", "markdown": "report.md", "html": "report.html"}.get(format)
    if key is None:
        raise bad_request("format: json | submission | markdown | html")
    wf = s.get(m.Workflow, run.workflow_id) if run.workflow_id else None
    reports = build_reports(findings, wf.name if wf else "project", OFFICIAL_MIN_CONFIDENCE, False, None,
                            {"Запуск": run.id})
    kind, ctype = EXPORTS[key]
    if kind == "submission_json":
        return JSONResponse(json.loads(reports[kind]))
    return PlainTextResponse(reports[kind], media_type=ctype)


# ---- YAML + CLI ------------------------------------------------------------------------------------------------
@router.get("/ci/yaml")
def ci_yaml(provider: str, workflow_id: str, branches: str = "main", user: m.User = Depends(current_user),
            s: Session = Depends(get_session)):
    wf = load_scoped(s, m.Workflow, workflow_id, user, what="сценарий")
    if provider == "github":
        text = github_actions(wf.id, [b.strip() for b in branches.split(",") if b.strip()])
    elif provider == "gitlab":
        text = gitlab_ci(wf.id)
    else:
        raise bad_request("provider: github | gitlab")
    return PlainTextResponse(text, media_type="text/yaml; charset=utf-8")


@router.get("/ci/cli")
def ci_cli() -> FileResponse:
    return FileResponse(REPO_ROOT / "cli" / "aisw_ci.py", media_type="text/x-python", filename="aisw_ci.py")


# ---- Webhook / status-check health -----------------------------------------------------------------------------
@router.get("/ci/webhooks/status")
def webhook_status(workspace_id: str | None = None, limit: int = 20, user: m.User = Depends(current_user),
                   s: Session = Depends(get_session)) -> dict:
    """Recent webhook deliveries and statuses/comments written back to GitHub/GitLab for this workspace."""
    ws = resolve_workspace(s, user, workspace_id, "viewer")
    limit = max(1, min(limit, 100))
    deliveries = s.scalars(select(m.WebhookDelivery).where(m.WebhookDelivery.workspace_id == ws)
                           .order_by(m.WebhookDelivery.created_at.desc()).limit(limit))
    statuses = s.scalars(select(m.CiStatusReport).join(m.Run, m.Run.id == m.CiStatusReport.run_id)
                         .where(m.Run.workspace_id == ws)
                         .order_by(m.CiStatusReport.created_at.desc()).limit(limit))
    return {
        "deliveries": [{"id": d.id, "provider": d.provider, "event": d.event, "delivery_id": d.delivery_id[:40],
                        "run_ids": d.run_ids, "created_at": d.created_at} for d in deliveries],
        "statuses": [{"id": r.id, "run_id": r.run_id, "provider": r.provider, "kind": r.kind, "state": r.state,
                      "target": r.target, "response_code": r.response_code, "error": r.error,
                      "created_at": r.created_at} for r in statuses],
    }
