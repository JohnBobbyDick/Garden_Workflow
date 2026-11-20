"""End-to-end smoke demo against a running stack (docker compose with the ``mock`` profile, or a dev stack).

Registers a user, creates a project from the organizer training project (directory inside APP_SCAN_ROOTS), builds
``manual → source → [secrets, sca, sast] → merge → if_else(severity.max >= HIGH) → ai.report → report_export +
notify.webhook`` (false branch → notify.webhook), runs it and checks: 15 findings, webhook delivered to the mock,
``submission.json`` exported, Security Score recorded. Only the standard library + httpx (backend venv) are used.

    python scripts/demo_stack.py --url http://localhost:8080 --mock http://localhost:8025
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid

import httpx


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("AISW_URL", "http://localhost:8080"))
    ap.add_argument("--mock", default=os.environ.get("AISW_MOCK_URL", "http://localhost:8025"),
                    help="mock receiver as seen from this machine")
    ap.add_argument("--mock-internal", default=os.environ.get("AISW_MOCK_INTERNAL", "http://mock:8025"),
                    help="mock receiver as seen from the backend/worker")
    ap.add_argument("--path", default=os.environ.get("AISW_DEMO_PATH",
                                                     "/app/fixtures/organizer-training/training-project"))
    args = ap.parse_args()
    c = httpx.Client(base_url=args.url, timeout=60)
    email = f"demo-{uuid.uuid4().hex[:6]}@example.org"
    reg = c.post("/api/auth/register", json={"email": email, "password": "Demo-Passw0rd!", "display_name": "demo"})
    reg.raise_for_status()
    h = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    ws = c.get("/api/auth/me", headers=h).json()["workspaces"][0]["id"]
    print(f"[demo] user {email}, workspace {ws}")
    pid = c.post("/api/projects", headers=h, json={"workspace_id": ws, "name": "training-project",
                                                   "source_mode": "path", "path": args.path})
    pid.raise_for_status()
    pid = pid.json()["id"]
    hook = f"{args.mock_internal}/aisw-demo-{uuid.uuid4().hex[:6]}"
    nodes = [("t", "trigger.manual", {}), ("src", "source.repo", {"mode": "project"}),
             ("sec", "scanner.secrets", {}), ("sca", "scanner.sca", {}), ("sast", "scanner.sast", {}),
             ("merge", "logic.merge", {}), ("score", "analysis.security_score", {}),
             ("if", "logic.if_else", {"expression": "severity.max >= HIGH"}),
             ("ai", "ai.report", {}), ("exp", "output.report_export", {}),
             ("hook", "notify.webhook", {"url": hook}), ("ok", "notify.webhook", {"url": hook + "-clean"})]
    edges = [("t", "out", "src", "in"), ("src", "out", "sec", "in"), ("src", "out", "sca", "in"),
             ("src", "out", "sast", "in"), ("sec", "out", "merge", "in"), ("sca", "out", "merge", "in"),
             ("sast", "out", "merge", "in"), ("merge", "out", "score", "findings"), ("src", "out", "score", "repo"),
             ("merge", "out", "if", "in"), ("if", "true", "ai", "in"), ("if", "true", "exp", "in"), ("ai", "out", "exp", "ai"),
             ("exp", "out", "hook", "in"), ("if", "false", "ok", "in")]
    graph = {"schema_version": 1,
             "nodes": [{"id": i, "type": t, "position": {"x": 0, "y": 0}, "config": cfg} for i, t, cfg in nodes],
             "edges": [{"id": f"e{k}", "source": s, "source_port": sp, "target": d, "target_port": dp}
                       for k, (s, sp, d, dp) in enumerate(edges)]}
    wf = c.post("/api/workflows", headers=h, json={"workspace_id": ws, "name": "Демо: полный аудит", "graph": graph,
                                                   "project_id": pid})
    if wf.status_code >= 400:
        print(wf.text)
        return 1
    started = c.post(f"/api/workflows/{wf.json()['id']}/run", headers=h, json={})
    if started.status_code >= 400:
        print(started.text)
        return 1
    rid = started.json()["id"]
    for _ in range(600):
        run = c.get(f"/api/runs/{rid}", headers=h).json()
        if run["status"] in ("success", "failed", "cancelled"):
            break
        time.sleep(0.5)
    time.sleep(1)
    run = c.get(f"/api/runs/{rid}", headers=h).json()
    print(f"[demo] run {rid}: {run['status']} {run.get('error') or ''}; findings {run['summary'].get('total')}, "
          f"by severity {run['summary'].get('by_severity')}; score {run.get('score')}")
    arts = {a["name"]: a["url"] for a in run.get("artifacts", [])}
    sub = c.get(arts["submission.json"], headers=h) if "submission.json" in arts else None
    official = len(json.loads(sub.text)["findings"]) if sub is not None and sub.status_code == 200 else None
    received = httpx.get(f"{args.mock}/_received", timeout=10).json()
    hits = [r for r in received if r.get("kind") == "webhook" and hook.rsplit("/", 1)[1] in r.get("path", "")]
    print(f"[demo] artifacts: {sorted(arts)}; submission.json findings: {official}; webhook deliveries: {len(hits)}")
    ok = run["status"] == "success" and run["summary"].get("total") == 15 and official == 15 and hits \
        and run.get("score") is not None
    print("[demo] OK" if ok else "[demo] FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
