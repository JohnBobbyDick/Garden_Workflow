"""AutoFix Pull Request / Merge Request through REST (12A.3 §3) — never ``git push`` with a token in a URL.

GitHub: base sha → POST git/refs (``refs/heads/autofix/<finding_id>``) → PUT contents (with blob sha) → pulls.
GitLab: POST repository/branches → POST repository/commits (actions ``update``) → merge_requests.
Idempotent: an existing branch / PR / MR is updated, not duplicated. No auto-merge, never a commit to the base branch.
Writes only for allowlisted repositories with ``allow_write`` (``scm_target`` refuses the organizer repository).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from urllib.parse import quote

from app.ci.status import ScmTarget, auth_headers
from app.config import get_settings
from app.core.repo_guard import check_ref
from app.core.ssrf import safe_request

LABEL = "security-autofix"


class PrError(Exception):
    pass


@dataclass
class PrFile:
    path: str  # path inside the repository
    content: str


@dataclass
class PrResult:
    url: str
    number: int | str
    branch: str
    created: bool


async def _call(t: ScmTarget, method: str, path: str, json: dict | None = None):  # noqa: ANN202
    resp = await safe_request(method, f"{t.api_base}{path}", allow_hosts=get_settings().ssrf_allowed(),
                              headers=auth_headers(t), json=json)
    return resp


def _ok(resp, what: str) -> dict | list:  # noqa: ANN001
    if resp.status_code >= 400:
        raise PrError(f"{what}: HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError:
        return {}


def _head(pr: dict) -> str | None:
    h = pr.get("head")
    return h.get("ref") if isinstance(h, dict) else h


async def github_pr(t: ScmTarget, base: str, branch: str, files: list[PrFile], title: str, body: str,
                    message: str) -> PrResult:
    p = t.project
    ref = _ok(await _call(t, "GET", f"/repos/{p}/git/ref/heads/{quote(base)}"), "base-ветка")
    sha = (ref.get("object") or {}).get("sha") if isinstance(ref, dict) else None
    if not sha:
        raise PrError("не удалось получить sha base-ветки")
    r = await _call(t, "POST", f"/repos/{p}/git/refs", {"ref": f"refs/heads/{branch}", "sha": sha})
    if r.status_code not in (201, 422):  # 422 = branch already exists → update it
        _ok(r, "создание ветки")
    for f in files:
        cur = await _call(t, "GET", f"/repos/{p}/contents/{quote(f.path)}?ref={quote(branch)}")
        blob = cur.json().get("sha") if cur.status_code == 200 else None
        body_put = {"message": message, "branch": branch,
                    "content": base64.b64encode(f.content.encode("utf-8")).decode()}
        if blob:
            body_put["sha"] = blob
        _ok(await _call(t, "PUT", f"/repos/{p}/contents/{quote(f.path)}", body_put), f"коммит {f.path}")
    owner = p.split("/", 1)[0]
    pulls = _ok(await _call(t, "GET", f"/repos/{p}/pulls?head={quote(owner + ':' + branch)}&state=open"),
                "список PR")
    existing = next((x for x in pulls if _head(x) in (branch, f"{owner}:{branch}")), None) \
        if isinstance(pulls, list) else None
    if existing:
        num = existing["number"]
        pr = _ok(await _call(t, "PATCH", f"/repos/{p}/pulls/{num}", {"title": title, "body": body}), "обновление PR")
        created = False
    else:
        pr = _ok(await _call(t, "POST", f"/repos/{p}/pulls", {"title": title, "head": branch, "base": base,
                                                              "body": body, "maintainer_can_modify": False}),
                 "создание PR")
        num, created = pr["number"], True
    _ok(await _call(t, "POST", f"/repos/{p}/issues/{num}/labels", {"labels": [LABEL]}), "метка PR")
    return PrResult(pr.get("html_url") or existing.get("html_url", ""), num, branch, created)  # type: ignore[union-attr]


async def gitlab_mr(t: ScmTarget, base: str, branch: str, files: list[PrFile], title: str, body: str,
                    message: str) -> PrResult:
    pid = quote(t.project, safe="")
    r = await _call(t, "POST", f"/projects/{pid}/repository/branches?branch={quote(branch, safe='')}"
                               f"&ref={quote(base, safe='')}")
    if r.status_code not in (201, 400):  # 400 = branch already exists → update it
        _ok(r, "создание ветки")
    _ok(await _call(t, "POST", f"/projects/{pid}/repository/commits", {
        "branch": branch, "commit_message": message,
        "actions": [{"action": "update", "file_path": f.path, "content": f.content} for f in files]}), "коммит")
    mrs = _ok(await _call(t, "GET", f"/projects/{pid}/merge_requests?source_branch={quote(branch, safe='')}"
                                    f"&state=opened"), "список MR")
    existing = next((x for x in mrs if (x.get("source_branch") or x.get("head")) == branch), None) \
        if isinstance(mrs, list) else None
    if existing:
        iid = existing["iid"]
        mr = _ok(await _call(t, "PUT", f"/projects/{pid}/merge_requests/{iid}",
                             {"title": title, "description": body, "labels": LABEL}), "обновление MR")
        created = False
    else:
        mr = _ok(await _call(t, "POST", f"/projects/{pid}/merge_requests", {
            "source_branch": branch, "target_branch": base, "title": title, "description": body, "labels": LABEL,
            "remove_source_branch": False}), "создание MR")
        iid, created = mr["iid"], True
    return PrResult(mr.get("web_url") or existing.get("web_url", ""), iid, branch, created)  # type: ignore[union-attr]


async def open_pull_request(t: ScmTarget, base: str, branch: str, files: list[PrFile], title: str, body: str,
                            message: str) -> PrResult:
    check_ref(base)
    check_ref(branch)
    if branch == base:
        raise PrError("ветка AutoFix не может совпадать с base-веткой")
    fn = github_pr if t.provider == "github" else gitlab_mr
    return await fn(t, base, branch, files, title, body, message)
