"""Real local HTTP servers speaking the OpenAI-compatible and Ollama chat APIs, with scripted replies (tests only)."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Script:
    def __init__(self) -> None:
        self.replies: list[dict] = []  # {"status", "content" | "body", "delay", "headers"}
        self.requests: list[dict] = []
        self.default: dict | None = None
        self.dynamic = None  # callable(request_body) -> content, used when no scripted reply is queued

    def reply(self, content=None, status=200, delay=0.0, body=None, headers=None):
        self.replies.append({"status": status, "content": content, "delay": delay, "body": body,
                             "headers": headers or {}})
        return self


def _content_text(content) -> str:
    return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)


def make_server(kind: str = "openai"):
    script = Script()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, status, payload, headers=None):
            raw = json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path.endswith("/models"):
                return self._send(200, {"data": [{"id": "test-model"}, {"id": "other"}]})
            if self.path.endswith("/api/tags"):
                return self._send(200, {"models": [{"name": "qwen2.5:3b"}]})
            self._send(404, {"error": "nope"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            script.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
            r = script.replies.pop(0) if script.replies else script.default
            if r is None and script.dynamic is not None:
                r = {"status": 200, "content": script.dynamic(body), "delay": 0, "body": None, "headers": {}}
            if r is None:
                return self._send(500, {"error": "no scripted reply"})
            if r["delay"]:
                time.sleep(r["delay"])
            if r["body"] is not None:
                return self._send(r["status"], r["body"], r["headers"])
            if r["status"] != 200:
                return self._send(r["status"], {"error": {"message": "scripted error"}}, r["headers"])
            text = _content_text(r["content"])
            if kind == "ollama":
                return self._send(200, {"model": body.get("model"), "message": {"role": "assistant", "content": text},
                                        "prompt_eval_count": 11, "eval_count": 22, "done": True})
            return self._send(200, {"id": "x", "model": body.get("model"),
                                    "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                                                 "finish_reason": "stop"}],
                                    "usage": {"prompt_tokens": 11, "completion_tokens": 22, "total_tokens": 33}})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, script, f"127.0.0.1:{srv.server_address[1]}"
