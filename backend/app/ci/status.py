"""Commit statuses (and later PR/MR comments) back to GitHub/GitLab — writes are allowed only for allowlisted
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
        new_crit = sum((run.verdict or {}).get("new_counts_by_severity", {}).get(k, 0) for k in ("CRITICAL",))
        if verdict == "FAIL":
            return "failure", f"{new_crit} new critical — merge blocked"
        return "failure", f"gate fail: CRITICAL {by.get('CRITICAL', 0)}, HIGH {by.get('HIGH', 0)}"
    return "success", f"findings: {(run.summary or {}).get('total', 0)}, gate pass"


async def report_run_status(db: Database, run_id: str, findings) -> None:  # noqa: ANN001 - post-run hook
    with db.session() as s:
        run = s.get(m.Run, run_id)
        scm = (run.trigger_payload or {}).get("scm") if run else None
        if not scm or not scm.get("sha"):
            return
        target = scm_target(s, run.workspace_id, scm["provider"], scm["repo_url"], scm["project"])
        state, desc = run_state(run)
    if target is None:
        return
    await post_status(db, run_id, target, scm["sha"], state, desc,
                      f"{get_settings().public_url.rstrip('/')}/runs/{run_id}")
