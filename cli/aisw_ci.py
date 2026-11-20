#!/usr/bin/env python3
"""AI Security Workflow CI client (Python stdlib only, single file).

Packs the working copy, uploads it to the platform, starts the workflow, waits for the result, prints a summary,
writes ``report.md`` / ``submission.json`` and exits with: 0 = pass, 1 = gate/verdict fail (Critical by default),
2 = platform/transport error.

    AISW_TOKEN=aisw_... python aisw_ci.py --url https://aisw.example --workflow <id> [--path .] [--out aisw-report]

With git history available (``fetch-depth: 0`` / ``GIT_DEPTH: 0``) the CLI also uploads a diff context for
diff-aware scanning (only new findings block the PR)."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path

EXCLUDE_DIRS = {".git", "node_modules", "build", ".gradle", ".idea", "target", "out", "dist", "__pycache__", ".venv"}
MAX_ARCHIVE = 45 * 1024 * 1024
BUILD_FILES = ("build.gradle.kts", "build.gradle", "settings.gradle.kts", "settings.gradle", "gradle.properties",
               "gradle.lockfile", "gradle/libs.versions.toml")


class PlatformError(Exception):
    pass


def pack(root: Path, skip: Path | None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS
                           and not (skip and Path(dirpath, d).resolve() == skip)]
            for name in filenames:
                p = Path(dirpath, name)
                if p.is_symlink() or p.stat().st_size > 2 * 1024 * 1024:
                    continue
                z.write(p, p.relative_to(root).as_posix())
    data = buf.getvalue()
    if len(data) > MAX_ARCHIVE:
        raise PlatformError(f"архив слишком большой ({len(data) // 1024 // 1024} МБ)")
    return data


def git(*args: str, cwd: Path) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60,
                              check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None


BUILD_NAMES = {f.rsplit("/", 1)[-1] for f in BUILD_FILES}
HUNK_NEW_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
MAX_BLAME_RANGES = 300


def changed_ranges(diff: str) -> dict[str, list[tuple[int, int]]]:
    """{repo-relative path: [(start, end)]} of added lines in a --unified=0 diff."""
    out: dict[str, list[tuple[int, int]]] = {}
    path = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            p = line[4:].strip()
            path = None if p == "/dev/null" else (p[2:] if p.startswith("b/") else p)
        elif path and (m := HUNK_NEW_RE.match(line)):
            start, count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
            if count:
                out.setdefault(path, []).append((start, start + count - 1))
    return out


def parse_blame(text: str) -> dict[int, list[str]]:
    info: dict[str, dict[str, str]] = {}
    out: dict[int, list[str]] = {}
    sha, final = None, 0
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and re.fullmatch(r"[0-9a-f]{40}", parts[0]) and parts[1].isdigit():
            sha, final = parts[0], int(parts[2])
            info.setdefault(sha, {})
        elif sha and line.startswith("author-mail "):
            info[sha]["mail"] = line[12:].strip().strip("<>")
        elif sha and line.startswith("author "):
            info[sha]["name"] = line[7:].strip()
        elif sha and line.startswith("\t"):
            out[final] = [sha, info[sha].get("mail") or info[sha].get("name") or ""]
    return out


def diff_context(root: Path, base_ref: str | None) -> dict | None:
    """git diff from the merge base (three dots) + base versions of build files + blame of changed lines."""
    head = (git("rev-parse", "HEAD", cwd=root) or "").strip()
    if not head:
        return None
    base = base_ref or os.environ.get("GITHUB_BASE_REF") or os.environ.get("CI_MERGE_REQUEST_TARGET_BRANCH_NAME") or "main"
    if base.startswith("-"):
        return None
    base_sha = merge_base = None
    for c in (f"origin/{base}", base):
        sha = git("rev-parse", "--verify", "--quiet", f"{c}^{{commit}}", cwd=root)
        mb = git("merge-base", c, "HEAD", cwd=root) if sha else None
        if mb:
            base_sha, merge_base = sha.strip(), mb.strip()
            break
    if not merge_base:
        return None
    top = (git("rev-parse", "--show-toplevel", cwd=root) or "").strip()
    prefix = Path(root).resolve().relative_to(Path(top).resolve()).as_posix() if top else ""
    prefix = "" if prefix == "." else prefix
    diff = git("diff", "--no-ext-diff", "--no-textconv", "--unified=0", "--find-renames", "-w", "--ignore-blank-lines",
               f"{base_sha}...HEAD", "--", ".", cwd=root) or ""
    base_files = {}
    for full in (git("ls-tree", "-r", "--full-name", "--name-only", merge_base, "--", ".", cwd=root) or "").splitlines():
        if full.rsplit("/", 1)[-1] in BUILD_NAMES:
            content = git("show", "--no-textconv", f"{merge_base}:{full}", cwd=root)
            rel = full[len(prefix) + 1:] if prefix and full.startswith(prefix + "/") else full
            if content is not None:
                base_files[rel] = content
    blame: dict[str, dict[int, list[str]]] = {}
    budget = MAX_BLAME_RANGES
    for path, ranges in changed_ranges(diff).items():
        rel = path[len(prefix) + 1:] if prefix and path.startswith(prefix + "/") else path
        for start, end in ranges:
            if budget <= 0:
                break
            budget -= 1
            out = git("blame", "--porcelain", "-L", f"{start},{end}", "HEAD", "--", path, cwd=Path(top or root))
            if out:
                blame.setdefault(rel, {}).update(parse_blame(out))
    return {"base_sha": base_sha, "head_sha": head, "merge_base": merge_base, "diff": diff[:5_000_000],
            "path_prefix": prefix, "base_files": base_files, "blame": blame}


def request(method: str, url: str, token: str, body: bytes | None = None, ctype: str | None = None,
            timeout: float = 60) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers={"Authorization": f"Bearer {token}",
                                                                        "User-Agent": "aisw-ci/1"})
    if ctype:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - URL is the configured platform
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise PlatformError(f"платформа недоступна: {e}") from e


def multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes]]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    for k, (fname, data) in files.items():
        out.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fname}\"\r\n"
                  "Content-Type: application/zip\r\n\r\n".encode())
        out.write(data)
        out.write(b"\r\n")
    out.write(f"--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


def ci_meta() -> dict[str, str]:
    if os.environ.get("GITHUB_ACTIONS"):
        ref = os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME", "")
        pr = ""
        event_path = os.environ.get("GITHUB_EVENT_PATH")
        if event_path and Path(event_path).exists():
            try:
                pr = str(json.loads(Path(event_path).read_text()).get("number") or "")
            except ValueError:
                pr = ""
        return {"provider": "github", "repo": os.environ.get("GITHUB_REPOSITORY", ""), "ref": ref,
                "commit_sha": os.environ.get("GITHUB_SHA", ""), "pr": pr}
    if os.environ.get("GITLAB_CI"):
        return {"provider": "gitlab", "repo": os.environ.get("CI_PROJECT_PATH", ""),
                "ref": os.environ.get("CI_COMMIT_REF_NAME", ""), "commit_sha": os.environ.get("CI_COMMIT_SHA", ""),
                "pr": os.environ.get("CI_MERGE_REQUEST_IID", "")}
    return {"provider": "ci", "repo": "", "ref": "", "commit_sha": "", "pr": ""}


COMMENT_MARKER = "<!-- aisw-report -->"


def _scm_call(method: str, url: str, headers: dict[str, str], payload: dict | None = None) -> tuple[int, object]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={**headers, "User-Agent": "aisw-ci/1",
                                                                         "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - CI provider API from CI env
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, None


def _comment_target() -> tuple[str, dict[str, str], str, str] | None:
    """(list/create url, auth headers, update url template with {id}, update method) or None when not applicable."""
    if os.environ.get("GITHUB_ACTIONS"):
        token, repo = os.environ.get("GITHUB_TOKEN", ""), os.environ.get("GITHUB_REPOSITORY", "")
        pr = ci_meta().get("pr", "")
        if not (token and repo and pr.isdigit()):
            return None
        api = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
        return (f"{api}/repos/{repo}/issues/{pr}/comments", {"Authorization": f"Bearer {token}",
                                                             "Accept": "application/vnd.github+json"},
                f"{api}/repos/{repo}/issues/comments/{{id}}", "PATCH")
    if os.environ.get("GITLAB_CI"):
        token, iid = os.environ.get("GITLAB_TOKEN", ""), os.environ.get("CI_MERGE_REQUEST_IID", "")
        project = os.environ.get("CI_PROJECT_ID") or os.environ.get("CI_PROJECT_PATH", "")
        if not (token and project and iid.isdigit()):
            return None
        api = os.environ.get("CI_API_V4_URL", "https://gitlab.com/api/v4").rstrip("/")
        base = f"{api}/projects/{urllib.parse.quote(project, safe='')}/merge_requests/{iid}/notes"
        return base, {"PRIVATE-TOKEN": token}, base + "/{id}", "PUT"
    return None


def publish_comment(text: str) -> str:
    """Create or update (by marker) a single report comment on the PR/MR. Returns created|updated|skipped|failed."""
    target = _comment_target()
    if target is None:
        return "skipped"
    url, headers, update_url, update_method = target
    body = {"body": f"{COMMENT_MARKER}\n{text}"}
    code, existing = _scm_call("GET", url, headers)
    if code == 200 and isinstance(existing, list):
        for c in existing:
            if isinstance(c, dict) and COMMENT_MARKER in str(c.get("body", "")):
                code, _ = _scm_call(update_method, update_url.format(id=c["id"]), headers, body)
                return "updated" if code in (200, 201) else "failed"
    code, _ = _scm_call("POST", url, headers, body)
    return "created" if code in (200, 201) else "failed"


def render_summary(st: dict, verdict_body: dict | None = None) -> str:
    sev = st.get("summary", {}).get("by_severity", {})
    v = st.get("verdict") or {}
    verdict = v.get("verdict")
    lines = ["## AI Security Workflow", "",
             f"**Gate:** {'❌ FAIL' if st.get('gate') == 'fail' else '✅ PASS'}"
             + (f" · **Diff verdict:** {verdict}" if verdict else ""), "",
             "| CRITICAL | HIGH | MEDIUM | LOW | Всего |", "|---|---|---|---|---|",
             f"| {sev.get('CRITICAL', 0)} | {sev.get('HIGH', 0)} | {sev.get('MEDIUM', 0)} | {sev.get('LOW', 0)} | "
             f"{st.get('summary', {}).get('total', 0)} |", ""]
    new = (verdict_body or {}).get("new_findings") or []
    if verdict and v.get("diff_available"):
        lines.append(f"**Новые находки в этом diff:** {len(new)} (порог блокировки {v.get('threshold')})")
        if new:
            lines += ["", "| Severity | Находка | Где | Коммит |", "|---|---|---|---|"]
            for f in new[:30]:
                where = f"{f.get('path')}:{f.get('line')}"
                commit = (f.get("introduced_in_commit") or "")[:7] or "—"
                lines.append(f"| {f.get('severity')} | {f.get('title')} | `{where}` | `{commit}` |")
        lines += ["", f"ℹ️ {v.get('existing_count', 0)} существующих находок не блокируют.", ""]
    lines.append(f"Отчёт: {st.get('links', {}).get('ui', '')}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AI Security Workflow CI client")
    ap.add_argument("--url", default=os.environ.get("AISW_URL", ""))
    ap.add_argument("--token", default=os.environ.get("AISW_TOKEN", ""))
    ap.add_argument("--workflow", required=True)
    ap.add_argument("--path", default=".")
    ap.add_argument("--out", default="aisw-report")
    ap.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY", ""))
    ap.add_argument("--base", default=None, help="base branch for diff-aware scanning")
    ap.add_argument("--timeout", type=float, default=1800)
    ap.add_argument("--no-comment", action="store_true", help="do not post the report comment to the PR/MR")
    args = ap.parse_args(argv)
    if not args.url or not args.token:
        print("aisw: нужны --url и AISW_TOKEN", file=sys.stderr)
        return 2
    base = args.url.rstrip("/")
    root = Path(args.path).resolve()
    out = Path(args.out).resolve()
    try:
        archive = pack(root, out)
        fields = {"workflow_id": args.workflow, **ci_meta()}
        diff = diff_context(root, args.base)
        if diff:
            fields["diff_context"] = json.dumps(diff)
        body, ctype = multipart(fields, {"archive": ("source.zip", archive)})
        code, raw = request("POST", f"{base}/api/v1/ci/runs", args.token, body, ctype, timeout=300)
        if code != 202:
            raise PlatformError(f"запуск не создан: HTTP {code} {raw[:300].decode('utf-8', 'replace')}")
        run = json.loads(raw)
        print(f"aisw: запуск {run['id']} создан, ожидание результата…")
        deadline = time.monotonic() + args.timeout
        while True:
            code, raw = request("GET", f"{base}/api/v1/ci/runs/{run['id']}?wait=20", args.token, timeout=60)
            if code != 200:
                raise PlatformError(f"статус недоступен: HTTP {code}")
            st = json.loads(raw)
            if st["status"] in ("success", "failed", "cancelled"):
                break
            if time.monotonic() > deadline:
                raise PlatformError("превышено время ожидания результата")
        if st["status"] != "success":
            raise PlatformError(f"запуск завершился со статусом {st['status']}: {st.get('error') or ''}")
        out.mkdir(parents=True, exist_ok=True)
        for fmt, name in (("markdown", "report.md"), ("submission", "submission.json")):
            code, raw = request("GET", f"{base}/api/v1/ci/runs/{run['id']}/report?format={fmt}", args.token)
            if code == 200:
                (out / name).write_bytes(raw)
        verdict_body = None
        if (st.get("verdict") or {}).get("verdict"):
            code, raw = request("GET", f"{base}/api/v1/ci/runs/{run['id']}/verdict", args.token)
            if code in (200, 422):
                verdict_body = json.loads(raw)
        summary = render_summary(st, verdict_body)
        print(summary)
        if args.summary:
            with open(args.summary, "a", encoding="utf-8") as f:
                f.write(summary)
        if not args.no_comment:
            try:
                result = publish_comment(summary)
            except (urllib.error.URLError, OSError, ValueError) as e:
                result = f"failed ({e.__class__.__name__})"
            if result != "skipped":
                print(f"aisw: комментарий к PR/MR: {result}")
        verdict = (st.get("verdict") or {}).get("verdict")
        failed = verdict == "FAIL" if verdict in ("PASS", "FAIL") else st.get("gate") == "fail"
        print(f"aisw: gate: {'FAIL' if failed else 'PASS'}")
        return 1 if failed else 0
    except PlatformError as e:
        print(f"aisw: ошибка платформы: {e}", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError) as e:
        print(f"aisw: ошибка: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
