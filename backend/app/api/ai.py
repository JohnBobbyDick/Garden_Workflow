from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.ai.providers.base import LLMError, build_provider, provider_names
from app.ai.settings_service import FREE_HINTS, host_port, provider_config_for
from app.core.audit import audit
from app.core.errors import ApiError, bad_request, not_found
from app.core.masking import global_masker
from app.deps import client_ip, current_user, get_session, load_scoped, resolve_workspace

router = APIRouter(tags=["ai"])


class AISettingsIn(BaseModel):
    workspace_id: str | None = None
    enabled: bool = False
    provider: str = Field(default="openai_compat", max_length=32)
    base_url: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=200)
    credential_id: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    timeout: float = Field(default=90, ge=5, le=600)
    json_mode: str = Field(default="auto", pattern="^(auto|schema|object|instruction)$")
    allow_local: bool = False


class WorkspaceRef(BaseModel):
    workspace_id: str | None = None


def settings_out(row: m.AISettings | None) -> dict:
    extra = dict(row.extra or {}) if row else {}
    return {"enabled": bool(row and row.enabled), "provider": row.provider if row else "openai_compat",
            "base_url": row.base_url if row else "", "model": row.model if row else "",
            "credential_id": row.credential_id if row else None, "headers": extra.get("headers", {}),
            "timeout": extra.get("timeout", 90), "json_mode": extra.get("json_mode", "auto"),
            "allow_local": bool(extra.get("allow_host")), "providers": provider_names(), "hints": FREE_HINTS}


@router.get("/settings/ai")
def get_ai_settings(workspace_id: str | None = None, user: m.User = Depends(current_user),
                    s: Session = Depends(get_session)) -> dict:
    ws = resolve_workspace(s, user, workspace_id)
    return settings_out(s.get(m.AISettings, ws))


@router.put("/settings/ai")
def put_ai_settings(body: AISettingsIn, request: Request, user: m.User = Depends(current_user),
                    s: Session = Depends(get_session)) -> dict:
    ws = resolve_workspace(s, user, body.workspace_id, "admin")
    if body.provider not in provider_names():
        raise bad_request(f"неизвестный провайдер {body.provider}")
    if body.base_url and not body.base_url.startswith(("http://", "https://")):
        raise bad_request("base_url должен начинаться с http:// или https://")
    if body.enabled and not (body.base_url and body.model):
        raise bad_request("для включения AI укажите base_url и модель")
    if body.credential_id:
        cred = s.get(m.Credential, body.credential_id)
        if cred is None or cred.workspace_id != ws:
            raise bad_request("ключ не найден в хранилище этого рабочего пространства")
    for name in body.headers:
        if name.lower() in ("authorization", "host", "content-length"):
            raise bad_request(f"заголовок {name} задаётся платформой; секреты храните в хранилище")
    row = s.get(m.AISettings, ws) or m.AISettings(workspace_id=ws)
    row.enabled, row.provider, row.base_url, row.model = body.enabled, body.provider, body.base_url, body.model
    row.credential_id = body.credential_id
    row.extra = {"headers": body.headers, "timeout": body.timeout, "json_mode": body.json_mode,
                 **({"allow_host": host_port(body.base_url)} if body.allow_local and body.base_url else {})}
    s.add(row)
    audit(s, "ai_settings.update", user_id=user.id, workspace_id=ws, target=body.provider,
          details={"base_url": body.base_url, "model": body.model, "enabled": body.enabled,
                   "allow_local": body.allow_local}, ip=client_ip(request))
    s.commit()
    return settings_out(row)


@router.post("/settings/ai/test")
async def test_ai(body: WorkspaceRef, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    ws = resolve_workspace(s, user, body.workspace_id, "developer")
    masker = global_masker.child()
    try:
        cfg = provider_config_for(s, ws, None, masker, require_enabled=False)
    except LookupError as exc:
        return {"ok": False, "error": str(exc)}
    if cfg is None:
        return {"ok": False, "error": "AI-провайдер не настроен: укажите base_url и модель"}
    provider = build_provider(cfg)
    started = time.monotonic()
    models: list[str] = []
    try:
        try:
            models = await provider.list_models()
        except LLMError:
            models = []
        res = await provider.chat([{"role": "user", "content": 'Верни JSON {"ok": true}'}],
                                  response_schema={"type": "object", "properties": {"ok": {"type": "boolean"}},
                                                   "required": ["ok"]}, max_tokens=20, timeout=min(cfg.timeout, 60))
        return {"ok": True, "model": res.model, "json_mode": res.json_mode, "models": models,
                "latency_ms": int((time.monotonic() - started) * 1000), "reply": masker.mask(res.content[:200])}
    except LLMError as exc:
        return {"ok": False, "error": masker.mask(str(exc)), "models": models}


@router.get("/settings/ai/models")
async def ai_models(workspace_id: str | None = None, user: m.User = Depends(current_user),
                    s: Session = Depends(get_session)) -> dict:
    ws = resolve_workspace(s, user, workspace_id)
    cfg = provider_config_for(s, ws, None, global_masker.child(), require_enabled=False)
    if cfg is None:
        return {"models": []}
    try:
        return {"models": await build_provider(cfg).list_models()}
    except LLMError as exc:
        return {"models": [], "error": global_masker.mask(str(exc))}


def ai_report_out(r: m.AIReport) -> dict:
    return {"id": r.id, "run_id": r.run_id, "node_id": r.node_id, "kind": r.kind, "provider": r.provider,
            "model": r.model, "language": r.language, "ai_generated": r.ai_generated, "report": r.report,
            "validation": {k: v for k, v in (r.validation or {}).items() if k != "error"},
            "error": (r.validation or {}).get("error"), "metrics": r.metrics, "usage": r.usage,
            "created_at": r.created_at}


@router.get("/runs/{run_id}/ai-report")
def get_ai_report(run_id: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    run = load_scoped(s, m.Run, run_id, user, what="запуск")
    row = s.scalars(select(m.AIReport).where(m.AIReport.run_id == run.id, m.AIReport.kind == "report")
                    .order_by(m.AIReport.created_at.desc())).first()
    if row is None:
        raise not_found("AI-отчёт")
    return ai_report_out(row)


# ---- AI workflow generation and chat editing (12.3) -------------------------------------------------------------
class GenerateIn(BaseModel):
    workspace_id: str | None = None
    prompt: str = Field(min_length=3, max_length=4000)
    create: bool = False
    name: str | None = Field(default=None, max_length=200)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


def _provider_or_400(s: Session, ws: str, masker):  # noqa: ANN001, ANN202
    cfg = provider_config_for(s, ws, None, masker)
    if cfg is None:
        raise ApiError(400, "ai_not_configured", "AI-провайдер не настроен: Настройки → AI-провайдер")
    return build_provider(cfg)


def _cred_checker(s: Session, ws: str):  # noqa: ANN202
    ids = set(s.scalars(select(m.Credential.id).where(m.Credential.workspace_id == ws)))
    return lambda c: c in ids


@router.post("/ai/workflows/generate")
async def ai_generate(body: GenerateIn, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    from app.ai.workflow_gen import generate_graph
    from app.engine.scheduler import sync_schedules
    from app.nodes.base import get_registry

    ws = resolve_workspace(s, user, body.workspace_id, "developer")
    masker = global_masker.child()
    provider = _provider_or_400(s, ws, masker)
    try:
        res = await generate_graph(provider, body.prompt, get_registry(), _cred_checker(s, ws), masker)
    except LLMError as exc:
        raise ApiError(502, "ai_error", masker.mask(str(exc))) from exc
    out = {"graph": res.graph, "issues": res.issues, "needs_input": res.needs_input, "attempts": res.attempts,
           "valid": res.valid, "usage": res.usage}
    if not res.valid:
        raise ApiError(422, "generation_failed", "не удалось получить корректный граф за 3 попытки — ничего не применено",
                       out)
    if body.create:
        wf = m.Workflow(workspace_id=ws, name=body.name or body.prompt[:80], description=body.prompt, graph=res.graph,
                        created_by=user.id)
        s.add(wf)
        s.flush()
        sync_schedules(s, wf)
        s.add(m.WorkflowChatMessage(workflow_id=wf.id, user_id=user.id, role="user", content=body.prompt,
                                    status="applied"))
        s.commit()
        out["workflow_id"] = wf.id
    return out


def chat_out(msg: m.WorkflowChatMessage) -> dict:
    return {"id": msg.id, "role": msg.role, "content": msg.content, "operations": msg.operations, "status": msg.status,
            "created_at": msg.created_at}


@router.get("/ai/workflows/{workflow_id}/chat")
def ai_chat_history(workflow_id: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> list[dict]:
    wf = load_scoped(s, m.Workflow, workflow_id, user, what="сценарий")
    rows = s.scalars(select(m.WorkflowChatMessage).where(m.WorkflowChatMessage.workflow_id == wf.id)
                     .order_by(m.WorkflowChatMessage.created_at))
    return [chat_out(r) for r in rows if r.content or r.role == "assistant"][-200:]


@router.post("/ai/workflows/{workflow_id}/chat")
async def ai_chat(workflow_id: str, body: ChatIn, user: m.User = Depends(current_user),
                  s: Session = Depends(get_session)) -> dict:
    from app.ai.workflow_gen import (
        OpError,
        apply_operations,
        blocking_issues,
        graph_diff,
        propose_operations,
        strip_secrets,
    )
    from app.nodes.base import get_registry

    wf = load_scoped(s, m.Workflow, workflow_id, user, "developer", "сценарий")
    masker = global_masker.child()
    provider = _provider_or_400(s, wf.workspace_id, masker)
    reg = get_registry()
    try:
        ops, explanation, _usage = await propose_operations(provider, wf.graph, body.message, reg, masker)
    except LLMError as exc:
        raise ApiError(502, "ai_error", masker.mask(str(exc))) from exc
    except ValueError as exc:
        raise ApiError(502, "ai_bad_answer", masker.mask(str(exc))) from exc
    checker = _cred_checker(s, wf.workspace_id)
    try:
        new_graph = apply_operations(wf.graph, ops, reg)
        needs = strip_secrets(new_graph, reg, checker)
        issues, blocking = blocking_issues(new_graph, reg, checker, needs)
        valid = not blocking
    except OpError as exc:
        new_graph, needs, issues, blocking, valid = wf.graph, [], [{"code": "bad_operation", "message": str(exc),
                                                                     "node_id": None, "field": None}], [], False
    status = "proposed" if valid else "failed"
    user_msg = m.WorkflowChatMessage(workflow_id=wf.id, user_id=user.id, role="user", content=body.message, status=status)
    bot = m.WorkflowChatMessage(workflow_id=wf.id, role="assistant", content=explanation, operations=ops, status=status,
                                result_graph=new_graph if valid else None)
    s.add_all([user_msg, bot])
    s.commit()
    return {**chat_out(bot), "diff": graph_diff(wf.graph, new_graph) if valid else {}, "valid": valid,
            "issues": blocking or issues if not valid else issues, "needs_input": needs, "graph": new_graph,
            "user_message_id": user_msg.id}


def _proposal(s: Session, wf: m.Workflow, msg_id: str) -> tuple[m.WorkflowChatMessage, m.WorkflowChatMessage | None]:
    msg = s.get(m.WorkflowChatMessage, msg_id)
    if msg is None or msg.workflow_id != wf.id or msg.role != "assistant":
        raise not_found("предложение")
    prev = s.scalars(select(m.WorkflowChatMessage).where(m.WorkflowChatMessage.workflow_id == wf.id,
                                                         m.WorkflowChatMessage.role == "user",
                                                         m.WorkflowChatMessage.created_at <= msg.created_at)
                     .order_by(m.WorkflowChatMessage.created_at.desc())).first()
    return msg, prev


@router.post("/ai/workflows/{workflow_id}/chat/{msg_id}/apply")
def ai_chat_apply(workflow_id: str, msg_id: str, user: m.User = Depends(current_user),
                  s: Session = Depends(get_session)) -> dict:
    from app.engine.scheduler import sync_schedules

    wf = load_scoped(s, m.Workflow, workflow_id, user, "developer", "сценарий")
    msg, prev = _proposal(s, wf, msg_id)
    if msg.status != "proposed" or not msg.result_graph:
        raise ApiError(409, "not_applicable", "это предложение нельзя применить")
    wf.graph = msg.result_graph
    wf.version += 1
    sync_schedules(s, wf)
    msg.status = "applied"
    if prev is not None:
        prev.status = "applied"
    s.commit()
    return {"workflow_id": wf.id, "version": wf.version, "graph": wf.graph}


@router.post("/ai/workflows/{workflow_id}/chat/{msg_id}/reject")
def ai_chat_reject(workflow_id: str, msg_id: str, user: m.User = Depends(current_user),
                   s: Session = Depends(get_session)) -> dict:
    wf = load_scoped(s, m.Workflow, workflow_id, user, "developer", "сценарий")
    msg, prev = _proposal(s, wf, msg_id)
    msg.status = "rejected"
    if prev is not None:
        prev.status = "rejected"
    s.commit()
    return {"status": "rejected"}
