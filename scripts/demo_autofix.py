"""AI AutoFix demo on a running stack (§12А.3).

1. Temp git repository with training-project on ``main`` (fixtures are never modified), mock GitHub, demo user,
   webhook + write token + allowlist (``allow_write`` only for the demo repository on the mock).
2. PR webhook → diff-aware run → finding «Встроенный пароль» → AutoFix → validation checklist + diff (password moved
   to an environment variable) → «Создать PR» → PR on the local mock GitHub (branch ``autofix/<finding_id>``).
3. The file pushed to the mock is committed to ``autofix/<id>`` in the temp repo → PR webhook for that branch →
   diff-aware verdict PASS, 0 new findings, one finding fewer.
4. Organizer training project (read-only): deterministic SCA AutoFix → only «Скачать .patch» (PR refused).

For reproducible offline testing, the demo LLM is a local Ollama-compatible endpoint that builds its
answer from the masked context it receives (marked as such in the output). Validator, self-check by all analyzers,
PR creation and the diff-aware re-check are the real product code.

The API must run with ``APP_SCAN_ROOTS=<repo>/fixtures,<demo root>`` and
``APP_SSRF_ALLOW_HOSTS=127.0.0.1:<mock port>,127.0.0.1:<llm port>``.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import mock_scm  # noqa: E402
from demo_diff import REPO_URL, TRAINING, git  # noqa: E402

WEBHOOK_SECRET = "demo-" + uuid.uuid4().hex


def demo_llm(port: int) -> ThreadingHTTPServer:
    """Local Ollama demo endpoint: moves the masked string literal of the finding line to an env var."""

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, payload: dict) -> None:
            raw = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path != "/api/tags":
                return self.send_error(404)
            self._send({"models": [{"name": "demo-llm"}]})

        def do_POST(self):
            if self.path != "/api/chat":
                return self.send_error(404)
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            ctx = json.loads(body["messages"][1]["content"])
            f = ctx["finding"]
            lines = {int(n): t for n, t in re.findall(r"^\s*(\d+)\| (.*)$", ctx["snippet"], re.M)}
            old = lines[f["start_line"]]
            m = re.match(r"^(\s*)(private |internal )?val (\w+)(\s*:\s*String)?\s*=\s*\".*\"\s*$", old)
            name = m.group(3) if m else "secret"
            env = re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper()
            new = f'{m.group(1) if m else ""}{(m.group(2) or "") if m else ""}val {name}: String = ' \
                  f'System.getenv("{env}") ?: error("{env} is not set")'
            answer = {"file": f["file"], "start_line": f["start_line"], "end_line": f["start_line"],
                      "old_snippet": old, "new_snippet": new,
                      "explanation": f"Пароль вынесен в переменную окружения {env} без значения по умолчанию; "
                                     "при отсутствии переменной приложение падает с понятной ошибкой. "
                                     "Скомпрометированный пароль нужно перевыпустить.",
                      "requires_config": [{"name": env, "description": "пароль импорта (из хранилища секретов)"}]}
            self._send({"model": "demo-llm", "done": True,
                        "message": {"role": "assistant", "content": json.dumps(answer)}})

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("AISW_URL", "http://localhost:8000"))
    ap.add_argument("--demo-root", default=os.environ.get("AISW_DEMO_ROOT", str(Path(tempfile.gettempdir()) / "aisw-demo")))
    ap.add_argument("--mock-port", type=int, default=int(os.environ.get("AISW_MOCK_SCM_PORT", "18090")))
    ap.add_argument("--llm-port", type=int, default=int(os.environ.get("AISW_DEMO_LLM_PORT", "18091")))
    args = ap.parse_args()

    demo_root = Path(args.demo_root)
    demo_root.mkdir(parents=True, exist_ok=True)
    repo = Path(tempfile.mkdtemp(prefix="autofix-", dir=demo_root))
    project = repo / "training-project"
    shutil.copytree(TRAINING, project)
    git(repo.parent, "init", "-q", "-b", "main", str(repo))
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "base: training project")
    base_sha = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "feature")
    git(repo, "commit", "-q", "--allow-empty", "-m", "chore: open PR")

    srv, state = mock_scm.start(port=args.mock_port)
    llm = demo_llm(args.llm_port)
    mock = f"http://127.0.0.1:{srv.server_address[1]}"
    print(f"[demo] mock GitHub {mock}; эмулятор Ollama http://127.0.0.1:{args.llm_port}")
    c = httpx.Client(base_url=args.url, timeout=120)
    reg = c.post("/api/auth/register", json={"email": f"autofix-{uuid.uuid4().hex[:6]}@example.org",
                                             "password": "Demo-Passw0rd!", "display_name": "autofix demo"})
    reg.raise_for_status()
    h = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    ws = c.get("/api/auth/me", headers=h).json()["workspaces"][0]["id"]
    cred = lambda name, kind, value: c.post("/api/credentials", headers=h, json={  # noqa: E731
        "workspace_id": ws, "name": name, "kind": kind, "value": value}).json()["id"]
    whs = cred("github webhook", "webhook_secret", WEBHOOK_SECRET)
    wtok = cred("github write token", "repo_write_token", "ghp_" + secrets.token_hex(18))
    c.put("/api/settings/allowlist", headers=h, json={"workspace_id": ws, "entries": [
        {"url": "https://github.com/TBagirov/training"},
        {"url": REPO_URL, "allow_write": True, "provider": "github", "api_base": mock,
         "write_credential_id": wtok}]}).raise_for_status()
    c.put("/api/settings/ai", headers=h, json={"workspace_id": ws, "enabled": True, "provider": "ollama",
                                               "base_url": f"http://127.0.0.1:{args.llm_port}", "model": "demo-llm",
                                               "allow_local": True}).raise_for_status()

    def graph(trigger: tuple, src: dict, diff: bool) -> dict:
        nodes = [trigger, ("src", "source.repo", src), ("sec", "scanner.secrets", {}), ("sca", "scanner.sca", {}),
                 ("sast", "scanner.sast", {}), ("merge", "logic.merge", {})]
        edges = [("t", "out", "src", "in"), ("src", "out", "sec", "in"), ("src", "out", "sca", "in"),
                 ("src", "out", "sast", "in"), ("sec", "out", "merge", "in"), ("sca", "out", "merge", "in"),
                 ("sast", "out", "merge", "in")]
        if diff:
            nodes.append(("diff", "scanner.diff", {"threshold": "HIGH"}))
            edges += [("src", "out", "diff", "repo"), ("merge", "out", "diff", "findings")]
        return {"schema_version": 1,
                "nodes": [{"id": i, "type": t, "position": {"x": 0, "y": 0}, "config": cfg} for i, t, cfg in nodes],
                "edges": [{"id": f"e{k}", "source": s, "source_port": sp, "target": d, "target_port": dp}
                          for k, (s, sp, d, dp) in enumerate(edges)]}

    trig = ("t", "trigger.webhook", {"provider": "github", "secret": whs, "repo_url": REPO_URL,
                                     "events": ["pull_request"]})
    c.post("/api/workflows", headers=h, json={"workspace_id": ws, "name": "PR: diff-aware + AutoFix",
                                              "graph": graph(trig, {"mode": "path", "path": str(project)}, True)}
           ).raise_for_status()

    def wait(rid: str) -> dict:
        for _ in range(600):
            run = c.get(f"/api/runs/{rid}", headers=h).json()
            if run["status"] in ("success", "failed", "cancelled"):
                time.sleep(1.0)
                return c.get(f"/api/runs/{rid}", headers=h).json()
            time.sleep(0.5)
        raise TimeoutError(rid)

    def deliver(number: int, head_ref: str) -> dict:
        body = json.dumps({"action": "opened", "number": number,
                           "repository": {"full_name": "demo/shop", "html_url": REPO_URL},
                           "pull_request": {"head": {"sha": git(repo, "rev-parse", "HEAD"), "ref": head_ref},
                                            "base": {"sha": base_sha, "ref": "main"}}}).encode()
        sig = "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        r = c.post("/api/v1/webhooks/github", content=body, headers={
            "X-GitHub-Event": "pull_request", "X-GitHub-Delivery": uuid.uuid4().hex, "X-Hub-Signature-256": sig,
            "Content-Type": "application/json"})
        r.raise_for_status()
        return wait(r.json()["run_ids"][0])

    run = deliver(7, "feature")
    v = run.get("verdict") or {}
    print(f"[demo] PR #7 → run {run['id'][:8]}: {run['status']}, verdict {v.get('verdict')}, "
          f"existing {v.get('existing_count')}")
    fs = c.get(f"/api/runs/{run['id']}/findings", headers=h).json()["findings"]
    pwd = next(f for f in fs if f["category"] == "SECRET" and f["class"] == "password")
    print(f"[demo] AutoFix → {pwd['title']} {pwd['path']}:{pwd['line']}")
    af = c.post(f"/api/runs/{run['id']}/findings/{pwd['id']}/autofix", headers=h, json={})
    af.raise_for_status()
    af = af.json()
    for st in af["steps"]:
        print(f"    {'✔' if st['ok'] else '✘'} {st['name']}: {st['detail']}")
    print(f"[demo] status {af['status']}; requires_config: {[r['name'] for r in af['proposal']['requires_config']]}")
    print("\n".join("    " + ln for ln in (af["patch"] or "").splitlines()))
    ok = af["status"] == "validated" and af["can_create_pr"]
    state.requests.clear()
    pr = c.post(f"/api/autofixes/{af['id']}/pull-request", headers=h, json={})
    pr.raise_for_status()
    pr = pr.json()
    print(f"[demo] PR on mock GitHub: {pr['url']} (branch {pr['branch']}); requests: "
          + ", ".join(f"{q['method']} {q['path'].split('/demo/shop', 1)[1]}" for q in state.requests))
    print("[demo] PR body:\n" + "\n".join("    " + ln for ln in state.pulls[0]["body"].splitlines()))

    # diff-aware run of the autofix branch: commit exactly what was pushed to the mock
    git(repo, "checkout", "-q", "-b", pr["branch"], base_sha)
    for key, content in state.files.items():
        rel = key.split(":", 1)[1]
        (repo / rel).write_text(content) if rel.startswith("training-project/") else (project / rel).write_text(content)
    git(repo, "commit", "-q", "-am", f"fix(security): {pwd['class']} ({pwd['id']})")
    run2 = deliver(8, pr["branch"])
    v2 = run2.get("verdict") or {}
    print(f"[demo] PR #8 ({pr['branch']}) → verdict {v2.get('verdict')}, new {v2.get('new_count')}, existing "
          f"{v2.get('existing_count')} (было {v.get('existing_count')})")
    ok = ok and v2.get("verdict") == "PASS" and v2.get("new_count") == 0 \
        and v2.get("existing_count") == v.get("existing_count", 0) - 1

    # organizer repository (read-only): deterministic SCA AutoFix → .patch only
    wf = c.post("/api/workflows", headers=h, json={"workspace_id": ws, "name": "Организаторы: аудит",
                                                   "graph": graph(("t", "trigger.manual", {}),
                                                                  {"mode": "path", "path": str(TRAINING)}, False)})
    wf.raise_for_status()
    run3 = wait(c.post(f"/api/workflows/{wf.json()['id']}/run", headers=h, json={}).json()["id"])
    sca = next(f for f in c.get(f"/api/runs/{run3['id']}/findings", headers=h).json()["findings"]
               if f.get("artifact") == "commons-text")
    af3 = c.post(f"/api/runs/{run3['id']}/findings/{sca['id']}/autofix", headers=h, json={}).json()
    patch = c.get(f"/api/autofixes/{af3['id']}/patch", headers=h)
    print(f"[demo] training-project (организаторы): SCA AutoFix {af3['status']}, PR: {af3['pr_unavailable_reason']}")
    print("\n".join("    " + ln for ln in patch.text.splitlines()))
    ok = ok and af3["status"] == "validated" and not af3["can_create_pr"] and patch.status_code == 200
    srv.shutdown()
    llm.shutdown()
    shutil.rmtree(repo, ignore_errors=True)
    print("[demo] OK" if ok else "[demo] FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
