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
import subprocess
import sys
import time
import urllib.error
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


def diff_context(root: Path, base_ref: str | None) -> dict | None:
    """git diff from the merge base + base versions of build files + blame of changed lines (if history exists)."""
    head = (git("rev-parse", "HEAD", cwd=root) or "").strip()
    if not head:
        return None
    base = base_ref or os.environ.get("GITHUB_BASE_REF") or os.environ.get("CI_MERGE_REQUEST_TARGET_BRANCH_NAME") or "main"
    candidates = [f"origin/{base}", base]
    merge_base = None
    for c in candidates:
        mb = git("merge-base", c, "HEAD", cwd=root)
        if mb:
            merge_base = mb.strip()
            break
    if not merge_base:
        return None
    top = (git("rev-parse", "--show-toplevel", cwd=root) or "").strip()
    prefix = Path(root).resolve().relative_to(Path(top).resolve()).as_posix() if top else ""
    prefix = "" if prefix == "." else prefix
    diff = git("diff", "--unified=0", "--find-renames", "-w", "--ignore-blank-lines", f"{merge_base}...HEAD",
               "--", ".", cwd=root) or ""
    base_files = {}
    for f in BUILD_FILES:
        rel = f"{prefix}/{f}" if prefix else f
        content = git("show", f"{merge_base}:{rel}", cwd=root)
        if content is not None:
            base_files[f] = content
    return {"base_sha": merge_base, "head_sha": head, "merge_base": merge_base, "diff": diff[:5_000_000],
            "path_prefix": prefix, "base_files": base_files}


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


def render_summary(st: dict) -> str:
    sev = st.get("summary", {}).get("by_severity", {})
    verdict = (st.get("verdict") or {}).get("verdict")
    lines = ["## AI Security Workflow", "",
             f"**Gate:** {'❌ FAIL' if st.get('gate') == 'fail' else '✅ PASS'}"
             + (f" · **Diff verdict:** {verdict}" if verdict else ""), "",
             "| CRITICAL | HIGH | MEDIUM | LOW | Всего |", "|---|---|---|---|---|",
             f"| {sev.get('CRITICAL', 0)} | {sev.get('HIGH', 0)} | {sev.get('MEDIUM', 0)} | {sev.get('LOW', 0)} | "
             f"{st.get('summary', {}).get('total', 0)} |", "", f"Отчёт: {st.get('links', {}).get('ui', '')}"]
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
        summary = render_summary(st)
        print(summary)
        if args.summary:
            with open(args.summary, "a", encoding="utf-8") as f:
                f.write(summary)
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
