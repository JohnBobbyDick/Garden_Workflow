from __future__ import annotations

import time
from copy import deepcopy
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, load_only

from app import models as m
from app.ai.diagnose import diagnose, probe_chat
from app.ai.pool import NEMOTRON_LIGHTNING, NVIDIA_BASE_URL, canonical_provider, get_llm_env
from app.ai.providers.base import LLMError, build_provider, provider_names
from app.ai.settings_service import FREE_HINTS, env_default_out, host_port, provider_config_for
from app.core.audit import audit
from app.core.errors import ApiError, bad_request, not_found
from app.core.masking import global_masker
from app.deps import client_ip, current_user, get_session, load_scoped, resolve_workspace

router = APIRouter(tags=["ai"])


class AISettingsIn(BaseModel):
    workspace_id: str | None = None
    enabled: bool = False
    provider: str = Field(default="nvidia", max_length=32)
    base_url: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=200)
    credential_id: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    timeout: float = Field(default=90, ge=5, le=600)
    json_mode: str = Field(default="auto", pattern="^(auto|schema|object|instruction)$")
    allow_local: bool = False
    # pool (LLM_PROXY.md): more keys, proxies from the vault, fallback models, attempts
    credential_ids: list[str] = Field(default_factory=list, max_length=20)
    proxy_credential_ids: list[str] = Field(default_factory=list, max_length=50)
    fallback_models: list[str] = Field(default_factory=list, max_length=10)
    proxy_scheme: Literal["auto", "http", "https", "socks5", "socks5h"] = "auto"
    proxy_port: str | None = Field(default=None, pattern=r"^\d{1,5}$")
    max_retries: int | None = Field(default=None, ge=1, le=6)


class WorkspaceRef(BaseModel):
    workspace_id: str | None = None


def settings_out(row: m.AISettings | None) -> dict:
    name = canonical_provider(row.provider, row.base_url, row.model) if row else "nvidia"
    if name is None:
        row = None
    extra = dict(row.extra or {}) if row else {}
    env = get_llm_env()
    return {"enabled": bool(row and row.enabled), "provider": name or "nvidia",
            "requires_reconfiguration": name is None,
            "ollama_defaults": {"base_url": env.ollama_url, "model": env.ollama_model},
            "base_url": row.base_url if name == "ollama" else NVIDIA_BASE_URL,
            "model": row.model if name == "ollama" else NEMOTRON_LIGHTNING,
            "credential_id": row.credential_id if row else None, "headers": extra.get("headers", {}),
            "timeout": extra.get("timeout", 90), "json_mode": extra.get("json_mode", "auto"),
            "allow_local": bool(extra.get("allow_host")), "providers": provider_names(), "hints": FREE_HINTS,
            "credential_ids": list(extra.get("credential_ids") or []),
            "proxy_credential_ids": list(extra.get("proxy_credential_ids") or []),
            "fallback_models": [],
            "proxy_scheme": extra.get("proxy_scheme") or "auto", "proxy_port": extra.get("proxy_port"),
            "max_retries": extra.get("max_retries"), "env_default": env_default_out()}


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
    if body.fallback_models:
        raise bad_request("дополнительные модели для выбранного провайдера не поддерживаются")
    if body.provider == "nvidia":
        if not canonical_provider(body.provider, body.base_url, body.model):
            raise bad_request("Для NVIDIA доступны только NVIDIA Build и Nemotron 3.5 Lightning")
        if not (body.credential_id or body.credential_ids) and (body.headers or body.proxy_credential_ids):
            raise bad_request("Свои заголовки и прокси требуют ключ NVIDIA из хранилища рабочего пространства")
        body.base_url, body.model, body.allow_local = NVIDIA_BASE_URL, NEMOTRON_LIGHTNING, False
    elif body.credential_ids or body.proxy_credential_ids:
        raise bad_request("Пулы ключей и прокси доступны для NVIDIA")
    if body.base_url and not body.base_url.startswith(("http://", "https://")):
        raise bad_request("base_url должен начинаться с http:// или https://")
    if body.base_url:
        from urllib.parse import urlsplit

        try:
            parts = urlsplit(body.base_url)
            host_port(body.base_url)
            if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
                raise ValueError
        except ValueError:
            raise bad_request("Некорректный адрес сервера AI") from None
    if body.enabled and not (body.base_url and body.model):
        raise bad_request("для включения AI укажите base_url и модель")
    for cid in [c for c in [body.credential_id, *body.credential_ids] if c]:
        cred = s.get(m.Credential, cid)
        if cred is None or cred.workspace_id != ws:
            raise bad_request("ключ не найден в хранилище этого рабочего пространства")
    for cid in body.proxy_credential_ids:
        cred = s.get(m.Credential, cid)
        if cred is None or cred.workspace_id != ws or cred.kind != "proxy":
            raise bad_request("прокси не найден в хранилище: добавьте секрет вида «proxy»")
    for name in body.headers:
        if name.lower() in ("authorization", "host", "content-length"):
            raise bad_request(f"заголовок {name} задаётся платформой; секреты храните в хранилище")
    row = s.get(m.AISettings, ws) or m.AISettings(workspace_id=ws)
    row.enabled, row.provider, row.base_url, row.model = body.enabled, body.provider, body.base_url, body.model
    row.credential_id = body.credential_id
    row.extra = {"headers": body.headers, "timeout": body.timeout, "json_mode": body.json_mode,
                 "credential_ids": body.credential_ids, "proxy_credential_ids": body.proxy_credential_ids,
                 "fallback_models": [x.strip() for x in body.fallback_models if x.strip()],
                 "proxy_scheme": body.proxy_scheme, "proxy_port": body.proxy_port, "max_retries": body.max_retries,
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
        return {"ok": False, "error": "AI-провайдер не настроен. Проверьте ключ NVIDIA или настройки сервера Ollama."}
    provider = build_provider(cfg)
    started = time.monotonic()
    models: list[str] = []
    try:
        try:
            models = await provider.list_models()
        except LLMError:
            models = []
        res = await probe_chat(provider, min(cfg.timeout, 60))
        return {"ok": True, "model": res.model, "json_mode": res.json_mode, "models": models,
                "latency_ms": int((time.monotonic() - started) * 1000), "reply": masker.mask(res.content[:200])}
    except LLMError as exc:
        return {"ok": False, "error": masker.mask(str(exc)), "models": models}


@router.post("/settings/ai/diagnose")
async def diagnose_ai(body: WorkspaceRef, user: m.User = Depends(current_user),
                      s: Session = Depends(get_session)) -> dict:
    """One small request per proxy (every protocol for auto) and directly; OK/FAIL, time, reason — never secrets."""
    ws = resolve_workspace(s, user, body.workspace_id, "developer")
    masker = global_masker.child()
    try:
        cfg = provider_config_for(s, ws, None, masker, require_enabled=False)
    except LookupError as exc:
        return {"results": [], "error": str(exc)}
    if cfg is None:
        return {"results": [], "error": "AI-провайдер не настроен. Проверьте ключ NVIDIA или настройки сервера Ollama."}
    return {"results": await diagnose(cfg, masker), "error": None}


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
    selected_node_id: str | None = Field(default=None, min_length=1, max_length=64)


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
    out = masker.mask_obj({"graph": res.graph, "issues": res.issues, "needs_input": res.needs_input,
                           "attempts": res.attempts, "valid": res.valid, "usage": res.usage})
    if not res.valid:
        raise ApiError(422, "generation_failed", "не удалось получить корректный граф за 3 попытки — ничего не применено",
                       out)
    if body.create:
        prompt = masker.mask(body.prompt)
        wf = m.Workflow(workspace_id=ws, name=masker.mask(body.name) if body.name else prompt[:80],
                        description=prompt, graph=out["graph"],
                        created_by=user.id)
        s.add(wf)
        s.flush()
        sync_schedules(s, wf)
        s.add(m.WorkflowChatMessage(workflow_id=wf.id, user_id=user.id, role="user", content=prompt,
                                    status="applied"))
        s.commit()
        out["workflow_id"] = wf.id
    return out


def chat_out(msg: m.WorkflowChatMessage) -> dict:
    return {"id": msg.id, "role": msg.role, "content": msg.content, "operations": msg.operations, "status": msg.status,
            "created_at": msg.created_at}


def _recent_messages(s: Session, workflow_id: str, limit: int) -> list[m.WorkflowChatMessage]:
    msg = m.WorkflowChatMessage
    query = (select(msg).options(load_only(msg.id, msg.role, msg.content, msg.status, msg.created_at, msg.operations))
             .where(msg.workflow_id == workflow_id, or_(msg.content != "", msg.role == "assistant"))
             .order_by(msg.created_at.desc(), msg.role.asc(), msg.id.desc()).limit(limit))
    return list(reversed(s.scalars(query).all()))


@router.get("/ai/workflows/{workflow_id}/chat")
def ai_chat_history(workflow_id: str, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> list[dict]:
    wf = load_scoped(s, m.Workflow, workflow_id, user, what="сценарий")
    return [global_masker.mask_obj(chat_out(r)) for r in _recent_messages(s, wf.id, 200)]


@router.post("/ai/workflows/{workflow_id}/chat")
async def ai_chat(workflow_id: str, body: ChatIn, user: m.User = Depends(current_user),
                  s: Session = Depends(get_session)) -> dict:
    from app.ai.workflow_gen import graph_diff, propose_operations
    from app.nodes.base import get_registry

    wf = load_scoped(s, m.Workflow, workflow_id, user, "developer", "сценарий")
    masker = global_masker.child()
    if body.selected_node_id is not None and not any(n["id"] == body.selected_node_id for n in wf.graph.get("nodes", [])):
        raise ApiError(422, "unknown_node", "Выбранный блок отсутствует в сценарии")
    provider = _provider_or_400(s, wf.workspace_id, masker)
    history = [{"role": row.role, "content": masker.mask(row.content), "status": row.status}
               for row in _recent_messages(s, wf.id, 6)]
    reg = get_registry()
    try:
        result, ops, explanation = await propose_operations(provider, wf.graph, body.message, reg,
                                                           _cred_checker(s, wf.workspace_id), masker,
                                                           selected_node_id=body.selected_node_id, history=history)
    except LLMError as exc:
        raise ApiError(502, "ai_error", masker.mask(str(exc))) from exc
    status = "proposed" if result.valid else "failed"
    user_msg = m.WorkflowChatMessage(workflow_id=wf.id, user_id=user.id, role="user", content=masker.mask(body.message),
                                     status=status)
    s.add(user_msg)
    s.flush()
    graph = masker.mask_obj(result.graph) if result.valid else None
    bot = m.WorkflowChatMessage(workflow_id=wf.id, role="assistant", content=masker.mask(explanation),
                                user_message_id=user_msg.id, operations=masker.mask_obj(ops), status=status,
                                base_version=wf.version, result_graph=graph,
                                proposal_details=masker.mask_obj({
                                    "diff": graph_diff(wf.graph, graph) if graph else {},
                                    "attempts": result.attempts, "issues": result.issues,
                                    "needs_input": result.needs_input, "selected_node_id": body.selected_node_id}))
    s.add(bot)
    s.commit()
    s.refresh(wf)
    return _proposal_out(s, wf, bot, user_msg)


def _proposal(s: Session, wf: m.Workflow, msg_id: str) -> tuple[m.WorkflowChatMessage, m.WorkflowChatMessage | None]:
    msg = s.get(m.WorkflowChatMessage, msg_id)
    if msg is None or msg.workflow_id != wf.id or msg.role != "assistant":
        raise not_found("предложение")
    if msg.user_message_id or msg.proposal_details is not None:
        request = s.get(m.WorkflowChatMessage, msg.user_message_id) if msg.user_message_id else None
        return msg, request if request and request.workflow_id == wf.id and request.role == "user" else None

    # Legacy rows have no request reference. Recover only an unambiguous turn, leaving overlapping turns unpaired.
    row = m.WorkflowChatMessage
    history = select(row).where(row.workflow_id == wf.id)
    boundary = select(func.max(row.created_at)).where(row.workflow_id == wf.id, row.role == "assistant",
                                                      row.created_at < msg.created_at).scalar_subquery()
    candidates = s.scalars(history.where(row.role == "user", row.status == msg.status,
                                         row.created_at < msg.created_at,
                                         or_(boundary.is_(None), row.created_at > boundary)).limit(2)).all()
    if len(candidates) == 1:
        same_time = s.scalar(select(row.id).where(row.workflow_id == wf.id, row.created_at == msg.created_at,
                                                  row.id != msg.id).limit(1))
        next_role = s.scalar(select(row.role).where(row.workflow_id == wf.id, row.created_at > msg.created_at)
                             .order_by(row.created_at, row.role).limit(1))
        if same_time is None and next_role != "assistant":
            return msg, candidates[0]
    return msg, None


def _proposal_out(s: Session, wf: m.Workflow, msg: m.WorkflowChatMessage, request: m.WorkflowChatMessage | None) -> dict:
    stale = msg.status == "proposed" and msg.base_version != wf.version
    graph = msg.result_graph or {}
    details = msg.proposal_details
    if details is None:
        from app.ai.workflow_gen import blocking_issues, graph_diff, strip_secrets
        from app.nodes.base import get_registry

        graph = deepcopy(graph)
        registry, checker = get_registry(), _cred_checker(s, wf.workspace_id)
        needs = strip_secrets(graph, registry, checker) if graph else []
        issues = blocking_issues(graph, registry, checker, needs)[0] if graph else []
        details = {"diff": graph_diff(wf.graph, graph) if graph and msg.base_version == wf.version else {},
                   "issues": issues, "needs_input": needs, "attempts": None, "selected_node_id": None}
    return global_masker.mask_obj({**chat_out(msg), **details, "stale": stale, "graph": graph, "valid": bool(graph),
                                   "original_message": request.content if request else None,
                                   "user_message_id": request.id if request else None})


@router.get("/ai/workflows/{workflow_id}/chat/{msg_id}")
def ai_chat_detail(workflow_id: str, msg_id: str, user: m.User = Depends(current_user),
                   s: Session = Depends(get_session)) -> dict:
    wf = load_scoped(s, m.Workflow, workflow_id, user, what="сценарий")
    return _proposal_out(s, wf, *_proposal(s, wf, msg_id))


def _transition(s: Session, wf: m.Workflow, msg: m.WorkflowChatMessage,
                request: m.WorkflowChatMessage | None, status: str) -> None:
    row = m.WorkflowChatMessage
    changes = {"status": status}
    if msg.proposal_details is None:
        # Freeze the recoverable preview and pairing before the base graph or request status changes.
        preview = _proposal_out(s, wf, msg, request)
        changes["proposal_details"] = {k: preview[k] for k in ("diff", "issues", "needs_input", "attempts", "selected_node_id")}
        changes["user_message_id"] = preview["user_message_id"]
    claimed = s.execute(update(row).where(row.id == msg.id, row.status == "proposed").values(**changes))
    if claimed.rowcount != 1:
        raise ApiError(409, "not_applicable", "Это предложение уже обработано или недоступно")
    if request:
        s.execute(update(row).where(row.id == request.id, row.status == "proposed").values(status=status))


@router.post("/ai/workflows/{workflow_id}/chat/{msg_id}/apply")
def ai_chat_apply(workflow_id: str, msg_id: str, user: m.User = Depends(current_user),
                  s: Session = Depends(get_session)) -> dict:
    from app.engine.scheduler import sync_schedules

    wf = load_scoped(s, m.Workflow, workflow_id, user, "developer", "сценарий")
    msg, prev = _proposal(s, wf, msg_id)
    if msg.status != "proposed" or not msg.result_graph:
        raise ApiError(409, "not_applicable", "это предложение нельзя применить")
    from app.ai.workflow_gen import blocking_issues, strip_secrets
    from app.nodes.base import get_registry

    stale = ApiError(409, "proposal_stale", "Сценарий или его настройки изменились. Обновите предложение.")
    if wf.version != msg.base_version:
        raise stale
    candidate = deepcopy(msg.result_graph)
    checker = _cred_checker(s, wf.workspace_id)
    registry = get_registry()
    needs = strip_secrets(candidate, registry, checker)
    _, blocking = blocking_issues(candidate, registry, checker, needs)
    if candidate != msg.result_graph or blocking:
        raise stale
    _transition(s, wf, msg, prev, "applied")
    written = s.execute(update(m.Workflow).where(m.Workflow.id == wf.id, m.Workflow.version == msg.base_version)
                        .values(graph=candidate, version=m.Workflow.version + 1))
    if written.rowcount != 1:
        raise stale
    sync_schedules(s, wf)
    s.commit()
    return {"workflow_id": wf.id, "version": wf.version, "graph": wf.graph}


@router.post("/ai/workflows/{workflow_id}/chat/{msg_id}/reject")
def ai_chat_reject(workflow_id: str, msg_id: str, user: m.User = Depends(current_user),
                   s: Session = Depends(get_session)) -> dict:
    wf = load_scoped(s, m.Workflow, workflow_id, user, "developer", "сценарий")
    msg, prev = _proposal(s, wf, msg_id)
    _transition(s, wf, msg, prev, "rejected")
    s.commit()
    return {"status": "rejected"}
