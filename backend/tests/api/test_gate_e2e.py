"""Phase-2 gate: manual → source → [secrets, sca, sast] → merge → if_else → notify (+export) end-to-end via the API,
with Telegram/SMTP/Webhook deliveries checked on real local servers."""

import hashlib
import hmac
import json
import socket
import threading
import time
from email import message_from_bytes
from email.policy import default as default_policy
from http.server import ThreadingHTTPServer

import pytest
from aiosmtpd.controller import Controller

from app.config import get_settings
from app.export.validator import validate_submission
from tests.api.conftest import drain
from tests.nodes.conftest import TRAINING
from tests.nodes.test_notify_nodes import BOT_TOKEN, MailSink, Recorder


@pytest.fixture
def mocks(monkeypatch):
    class H(Recorder):
        requests = []
    http = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        smtp_port = s.getsockname()[1]
    mail = MailSink()
    ctl = Controller(mail, hostname="127.0.0.1", port=smtp_port, server_hostname="localhost")
    ctl.start()
    hp = f"127.0.0.1:{http.server_address[1]}"
    monkeypatch.setenv("APP_SSRF_ALLOW_HOSTS", f"{hp},127.0.0.1:{smtp_port}")
    monkeypatch.setenv("APP_TELEGRAM_API_BASE", f"http://{hp}")
    get_settings.cache_clear()
    yield {"http": hp, "requests": H.requests, "smtp_port": smtp_port, "mail": mail}
    ctl.stop()
    http.shutdown()
    get_settings.cache_clear()


def cred(client, user, name, kind, value):
    r = client.post("/api/credentials", json={"workspace_id": user.workspace_id, "name": name, "kind": kind,
                                              "value": value}, headers=user.headers)
    assert r.status_code == 201
    return r.json()["id"]


def build(mocks, tg, hm, expression):
    nodes = [
        ("t", "trigger.manual", {}), ("src", "source.repo", {"mode": "path", "path": str(TRAINING)}),
        ("sec", "scanner.secrets", {}), ("sca", "scanner.sca", {}), ("sast", "scanner.sast", {}),
        ("merge", "logic.merge", {}), ("if", "logic.if_else", {"expression": expression}),
        ("tg", "notify.telegram", {"bot_token": tg, "chat_id": "42"}),
        ("mail", "notify.smtp", {"host": "127.0.0.1", "port": mocks["smtp_port"], "security": "none",
                                 "from_addr": "aisw@example.org", "to": ["team@example.org"]}),
        ("exp", "output.report_export", {}),
        ("hook", "notify.webhook", {"url": f"http://{mocks['http']}/hook", "hmac_secret": hm}),
    ]
    edges = [("t", "out", "src", "in"), ("src", "out", "sec", "in"), ("src", "out", "sca", "in"),
             ("src", "out", "sast", "in"), ("sec", "out", "merge", "in"), ("sca", "out", "merge", "in"),
             ("sast", "out", "merge", "in"), ("merge", "out", "if", "in"), ("if", "true", "exp", "in"),
             ("exp", "out", "tg", "in"), ("if", "true", "tg", "in"), ("if", "true", "mail", "in"),
             ("exp", "out", "mail", "in"), ("if", "false", "hook", "in")]
    return {"schema_version": 1,
            "nodes": [{"id": i, "type": t, "position": {"x": 0, "y": 0}, "config": c} for i, t, c in nodes],
            "edges": [{"id": f"e{k}", "source": s, "source_port": sp, "target": d, "target_port": dp}
                      for k, (s, sp, d, dp) in enumerate(edges)]}


def test_gate_true_branch_telegram_smtp_export(client, db, alice, mocks):
    tg = cred(client, alice, "tg", "telegram", BOT_TOKEN)
    hm = cred(client, alice, "hm", "webhook_secret", "gate-hmac-secret-123")
    g = build(mocks, tg, hm, "severity.max >= HIGH")
    wid = client.post("/api/workflows", json={"name": "gate", "graph": g, "workspace_id": alice.workspace_id},
                      headers=alice.headers).json()["id"]
    assert client.post(f"/api/workflows/{wid}/validate", headers=alice.headers).json()["valid"] is True
    rid = client.post(f"/api/workflows/{wid}/run", headers=alice.headers).json()["id"]
    drain(db)
    run = client.get(f"/api/runs/{rid}", headers=alice.headers).json()
    st = {n["node_id"]: n["status"] for n in run["nodes"]}
    assert run["status"] == "success", run["error"]
    assert st["tg"] == st["mail"] == st["exp"] == "success" and st["hook"] == "skipped"
    assert {n["channel"]: n["status"] for n in run["notifications"]} == {"telegram": "delivered", "smtp": "delivered"}
    tg_msgs = [json.loads(r["body"])["text"] for r in mocks["requests"] if r["path"].endswith("/sendMessage")]
    assert any("15" in t and "sql-injection" in t for t in tg_msgs)
    assert any(r["path"].endswith("/sendDocument") and b"report.md" in r["body"] for r in mocks["requests"])
    deadline = time.time() + 5
    while not mocks["mail"].messages and time.time() < deadline:
        time.sleep(0.05)
    letter = message_from_bytes(mocks["mail"].messages[0].content, policy=default_policy)
    assert {"report.html", "report.md"} <= {p.get_filename() for p in letter.iter_attachments()}
    sub = client.get(f"/api/runs/{rid}/export/submission.json", headers=alice.headers).json()
    assert validate_submission(sub) == [] and len(sub["findings"]) == 15
    # no secret leaks into stored events / API answers
    events = client.get(f"/api/runs/{rid}/events", headers=alice.headers).text
    assert BOT_TOKEN not in events and BOT_TOKEN not in json.dumps(run)


def test_gate_false_branch_webhook_with_hmac(client, db, alice, mocks):
    tg = cred(client, alice, "tg", "telegram", BOT_TOKEN)
    hm = cred(client, alice, "hm", "webhook_secret", "gate-hmac-secret-123")
    g = build(mocks, tg, hm, "findings.count > 1000")
    wid = client.post("/api/workflows", json={"name": "gate2", "graph": g, "workspace_id": alice.workspace_id},
                      headers=alice.headers).json()["id"]
    rid = client.post(f"/api/workflows/{wid}/run", headers=alice.headers).json()["id"]
    drain(db)
    run = client.get(f"/api/runs/{rid}", headers=alice.headers).json()
    st = {n["node_id"]: n["status"] for n in run["nodes"]}
    assert st["hook"] == "success" and st["tg"] == "skipped" and st["exp"] == "skipped"
    hook = next(r for r in mocks["requests"] if r["path"] == "/hook")
    ts = hook["headers"]["X-AISW-Timestamp"]
    sig = hmac.new(b"gate-hmac-secret-123", ts.encode() + b"." + hook["body"], hashlib.sha256).hexdigest()
    assert hook["headers"]["X-AISW-Signature"] == f"sha256={sig}"
    assert json.loads(hook["body"])["summary"]["total"] == 15
