"""Diff-aware demo on a running stack (§12А.1).

1. Copies training-project into a temporary git repository (fixtures are never modified): base commit with the 15
   reference findings on ``main``.
2. Branch ``feature`` adds a synthetic AWS key generated here (random, not ``EXAMPLE``; it lives only in the temp repo).
3. Starts a local mock GitHub, registers a demo user, configures the webhook secret, a write token and the allowlist
   entry pointing at the mock, creates the workflow ``webhook → source → [secrets, sca, sast] → merge → scanner.diff
   → ci_gate``.
4. Delivers a signed ``pull_request.opened`` → FAIL, commit status ``failure``, PR comment.
5. Removes the key (revert commit), delivers ``synchronize`` → PASS, the same comment is updated; 15 old = existing.

The API server must see the temp repo and the mock:
``APP_SCAN_ROOTS=<repo>/fixtures,<demo root>`` and ``APP_SSRF_ALLOW_HOSTS=127.0.0.1:<mock port>``.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import shutil
import string
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import mock_scm  # noqa: E402

TRAINING = ROOT / "fixtures" / "organizer-training" / "training-project"
REPO_URL = "https://github.com/demo/shop"
WEBHOOK_SECRET = "demo-" + uuid.uuid4().hex


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=Demo Dev", "-c", "user.email=dev@example.com", "-c",
                           "commit.gpgsign=false", *args], cwd=repo, check=True, capture_output=True,
                          text=True).stdout.strip()


def synthetic_aws_key() -> tuple[str, str]:
    alnum = string.ascii_uppercase + string.digits
    return ("AKIA" + "".join(secrets.choice(alnum) for _ in range(16)),
            "".join(secrets.choice(string.ascii_letters + string.digits + "/+") for _ in range(40)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("AISW_URL", "http://localhost:8000"))
    ap.add_argument("--demo-root", default=os.environ.get("AISW_DEMO_ROOT", str(Path(tempfile.gettempdir()) / "aisw-demo")))
    ap.add_argument("--mock-port", type=int, default=int(os.environ.get("AISW_MOCK_SCM_PORT", "18090")))
    args = ap.parse_args()

    demo_root = Path(args.demo_root)
    demo_root.mkdir(parents=True, exist_ok=True)
    repo = Path(tempfile.mkdtemp(prefix="diff-", dir=demo_root))
    project = repo / "training-project"
    shutil.copytree(TRAINING, project)
    git(repo.parent, "init", "-q", "-b", "main", str(repo))
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "base: training project (15 known findings)")
    base_sha = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "feature")
    target = next((project / "src" / "main" / "kotlin").rglob("*.kt"))
    key_id, key_secret = synthetic_aws_key()
    target.write_text(target.read_text() + f'\nval awsAccessKeyId = "{key_id}"\nval awsSecretAccessKey = "{key_secret}"\n')
    git(repo, "commit", "-q", "-am", "feat: upload reports to S3")
    print(f"[demo] temp repo {repo}: base {base_sha[:7]}, feature adds an AWS key to {target.relative_to(project)}")

    srv, state = mock_scm.start(port=args.mock_port)
    mock = f"http://127.0.0.1:{srv.server_address[1]}"
    print(f"[demo] mock GitHub on {mock}")
    c = httpx.Client(base_url=args.url, timeout=60)
    email = f"diff-demo-{uuid.uuid4().hex[:6]}@example.org"
    reg = c.post("/api/auth/register", json={"email": email, "password": "Demo-Passw0rd!", "display_name": "diff demo"})
    reg.raise_for_status()
    h = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    ws = c.get("/api/auth/me", headers=h).json()["workspaces"][0]["id"]
    whs = c.post("/api/credentials", headers=h, json={"workspace_id": ws, "name": "github webhook",
                                                     "kind": "webhook_secret", "value": WEBHOOK_SECRET}).json()["id"]
    wtok = c.post("/api/credentials", headers=h, json={"workspace_id": ws, "name": "github write token",
                                                      "kind": "repo_write_token",
                                                      "value": "ghp_" + secrets.token_hex(18)}).json()["id"]
    c.put("/api/settings/allowlist", headers=h, json={"workspace_id": ws, "entries": [
        {"url": "https://github.com/TBagirov/training"},
        {"url": REPO_URL, "allow_write": True, "provider": "github", "api_base": mock,
         "write_credential_id": wtok}]}).raise_for_status()
    nodes = [("t", "trigger.webhook", {"provider": "github", "secret": whs, "repo_url": REPO_URL,
                                       "events": ["pull_request"]}),
             ("src", "source.repo", {"mode": "path", "path": str(project)}),
             ("sec", "scanner.secrets", {}), ("sca", "scanner.sca", {}), ("sast", "scanner.sast", {}),
             ("merge", "logic.merge", {}), ("diff", "scanner.diff", {"threshold": "CRITICAL"}),
             ("gate", "output.ci_gate", {"fail_on": "CRITICAL"})]
    edges = [("t", "out", "src", "in"), ("src", "out", "sec", "in"), ("src", "out", "sca", "in"),
             ("src", "out", "sast", "in"), ("sec", "out", "merge", "in"), ("sca", "out", "merge", "in"),
             ("sast", "out", "merge", "in"), ("src", "out", "diff", "repo"), ("merge", "out", "diff", "findings"),
             ("merge", "out", "gate", "in"), ("diff", "verdict", "gate", "verdict")]
    graph = {"schema_version": 1,
             "nodes": [{"id": i, "type": t, "position": {"x": 0, "y": 0}, "config": cfg} for i, t, cfg in nodes],
             "edges": [{"id": f"e{k}", "source": s, "source_port": sp, "target": d, "target_port": dp}
                       for k, (s, sp, d, dp) in enumerate(edges)]}
    wf = c.post("/api/workflows", headers=h, json={"workspace_id": ws, "name": "Diff-aware PR gate", "graph": graph})
    wf.raise_for_status()

    def deliver(action: str) -> dict:
        head = git(repo, "rev-parse", "HEAD")
        body = json.dumps({"action": action, "number": 42,
                           "repository": {"full_name": "demo/shop", "html_url": REPO_URL},
                           "pull_request": {"head": {"sha": head, "ref": "feature"},
                                            "base": {"sha": base_sha, "ref": "main"}}}).encode()
        sig = "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        r = c.post("/api/v1/webhooks/github", content=body, headers={
            "X-GitHub-Event": "pull_request", "X-GitHub-Delivery": uuid.uuid4().hex,
            "X-Hub-Signature-256": sig, "Content-Type": "application/json"})
        r.raise_for_status()
        rid = r.json()["run_ids"][0]
        for _ in range(600):
            run = c.get(f"/api/runs/{rid}", headers=h).json()
            if run["status"] in ("success", "failed", "cancelled"):
                break
            time.sleep(0.5)
        time.sleep(1.0)  # post-run hook writes the status and comment right after completion
        return run

    run = deliver("opened")
    v = run.get("verdict") or {}
    print(f"[demo] PR opened → run {run['id']}: {run['status']}, verdict {v.get('verdict')}, "
          f"new {v.get('new_count')}, existing {v.get('existing_count')}")
    statuses = [q for q in state.requests if "/statuses/" in q["path"]]
    print(f"[demo] commit status: {statuses[-1]['body']['state']} — {statuses[-1]['body']['description']}")
    comment = state.comments.get("gh:demo/shop#42", [{}])[0].get("body", "")
    print("[demo] PR comment:\n" + "\n".join("    " + line for line in comment.splitlines()))
    ok1 = v.get("verdict") == "FAIL" and statuses[-1]["body"]["state"] == "failure"

    git(repo, "revert", "--no-edit", "HEAD")
    run = deliver("synchronize")
    v = run.get("verdict") or {}
    statuses = [q for q in state.requests if "/statuses/" in q["path"]]
    comments = state.comments.get("gh:demo/shop#42", [])
    print(f"[demo] key removed, push → run {run['id']}: verdict {v.get('verdict')}, new {v.get('new_count')}, "
          f"existing {v.get('existing_count')}; status {statuses[-1]['body']['state']}; "
          f"comments on PR: {len(comments)} (updated in place)")
    print("[demo] PR comment now:\n" + "\n".join("    " + line for line in comments[0]["body"].splitlines()))
    ok2 = v.get("verdict") == "PASS" and len(comments) == 1 and v.get("existing_count") == 15
    srv.shutdown()
    shutil.rmtree(repo, ignore_errors=True)
    print("[demo] OK" if ok1 and ok2 else "[demo] FAILED")
    return 0 if ok1 and ok2 else 1


if __name__ == "__main__":
    sys.exit(main())
