"""Commit statuses and PR/MR report comments back to GitHub/GitLab — writes are allowed only for allowlisted
repositories with ``allow_write`` (never the organizer repository; enforced in code by ``is_readonly_repo``)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import quote

from sqlalchemy import select

from app import models as m
from app.config import get_settings
from app.core.crypto import get_box
from app.core.masking import global_masker
from app.core.repo_guard import is_readonly_repo, normalize_repo_url
from app.core.ssrf import safe_request
from app.db import Database

logger = logging.getLogger(__name__)
DEFAULT_API = {"github": "https://api.github.com", "gitlab": "https://gitlab.com/api/v4"}
CONTEXT = "aisw/security"
COMMENT_MARKER = "<!-- aisw-report -->"
SEV_ICON = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "⚪"}


@dataclass
class ScmTarget:
    provider: str
    api_base: str
    token: str
    project: str  # "owner/repo" (GitHub) or "group/project" (GitLab)
    repo_url: str


def scm_target(s, workspace_id: str, provider: str, repo_url: str, project: str) -> ScmTarget | None:  # noqa: ANN001
    norm = normalize_repo_url(repo_url)
    if is_readonly_repo(norm):
        return None
    for e in s.scalars(select(m.RepoAllowlist).where(m.RepoAllowlist.workspace_id == workspace_id)):
        if normalize_repo_url(e.url) != norm or not e.allow_write or not e.write_credential_id:
            continue
        cred = s.get(m.Credential, e.write_credential_id)
        if cred is None or cred.workspace_id != workspace_id:
            return None
        token = get_box().decrypt(cred.ciphertext)
        global_masker.register(token)
        return ScmTarget(provider, (e.api_base or DEFAULT_API[provider]).rstrip("/"), token, project, norm)
    return None


def auth_headers(t: ScmTarget) -> dict[str, str]:
    if t.provider == "github":
        return {"Authorization": f"Bearer {t.token}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "aisw"}
    return {"PRIVATE-TOKEN": t.token, "User-Agent": "aisw"}


GITLAB_STATE = {"pending": "pending", "success": "success", "failure": "failed", "error": "failed"}


async def post_status(db: Database, run_id: str, t: ScmTarget, sha: str, state: str, description: str,
                      target_url: str) -> int | None:
    allow = get_settings().ssrf_allowed()
    try:
        if t.provider == "github":
            resp = await safe_request("POST", f"{t.api_base}/repos/{t.project}/statuses/{sha}", allow_hosts=allow,
                                      headers=auth_headers(t), json={"state": state, "target_url": target_url,
                                                                      "description": description[:140],
                                                                      "context": CONTEXT})
        else:
            q = (f"state={GITLAB_STATE[state]}&name={quote(CONTEXT)}&target_url={quote(target_url, safe='')}"
                 f"&description={quote(description[:140])}")
            resp = await safe_request("POST", f"{t.api_base}/projects/{quote(t.project, safe='')}/statuses/{sha}?{q}",
                                      allow_hosts=allow, headers=auth_headers(t))
        code, err = resp.status_code, None if resp.status_code < 400 else resp.text[:300]
    except Exception as exc:  # status reporting must never break the run
        code, err = None, f"{type(exc).__name__}: {exc}"
        logger.warning("commit status for run %s failed: %s", run_id, global_masker.mask(err))
    with db.session() as s:
        s.add(m.CiStatusReport(run_id=run_id, provider=t.provider, kind="status", state=state, target=f"{t.project}@{sha}",
                               response_code=code, error=global_masker.mask(err) if err else None))
        s.commit()
    return code


def run_state(run: m.Run) -> tuple[str, str]:
    by = (run.summary or {}).get("by_severity", {})
    if run.status != "success":
        return "error", f"проверка завершилась со статусом {run.status}"
    verdict = (run.verdict or {}).get("verdict")
    if verdict == "FAIL" or run.gate == "fail":
        if verdict == "FAIL":
            v = run.verdict or {}
            thr = str(v.get("threshold") or "CRITICAL")
            n = v.get("blocking_count") or v.get("new_counts_by_severity", {}).get(thr, 0)
            label = thr.lower() if thr == "CRITICAL" else f"{thr.lower()}+"
            return "failure", f"{n} new {label} — merge blocked"
        return "failure", f"gate fail: CRITICAL {by.get('CRITICAL', 0)}, HIGH {by.get('HIGH', 0)}"
    return "success", f"findings: {(run.summary or {}).get('total', 0)}, gate pass"


def _loc(f) -> str:  # noqa: ANN001
    if f.category == "SCA":
        return f"`{f.group}:{f.artifact}:{f.version}` ({f.advisory_id})"
    return f"`{f.path}:{f.line}`"


def render_comment(run: m.Run, findings: list, run_url: str) -> str:  # noqa: ANN001
    """Markdown for the single PR/MR comment. Values are already masked; author (personal data) is not included."""
    v = run.verdict or {}
    lines = [COMMENT_MARKER, "## AI Security Workflow", ""]
    if v.get("verdict") in ("PASS", "FAIL"):
        new = [f for f in findings if f.diff_status == "new"]
        new.sort(key=lambda f: (-{"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}[f.severity], f.path, f.line))
        if v["verdict"] == "FAIL":
            top = next((f for f in new if f.severity == v.get("threshold")), new[0] if new else None)
            head = f"🔴 **FAIL** — новые находки уровня ≥ {v.get('threshold')}, PR заблокирован"
            if top is not None:
                head += (f": {top.title} в {_loc(top)}"
                         + (f", коммит `{top.introduced_in_commit[:7]}`" if top.introduced_in_commit else ""))
            lines.append(head)
        else:
            lines.append("✅ **PASS** — новых блокирующих находок нет"
                         + (f" ({v.get('would_fail_reason')}, режим report_only)" if v.get("would_fail_reason") else ""))
        lines.append("")
        if new:
            lines += ["| Severity | Находка | Где | Коммит |", "|---|---|---|---|"]
            for f in new[:30]:
                commit = f"`{f.introduced_in_commit[:7]}`" if f.introduced_in_commit else "—"
                lines.append(f"| {SEV_ICON[f.severity]} {f.severity} | {f.title} | {_loc(f)} | {commit} |")
            if len(new) > 30:
                lines.append(f"| … | ещё {len(new) - 30} | | |")
            lines.append("")
        lines.append(f"ℹ️ {v.get('existing_count', 0)} существующих находок не блокируют PR.")
        if v.get("fixed_in_diff"):
            lines.append(f"🟢 Устранено в этом diff: {len(v['fixed_in_diff'])}.")
    else:
        by = (run.summary or {}).get("by_severity", {})
        gate = "❌ FAIL" if run.gate == "fail" else "✅ PASS"
        lines += [f"**Gate:** {gate}", "", "| CRITICAL | HIGH | MEDIUM | LOW |", "|---|---|---|---|",
                  f"| {by.get('CRITICAL', 0)} | {by.get('HIGH', 0)} | {by.get('MEDIUM', 0)} | {by.get('LOW', 0)} |"]
    lines += ["", f"[Отчёт о запуске]({run_url})"]
    return global_masker.mask("\n".join(lines)) + "\n"


async def upsert_comment(db: Database, run_id: str, t: ScmTarget, number: int | str, body: str) -> int | None:
    """One report comment per PR/MR: found by marker and updated in place, created otherwise (no spam)."""
    allow = get_settings().ssrf_allowed()
    h = auth_headers(t)
    if t.provider == "github":
        base = f"{t.api_base}/repos/{t.project}/issues/{int(number)}/comments"
        upd, upd_method = f"{t.api_base}/repos/{t.project}/issues/comments/{{id}}", "PATCH"
    else:
        base = f"{t.api_base}/projects/{quote(t.project, safe='')}/merge_requests/{int(number)}/notes"
        upd, upd_method = base + "/{id}", "PUT"
    state, code, err, ext = "created", None, None, None
    try:
        existing = await safe_request("GET", base + "?per_page=100", allow_hosts=allow, headers=h)
        found = None
        if existing.status_code == 200 and isinstance(existing.json(), list):
            found = next((c for c in existing.json() if COMMENT_MARKER in str(c.get("body", ""))), None)
        if found is not None:
            state, ext = "updated", str(found.get("id"))
            resp = await safe_request(upd_method, upd.format(id=int(found["id"])), allow_hosts=allow, headers=h,
                                      json={"body": body})
        else:
            resp = await safe_request("POST", base, allow_hosts=allow, headers=h, json={"body": body})
            if resp.status_code < 400:
                ext = str(resp.json().get("id"))
        code, err = resp.status_code, None if resp.status_code < 400 else resp.text[:300]
    except Exception as exc:  # reporting must never break the run
        code, err = None, f"{type(exc).__name__}: {exc}"
        logger.warning("PR comment for run %s failed: %s", run_id, global_masker.mask(err))
    with db.session() as s:
        s.add(m.CiStatusReport(run_id=run_id, provider=t.provider, kind="comment", state=state,
                               target=f"{t.project}#{number}", response_code=code, external_id=ext,
                               error=global_masker.mask(err) if err else None))
        s.commit()
    return code


async def report_run_status(db: Database, run_id: str, findings) -> None:  # noqa: ANN001 - post-run hook
    run_url = f"{get_settings().public_url.rstrip('/')}/runs/{run_id}"
    with db.session() as s:
        run = s.get(m.Run, run_id)
        scm = (run.trigger_payload or {}).get("scm") if run else None
        if not scm or not scm.get("sha"):
            return
        target = scm_target(s, run.workspace_id, scm["provider"], scm["repo_url"], scm["project"])
        state, desc = run_state(run)
        comment = render_comment(run, findings, run_url) if scm.get("pr") and run.status == "success" else None
    if target is None:
        return
    await post_status(db, run_id, target, scm["sha"], state, desc, run_url)
    if comment is not None and str(scm["pr"]).isdigit():
        await upsert_comment(db, run_id, target, scm["pr"], comment)
