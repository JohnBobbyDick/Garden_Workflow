"""Local mock services for demos without internet (Compose profile ``mock``).

* Telegram Bot API (``/bot<token>/sendMessage``, ``/bot<token>/sendDocument``) on MOCK_HTTP_PORT (default 8025)
* HTTP webhook receiver (any other path) — verifies ``X-AISW-Signature`` when MOCK_WEBHOOK_SECRET is set
* SMTP sink (aiosmtpd) on MOCK_SMTP_PORT (default 2525)
* ``GET /_received`` lists everything received (JSON), ``DELETE /_received`` clears it.

Secrets are never printed: bot tokens in paths are masked in the log and in ``/_received``."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
import time
from email import message_from_bytes
from email.policy import default as default_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RECEIVED: list[dict] = []
LOCK = threading.Lock()
TOKEN_IN_PATH = re.compile(r"/bot[^/]+/")


def record(kind: str, **data) -> None:
    item = {"kind": kind, "at": time.time(), **data}
    with LOCK:
        RECEIVED.append(item)
    print(json.dumps({k: (v if k != "body" else str(v)[:300]) for k, v in item.items()}, ensure_ascii=False),
          flush=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet default logging (it would print bot tokens)
        pass

    def _json(self, code: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/_received"):
            with LOCK:
                return self._json(200, RECEIVED)
        self._json(404, {"ok": False})

    def do_DELETE(self):
        with LOCK:
            RECEIVED.clear()
        self._json(200, {"ok": True})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(min(n, 20 * 1024 * 1024))
        path = TOKEN_IN_PATH.sub("/bot•••/", self.path)
        if self.path.startswith("/bot"):
            method = self.path.rsplit("/", 1)[-1]
            text = ""
            if method == "sendMessage":
                try:
                    text = json.loads(body).get("text", "")
                except ValueError:
                    text = ""
            record("telegram", method=method, path=path, text=text, size=len(body))
            return self._json(200, {"ok": True, "result": {"message_id": len(RECEIVED)}})
        secret = os.environ.get("MOCK_WEBHOOK_SECRET", "")
        verified = None
        if secret and "X-AISW-Signature" in self.headers:
            ts = self.headers.get("X-AISW-Timestamp", "")
            want = "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
            verified = hmac.compare_digest(want, self.headers["X-AISW-Signature"])
        record("webhook", path=path, signature_valid=verified, body=body.decode("utf-8", "replace"))
        self._json(200, {"ok": True})

    do_PUT = do_POST


class MailSink:
    async def handle_DATA(self, server, session, envelope):  # noqa: N802 - aiosmtpd API
        msg = message_from_bytes(envelope.content, policy=default_policy)
        record("smtp", to=list(envelope.rcpt_tos), subject=str(msg.get("Subject", "")),
               attachments=[p.get_filename() for p in msg.iter_attachments()])
        return "250 OK"


def main() -> None:
    from aiosmtpd.controller import Controller

    host = os.environ.get("MOCK_HOST", "0.0.0.0")
    http_port = int(os.environ.get("MOCK_HTTP_PORT", "8025"))
    smtp_port = int(os.environ.get("MOCK_SMTP_PORT", "2525"))
    ctl = Controller(MailSink(), hostname=host, port=smtp_port, server_hostname="aisw-mock")
    ctl.start()
    srv = ThreadingHTTPServer((host, http_port), Handler)
    print(f"mock services: http://{host}:{http_port} (telegram + webhook), smtp {host}:{smtp_port}", flush=True)
    try:
        srv.serve_forever()
    finally:
        ctl.stop()


if __name__ == "__main__":
    main()
