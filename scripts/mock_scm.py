"""Local mock of the GitHub REST and GitLab REST APIs (subset used by AI Security Workflow).

Real HTTP with in-memory state, used by tests and the Compose ``mock`` profile. Nothing here ever talks to the real
GitHub/GitLab — the organizer repository and fixtures are never written to.

GitHub:  POST /repos/{o}/{r}/statuses/{sha}; GET/POST /repos/{o}/{r}/issues/{n}/comments;
         PATCH /repos/{o}/{r}/issues/comments/{id}; GET /repos/{o}/{r}/git/ref/heads/{b};
         POST /repos/{o}/{r}/git/refs; GET/PUT /repos/{o}/{r}/contents/{path}; GET/POST /repos/{o}/{r}/pulls
GitLab:  POST /projects/{id}/statuses/{sha}; GET/POST /projects/{id}/merge_requests/{iid}/notes;
         PUT /projects/{id}/merge_requests/{iid}/notes/{nid}; POST /projects/{id}/repository/branches;
         GET /projects/{id}/repository/files/{path}; POST /projects/{id}/repository/commits;
         GET/POST /projects/{id}/merge_requests
Inspection: GET /_requests (all requests), DELETE /_requests.
"""

from __future__ import annotations

import base64
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests: list[dict] = []
        self.comments: dict[str, list[dict]] = {}
        self.refs: dict[str, str] = {}
        self.files: dict[str, str] = {}
        self.pulls: list[dict] = []
        self.seq = 100

    def next_id(self) -> int:
        self.seq += 1
        return self.seq


def make_handler(state: State):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, payload) -> None:
            raw = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _record(self, body) -> tuple[str, dict]:
            parts = urlsplit(self.path)
            with state.lock:
                state.requests.append({"method": self.command, "path": unquote(parts.path), "query": parse_qs(parts.query),
                                       "headers": {k: v for k, v in self.headers.items()}, "body": body})
            return unquote(parts.path), parse_qs(parts.query)

        def _body(self):
            n = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(n) if n else b""
            try:
                return json.loads(raw) if raw else {}
            except ValueError:
                return {"_raw": raw.decode("utf-8", "replace")}

        def do_GET(self):
            path, _ = self._record(None)
            if path == "/_requests":
                with state.lock:
                    return self._send(200, state.requests)
            if m := re.match(r"^/(?:api/v3/)?repos/([^/]+/[^/]+)/issues/(\d+)/comments$", path):
                return self._send(200, state.comments.get(f"gh:{m[1]}#{m[2]}", []))
            if m := re.match(r"^/(?:api/v4/)?projects/(.+?)/merge_requests/(\d+)/notes$", path):
                return self._send(200, state.comments.get(f"gl:{m[1]}!{m[2]}", []))
            if m := re.match(r"^/repos/([^/]+/[^/]+)/git/ref/heads/(.+)$", path):
                sha = state.refs.get(f"{m[1]}:{m[2]}", "a" * 40 if m[2] in ("main", "master") else None)
                return self._send(200, {"ref": f"refs/heads/{m[2]}", "object": {"sha": sha}}) if sha else \
                    self._send(404, {"message": "Not Found"})
            if m := re.match(r"^/repos/([^/]+/[^/]+)/contents/(.+)$", path):
                content = state.files.get(f"{m[1]}:{m[2]}", "")
                return self._send(200, {"sha": "b" * 40, "path": m[2],
                                        "content": base64.b64encode(content.encode()).decode()})
            if m := re.match(r"^/repos/([^/]+/[^/]+)/pulls$", path):
                return self._send(200, [p for p in state.pulls if p.get("repo") == m[1]])
            if m := re.match(r"^/projects/(.+?)/merge_requests$", path):
                return self._send(200, [p for p in state.pulls if p.get("repo") == m[1]])
            if m := re.match(r"^/projects/(.+?)/repository/files/(.+)$", path):
                return self._send(200, {"file_path": m[2], "content": base64.b64encode(
                    state.files.get(f"{m[1]}:{m[2]}", "").encode()).decode()})
            self._send(404, {"message": "Not Found"})

        def do_DELETE(self):
            with state.lock:
                state.requests.clear()
            self._send(200, {"ok": True})

        def do_POST(self):
            body = self._body()
            path, query = self._record(body)
            with state.lock:
                if re.match(r"^/(?:api/v3/)?repos/[^/]+/[^/]+/statuses/[0-9a-f]{7,40}$", path):
                    return self._send(201, {"id": state.next_id(), "state": body.get("state")})
                if re.match(r"^/(?:api/v4/)?projects/.+?/statuses/[0-9a-f]{7,40}$", path):
                    return self._send(201, {"id": state.next_id(), "status": (query.get("state") or [body.get("state")])[0]})
                if m := re.match(r"^/(?:api/v3/)?repos/([^/]+/[^/]+)/issues/(\d+)/comments$", path):
                    c = {"id": state.next_id(), "body": body.get("body", "")}
                    state.comments.setdefault(f"gh:{m[1]}#{m[2]}", []).append(c)
                    return self._send(201, c)
                if m := re.match(r"^/(?:api/v4/)?projects/(.+?)/merge_requests/(\d+)/notes$", path):
                    c = {"id": state.next_id(), "body": body.get("body", "")}
                    state.comments.setdefault(f"gl:{m[1]}!{m[2]}", []).append(c)
                    return self._send(201, c)
                if m := re.match(r"^/repos/([^/]+/[^/]+)/git/refs$", path):
                    key = f"{m[1]}:{body.get('ref', '').removeprefix('refs/heads/')}"
                    if key in state.refs:
                        return self._send(422, {"message": "Reference already exists"})
                    state.refs[key] = body.get("sha", "")
                    return self._send(201, {"ref": body.get("ref"), "object": {"sha": body.get("sha")}})
                if m := re.match(r"^/repos/([^/]+/[^/]+)/pulls$", path):
                    for p in state.pulls:
                        if p["repo"] == m[1] and p["head"] == body.get("head"):
                            return self._send(422, {"message": "A pull request already exists"})
                    p = {"repo": m[1], "number": state.next_id(), "head": body.get("head"), "base": body.get("base"),
                         "title": body.get("title"), "body": body.get("body"),
                         "html_url": f"http://mock/{m[1]}/pull/{state.seq}"}
                    state.pulls.append(p)
                    return self._send(201, p)
                if m := re.match(r"^/repos/([^/]+/[^/]+)/issues/(\d+)/labels$", path):
                    return self._send(200, [{"name": n} for n in body.get("labels", [])])
                if m := re.match(r"^/projects/(.+?)/repository/branches$", path):
                    key = f"{m[1]}:{(query.get('branch') or [body.get('branch')])[0]}"
                    if key in state.refs:
                        return self._send(400, {"message": "Branch already exists"})
                    state.refs[key] = "c" * 40
                    return self._send(201, {"name": key.split(":", 1)[1]})
                if m := re.match(r"^/projects/(.+?)/repository/commits$", path):
                    for a in body.get("actions", []):
                        state.files[f"{m[1]}:{a.get('file_path')}"] = a.get("content", "")
                    return self._send(201, {"id": "d" * 40})
                if m := re.match(r"^/projects/(.+?)/merge_requests$", path):
                    for p in state.pulls:
                        if p["repo"] == m[1] and p["head"] == body.get("source_branch"):
                            return self._send(409, {"message": "Another open merge request already exists"})
                    p = {"repo": m[1], "iid": state.next_id(), "head": body.get("source_branch"),
                         "base": body.get("target_branch"), "title": body.get("title"),
                         "web_url": f"http://mock/{m[1]}/-/merge_requests/{state.seq}"}
                    state.pulls.append(p)
                    return self._send(201, p)
            self._send(404, {"message": "Not Found"})

        def do_PATCH(self):
            body = self._body()
            path, _ = self._record(body)
            if m := re.match(r"^/(?:api/v3/)?repos/([^/]+/[^/]+)/issues/comments/(\d+)$", path):
                with state.lock:
                    for lst in state.comments.values():
                        for c in lst:
                            if str(c["id"]) == m[2]:
                                c["body"] = body.get("body", "")
                                return self._send(200, c)
            self._send(404, {"message": "Not Found"})

        def do_PUT(self):
            body = self._body()
            path, _ = self._record(body)
            with state.lock:
                if m := re.match(r"^/(?:api/v4/)?projects/(.+?)/merge_requests/(\d+)/notes/(\d+)$", path):
                    for c in state.comments.get(f"gl:{m[1]}!{m[2]}", []):
                        if str(c["id"]) == m[3]:
                            c["body"] = body.get("body", "")
                            return self._send(200, c)
                if m := re.match(r"^/repos/([^/]+/[^/]+)/contents/(.+)$", path):
                    state.files[f"{m[1]}:{m[2]}"] = base64.b64decode(body.get("content", "")).decode("utf-8", "replace")
                    return self._send(200, {"commit": {"sha": "e" * 40}, "content": {"path": m[2]}})
            self._send(404, {"message": "Not Found"})

    return H


def start(host: str = "127.0.0.1", port: int = 0) -> tuple[ThreadingHTTPServer, State]:
    state = State()
    srv = ThreadingHTTPServer((host, port), make_handler(state))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, state


if __name__ == "__main__":
    srv, _ = start(os.environ.get("MOCK_HOST", "0.0.0.0"), int(os.environ.get("MOCK_SCM_PORT", "8026")))
    print(f"mock GitHub/GitLab API on {srv.server_address}", flush=True)
    threading.Event().wait()
