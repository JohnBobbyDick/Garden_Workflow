"""«Новая проверка»: one request from «what to check» + «how to start» to a ready workflow.

The source is written into every ``source.repo`` node (git link, uploaded archive or the organizers' training set), so
the person never types server paths or template parameters. Template parameters that are still empty (e.g. a Telegram
token) do not block creation: they are returned in ``needs_input`` and the canvas flags those nodes."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.api.demo import TRAINING, demo_graph
from app.config import get_settings
from app.core.errors import ApiError
from app.core.repo_guard import RepoGuardError, check_git_url, check_scan_path, normalize_repo_url
from app.deps import current_user, get_session, resolve_workspace
from app.engine.services import allowlist_for
from app.templates_lib import TemplateParamError, apply_parameters

router = APIRouter(tags=["checks"])


def _graph(nodes: list[tuple[str, str, dict]], edges: list[tuple[str, str, str, str]]) -> dict:
    return {"schema_version": 1,
            "nodes": [{"id": i, "type": t, "position": {"x": 0, "y": 0}, "config": c} for i, t, c in nodes],
            "edges": [{"id": f"e{k}", "source": a, "source_port": ap, "target": b, "target_port": bp}
                      for k, (a, ap, b, bp) in enumerate(edges)]}


def full_graph() -> dict:
    return _graph(
        [("trigger", "trigger.manual", {}), ("src", "source.repo", {}), ("secrets", "scanner.secrets", {}),
         ("sca", "scanner.sca", {}), ("sast", "scanner.sast", {}), ("merge", "logic.merge", {}),
         ("if", "logic.if_else", {"expression": "severity.max >= HIGH"}), ("ai", "ai.report", {}),
         ("score", "analysis.security_score", {}), ("report", "output.report_export", {})],
        [("trigger", "out", "src", "in"), ("src", "out", "secrets", "in"), ("src", "out", "sca", "in"),
         ("src", "out", "sast", "in"), ("secrets", "out", "merge", "in"), ("sca", "out", "merge", "in"),
         ("sast", "out", "merge", "in"), ("merge", "out", "if", "in"), ("if", "true", "ai", "in"),
         ("merge", "out", "score", "findings"), ("src", "out", "score", "repo"), ("merge", "out", "report", "in"),
         ("ai", "out", "report", "ai")])


def secrets_graph() -> dict:
    return _graph([("trigger", "trigger.manual", {}), ("src", "source.repo", {}), ("secrets", "scanner.secrets", {}),
                   ("report", "output.report_export", {})],
                  [("trigger", "out", "src", "in"), ("src", "out", "secrets", "in"),
                   ("secrets", "out", "report", "in")])


def pr_graph() -> dict:
    g = demo_graph()
    for n in g["nodes"]:
        n["position"] = {"x": 0, "y": 0}
    return g


STARTERS: dict[str, dict[str, Any]] = {
    "full": {"title": "Полная проверка", "graph": full_graph,
             "description": "Секреты, зависимости и SAST, AI-объяснение при High и выше, Security Score и отчёт."},
    "secrets": {"title": "Только секреты", "graph": secrets_graph,
                "description": "Быстрый поиск паролей, токенов и ключей в коде и конфигурации."},
    "pr": {"title": "Проверка PR (diff)", "graph": pr_graph,
           "description": "Новые находки относительно базовой ветки, решение «блокировать PR?», AI AutoFix и Score."},
}


class SourceIn(BaseModel):
    mode: Literal["git_url", "upload", "training"]
    url: str | None = Field(default=None, max_length=500)
    ref: str | None = Field(default=None, max_length=200)
    upload_id: str | None = None
    subdir: str | None = Field(default=None, max_length=300)


class StartIn(BaseModel):
    starter: str | None = None
    template_id: str | None = None
    blank: bool = False
    prompt: str | None = Field(default=None, max_length=4000)


class CheckIn(BaseModel):
    workspace_id: str | None = None
    name: str | None = Field(default=None, max_length=200)
    source: SourceIn
    start: StartIn


@router.get("/checks/starters")
def starters(user: m.User = Depends(current_user)) -> list[dict]:
    return [{"id": k, "title": v["title"], "description": v["description"]} for k, v in STARTERS.items()]


def _source_config(s: Session, ws: str, src: SourceIn) -> tuple[dict, str]:
    """Node config for ``source.repo`` + default check name."""
    if src.mode == "training":
        try:
            path = check_scan_path(str(TRAINING), get_settings().scan_root_paths())
        except RepoGuardError as exc:
            raise ApiError(422, "demo_unavailable", f"учебный набор недоступен: {exc}") from exc
        return {"mode": "path", "path": str(path)}, "Учебный проект"
    if src.mode == "upload":
        up = s.get(m.Upload, src.upload_id or "")
        if up is None or up.workspace_id != ws:
            raise ApiError(422, "upload_not_found", "загруженный архив не найден")
        stem = PurePosixPath(up.filename).name
        for ext in (".tar.gz", ".tgz", ".zip", ".tar", ".gz"):
            if stem.lower().endswith(ext):
                stem = stem[: -len(ext)]
                break
        return {"mode": "upload", "upload_id": up.id}, stem or "Архив"
    url = normalize_repo_url(src.url or "")
    try:
        check_git_url(url, allowlist_for(s, ws))
    except RepoGuardError as exc:
        raise ApiError(422, "not_attested", "подтвердите, что это учебный или собственный проект "
                                            f"(репозиторий ещё не разрешён): {exc}") from exc
    cfg = {"mode": "git_url", "git_url": url, "ref": src.ref or ""}
    if src.subdir:
        sub = src.subdir.strip().strip("/")
        if "\\" in sub or ".." in sub.split("/"):
            raise ApiError(422, "invalid_subdir", "недопустимый подкаталог проекта")
        cfg["subdir"] = sub
    return cfg, url.rstrip("/").rsplit("/", 1)[-1]


async def _start_graph(s: Session, ws: str, user: m.User, start: StartIn) -> tuple[dict, list[dict], str | None]:
    if start.blank:
        return _graph([("trigger", "trigger.manual", {}), ("src", "source.repo", {})],
                      [("trigger", "out", "src", "in")]), [], None
    if start.starter:
        if start.starter not in STARTERS:
            raise ApiError(422, "unknown_starter", "неизвестный вариант старта")
        return STARTERS[start.starter]["graph"](), [], None
    if start.template_id:
        from app.api.templates import _get as get_template
        t = get_template(s, start.template_id, user)
        ids = set(s.scalars(select(m.Credential.id).where(m.Credential.workspace_id == ws)))
        missing: list[dict] = []
        try:
            g = apply_parameters(t.graph, t.parameters, {}, lambda c: c in ids, missing=missing)
        except TemplateParamError as exc:
            raise ApiError(422, "template_params", str(exc)) from exc
        t.usage_count += 1
        return g, [x for x in missing if not x["field"].startswith(("path", "git_url", "upload_id", "mode"))], t.id
    if start.prompt:
        from app.ai.providers.base import LLMError, build_provider
        from app.ai.settings_service import provider_config_for
        from app.ai.workflow_gen import generate_graph
        from app.core.masking import global_masker
        from app.nodes.base import get_registry
        masker = global_masker.child()
        cfg = provider_config_for(s, ws, None, masker)
        if cfg is None:
            raise ApiError(422, "ai_not_configured", "AI-провайдер не настроен: Настройки → AI")
        ids = set(s.scalars(select(m.Credential.id).where(m.Credential.workspace_id == ws)))
        try:
            res = await generate_graph(build_provider(cfg), start.prompt, get_registry(), lambda c: c in ids, masker)
        except LLMError as exc:
            raise ApiError(502, "ai_error", masker.mask(str(exc))) from exc
        if not res.valid:
            raise ApiError(422, "generation_failed", "не удалось получить корректный граф — попробуйте другой текст",
                           {"issues": res.issues})
        return res.graph, list(res.needs_input or []), None
    raise ApiError(422, "start_required", "выберите, с чего начать: готовый сценарий, шаблон, пустой граф или текст")


@router.post("/checks", status_code=201)
async def create_check(body: CheckIn, user: m.User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    from app.engine.scheduler import sync_schedules

    ws = resolve_workspace(s, user, body.workspace_id, "developer")
    src_cfg, default_name = _source_config(s, ws, body.source)
    graph, needs, template_id = await _start_graph(s, ws, user, body.start)
    has_source = False
    for n in graph.get("nodes", []):
        if n.get("type") == "source.repo":
            n["config"] = dict(src_cfg)
            has_source = True
    if not has_source:
        raise ApiError(422, "no_source_node", "в выбранном сценарии нет ноды «Исходный код»")
    wf = m.Workflow(workspace_id=ws, name=(body.name or default_name)[:200], graph=graph, created_by=user.id,
                    description=body.start.prompt or "", forked_from=template_id)
    s.add(wf)
    s.flush()
    sync_schedules(s, wf)
    s.commit()
    return {"workflow_id": wf.id, "needs_input": needs}
