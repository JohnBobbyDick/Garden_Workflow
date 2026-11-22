"""Turning a ``validated`` AutoFix into a PR/MR: target resolution (allowlist + ``allow_write``; organizer repository
and uploads/directories → ``.patch`` only), PR description template (masked), re-applying the stored secret-free
proposal on freshly restored sources (real file contents are never stored in the DB)."""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from sqlalchemy import select

from app import models as m
from app.analyzers.common.finding import Finding
from app.autofix.context import SecretIndex
from app.autofix.pr.scm import PrFile, PrResult, open_pull_request
from app.autofix.sca_bump import plan_bump
from app.autofix.source import restored_source
from app.autofix.validator import reapply
from app.ci.status import ScmTarget, scm_target
from app.core.masking import Masker
from app.core.repo_guard import is_readonly_path, is_readonly_repo, normalize_repo_url

MARKER = "<!-- aisw-autofix:{fid} -->"
STEP_TITLES = {"schema": "JSON-схема", "location": "файл и строки", "old_snippet": "old_snippet совпадает с файлом",
               "new_snippet": "без секретов и масок", "apply": "применение к копии", "syntax": "синтаксис (tree-sitter)",
               "self_check": "самопроверка анализаторами", "bump": "обновление версии"}


class PrForbidden(Exception):
    pass


def resolve_target(s, run: m.Run) -> tuple[ScmTarget, str]:  # noqa: ANN001
    """(target, default base branch) or PrForbidden with the reason shown to the user."""
    payload = run.trigger_payload or {}
    scm = payload.get("scm") or {}
    src = run.source or {}
    if scm.get("repo_url"):
        url, provider, project = scm["repo_url"], scm.get("provider", "github"), scm.get("project", "")
        base = payload.get("base_ref") or "main"
    elif src.get("mode") == "git_url" and src.get("url"):
        url = src["url"]
        entry = next((e for e in s.scalars(select(m.RepoAllowlist).where(m.RepoAllowlist.workspace_id ==
                                                                          run.workspace_id))
                      if normalize_repo_url(e.url) == normalize_repo_url(url)), None)
        provider = entry.provider if entry else "github"
        project = urlsplit(normalize_repo_url(url)).path.strip("/").removesuffix(".git")
        base = src.get("ref") if src.get("ref") and len(src.get("ref", "")) != 40 else "main"
    elif src.get("mode") == "path" and src.get("scan_path") and is_readonly_path(src["scan_path"]):
        raise PrForbidden("репозиторий организаторов и фикстуры доступны только для чтения — скачайте .patch")
    else:
        raise PrForbidden("PR доступен только для git-репозитория пользователя; для загруженного архива или каталога "
                          "скачайте .patch")
    if is_readonly_repo(url):
        raise PrForbidden("репозиторий организаторов доступен только для чтения — скачайте .patch")
    target = scm_target(s, run.workspace_id, provider, url, project)
    if target is None:
        raise PrForbidden("для репозитория не разрешена запись (allow_write=false или нет токена repo_write_token) — "
                          "скачайте .patch")
    return target, base


def pr_text(af: m.Autofix, finding: Finding, run_url: str, masker: Masker, note: str | None = None) -> tuple[str, str]:
    prop = af.proposal or {}
    title = f"[security-autofix] {finding.title}"[:200]
    steps = "\n".join(f"- {'✅' if st['ok'] else '❌'} {STEP_TITLES.get(st['name'], st['name'])}"
                      for st in af.steps or [])
    req = prop.get("requires_config") or []
    lines = [MARKER.format(fid=finding.id), f"## 🔒 AI AutoFix: {finding.title}", "",
             *([note.strip()[:2000], ""] if note and note.strip() else []),
             f"**Находка:** {finding.title} — `{finding.path}:{finding.line}` · {finding.severity} · `{finding.rule_id}`"
             f" · `{finding.id}`",
             "", f"**Что изменено:** {prop.get('explanation', '')}", "",
             "**Проверка:** самопроверка пройдена: находка устранена, 0 новых находок.", steps]
    if req:
        lines += ["", "**Требуется настроить перед слиянием:**",
                  *[f"- `{r['name']}` — {r['description']}" for r in req]]
    for n in prop.get("notes") or []:
        lines += ["", f"⚠️ {n}"]
    lines += ["", f"Запуск: {run_url}", "",
              "_PR создан AI Security Workflow. Auto-merge не включён — проверьте изменения перед слиянием._"]
    return masker.mask(title), masker.mask("\n".join(lines))


async def create_pr(s, run: m.Run, af: m.Autofix, finding: Finding, run_url: str,  # noqa: ANN001
                    target_branch: str | None = None, note: str | None = None) -> PrResult:
    target, base = resolve_target(s, run)
    base = target_branch or base
    masker = Masker()
    masker.register(target.token)
    sub = (run.source or {}).get("subdir") or ""
    with restored_source(s, run) as root:
        secrets = await asyncio.to_thread(SecretIndex.scan, root)
        masker.register(*secrets.all_values())
        if af.kind == "deterministic":
            _, edits, _ = plan_bump(root, finding)
        else:
            edits = reapply(root, af.proposal or {}, secrets)
        files = [PrFile(f"{sub.strip('/')}/{e.path}" if sub else e.path, e.after) for e in edits]
    title, body = pr_text(af, finding, run_url, masker, note)
    return await open_pull_request(target, base, f"autofix/{finding.id}", files, title, body,
                                   f"fix(security): {finding.cls} ({finding.id})")
