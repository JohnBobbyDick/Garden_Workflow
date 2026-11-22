import asyncio
import hashlib
import hmac
import json
import threading
import time
from email import message_from_bytes
from email.policy import default as default_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from app.ai.pool import LLMEnv
from app.analyzers.runner import analyze_project
from app.config import get_settings
from app.core.masking import Masker
from app.engine.data import findings_envelope
from app.nodes.output import notify_telegram
from tests.nodes.conftest import TRAINING, run_node

BOT_TOKEN = "123456789:AAFakeTokenForLocalMockServer_abcdefgh"


class Recorder(BaseHTTPRequestHandler):
    requests: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        type(self).requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "result": {"message_id": len(type(self).requests)}}).encode())


@pytest.fixture
def http_server(monkeypatch):
    class H(Recorder):
        requests = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    hostport = f"127.0.0.1:{srv.server_address[1]}"
    monkeypatch.setenv("APP_SSRF_ALLOW_HOSTS", hostport)
    monkeypatch.setenv("APP_TELEGRAM_API_BASE", f"http://{hostport}")
    get_settings.cache_clear()
    yield hostport, H.requests
    srv.shutdown()
    get_settings.cache_clear()


@pytest.fixture(scope="module")
def findings():
    return analyze_project(TRAINING).findings


@pytest.mark.parametrize(("recipient", "expected"), [("-100123", "-100123"), ("team_channel", "@team_channel")])
def test_telegram_sends_summary_with_report_and_document(http_server, services, findings, recipient, expected,
                                                         monkeypatch):
    monkeypatch.setattr("app.telegram.get_llm_env", lambda: LLMEnv(_env_file=None, nvidia_proxies="http://127.0.0.1:1"))
    hostport, reqs = http_server
    services.credentials["tg"] = BOT_TOKEN
    masker = Masker()
    out, sink = run_node("notify.telegram", {"in": [findings_envelope(findings, "m")]},
                         {"bot_token": "tg", "chat_id": recipient}, services, masker=masker)
    paths = [r["path"] for r in reqs]
    assert f"/bot{BOT_TOKEN}/sendMessage" in paths and f"/bot{BOT_TOKEN}/sendDocument" in paths
    msg = json.loads(next(r["body"] for r in reqs if r["path"].endswith("sendMessage")))
    assert msg["chat_id"] == expected
    assert "15" in msg["text"] and "CRITICAL" in msg["text"]
    assert "build.gradle.kts" in msg["text"] or ".kt" in msg["text"]  # top findings listed
    doc = next(r for r in reqs if r["path"].endswith("sendDocument"))
    assert b"report.md" in doc["body"] and "# Отчёт анализа безопасности".encode() in doc["body"]
    assert services.notifications[-1]["status"] == "delivered"
    assert BOT_TOKEN not in repr(sink.events) and BOT_TOKEN not in repr(out["out"].data)


def test_telegram_chat_not_found_explains_how_to_fix_destination():
    response = httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"})
    with pytest.raises(notify_telegram.TelegramError, match=r"chat not found.*Chat ID.*/start"):
        notify_telegram.NotifyTelegram._check(response)


def test_public_telegram_retries_connection_and_sends_document(monkeypatch, services):
    from app import telegram

    monkeypatch.setenv("NVIDIA_PROXIES", "http://u:p@proxy1.test:8080,http://u:p@proxy2.test:8080")
    monkeypatch.setenv("APP_TELEGRAM_API_BASE", "https://api.telegram.org")
    monkeypatch.setattr(telegram, "get_llm_env", lambda: LLMEnv(_env_file=None))
    calls = []

    async def send(method, url, *, proxy, **kwargs):
        calls.append((url.rsplit("/", 1)[1], proxy))
        if proxy.endswith("proxy1.test:8080"):
            raise httpx.ConnectError("unreachable")
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(telegram, "safe_request", send)
    services.credentials["tg"] = BOT_TOKEN
    run_node("notify.telegram", {}, {"bot_token": "tg", "chat_id": "1"}, services)
    delivered = [method for method, proxy in calls if proxy.endswith("proxy2.test:8080")]
    assert calls[0] == ("sendMessage", "http://u:p@proxy1.test:8080")
    assert delivered == ["sendMessage", "sendDocument"]


async def test_telegram_does_not_resend_after_ambiguous_delivery(monkeypatch):
    from app import telegram
    from app.core.ssrf import safe_request

    calls = []

    async def drop_after_post(reader, writer):
        headers = await reader.readuntil(b"\r\n\r\n")
        assert headers.startswith(b"POST ")
        writer.close()
        await writer.wait_closed()

    async def local_request(method, url, **kwargs):
        calls.append(kwargs["proxy"])
        kwargs["allow_hosts"].add("127.0.0.1:1")
        return await safe_request(method, "http://127.0.0.1:1/sendMessage", **kwargs)

    server = await asyncio.start_server(drop_after_post, "127.0.0.1", 0)
    async with server:
        first = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        monkeypatch.setattr(telegram, "get_llm_env", lambda: LLMEnv(
            _env_file=None, nvidia_proxies=f"{first},http://127.0.0.1:2"))
        monkeypatch.setattr(telegram, "safe_request", local_request)
        with pytest.raises(httpx.TransportError, match="Статус отправки неизвестен"):
            await telegram.telegram_request(BOT_TOKEN, "sendMessage", json={"chat_id": "1", "text": "test"})
    assert calls == [first]


@pytest.mark.parametrize(("threshold", "confidence", "count"), [(0.8, 0.9, 1), (0.8, 0.5, 0), (0.4, 0.5, 1)])
def test_telegram_summary_matches_connected_markdown_report(http_server, services, findings, threshold, confidence, count):
    _, requests = http_server
    services.credentials["tg"] = BOT_TOKEN
    finding = next(f for f in findings if f.category == "SAST").model_copy(update={"confidence": confidence})
    state = {"score": {"value": 31, "delta": 0}, "ai": {"summary": "Объяснение анализатора"}}
    report, _ = run_node("output.report_export", {"in": findings_envelope([finding], "scan")},
                         {"min_confidence": threshold}, services, state=state)
    run_node("notify.telegram", {"in": [report["out"]]},
             {"bot_token": "tg", "chat_id": "1",
              "template": "Итого {{findings.count}}, score={{score.value}}. {{ai.summary}}"},
             services, state=state)
    message = json.loads(next(r["body"] for r in requests if r["path"].endswith("/sendMessage")))["text"]
    assert f"Итого {count}, score=31" in message
    assert message.count("Объяснение анализатора") == 1
    assert ("Находок нет" in message) == (count == 0)
    assert (finding.cls in message) == (count == 1)
    document = next(r["body"] for r in requests if r["path"].endswith("/sendDocument"))
    assert services.artifacts["report.md"][0] in document
    assert f"Всего находок: {count}".encode() in document


def test_telegram_long_message_is_split_by_4096(http_server, services, findings):
    _, reqs = http_server
    services.credentials["tg"] = BOT_TOKEN
    many = findings * 40
    long_template = "Заголовок\n" + "\n".join(f"строка {i} " + "x" * 80 for i in range(120))
    run_node("notify.telegram", {"in": [findings_envelope(many, "m")]},
             {"bot_token": "tg", "chat_id": "1", "template": long_template, "send_document": False}, services)
    texts = [json.loads(r["body"])["text"] for r in reqs if r["path"].endswith("sendMessage")]
    assert len(texts) >= 3 and all(len(t) <= 4096 for t in texts)


def test_telegram_blocked_by_ssrf_when_api_base_internal(monkeypatch, services, findings):
    monkeypatch.setenv("APP_TELEGRAM_API_BASE", "http://127.0.0.1:9")
    monkeypatch.setenv("APP_SSRF_ALLOW_HOSTS", "")
    get_settings.cache_clear()
    services.credentials["tg"] = BOT_TOKEN
    try:
        with pytest.raises(Exception, match="заблокирован|внутреннюю"):
            run_node("notify.telegram", {"in": [findings_envelope(findings, "m")]},
                     {"bot_token": "tg", "chat_id": "1"}, services)
        assert services.notifications[-1]["status"] == "failed"
    finally:
        get_settings.cache_clear()


class MailSink:
    def __init__(self):
        self.messages = []

    async def handle_DATA(self, server, session, envelope):
        self.messages.append(envelope)
        return "250 OK"


def test_smtp_sends_html_letter_with_attachments(smtp_server, services, findings):
    port, handler = smtp_server
    run_node("notify.smtp", {"in": [findings_envelope(findings, "m")]},
             {"host": "127.0.0.1", "port": port, "security": "none", "from_addr": "aisw@example.org",
              "to": ["dev@example.org", "lead@example.org"]}, services)
    deadline = time.time() + 5
    while not handler.messages and time.time() < deadline:
        time.sleep(0.05)
    env = handler.messages[0]
    assert set(env.rcpt_tos) == {"dev@example.org", "lead@example.org"}
    msg = message_from_bytes(env.content, policy=default_policy)
    names = {p.get_filename() for p in msg.iter_attachments()}
    assert {"report.html", "report.md"} <= names
    html = msg.get_body(("html",)).get_content()
    assert "<table" in html and "CRITICAL" in html and "15" in html
    assert services.notifications[-1]["channel"] == "smtp"


def test_webhook_posts_signed_json_with_masked_findings(http_server, services, findings):
    hostport, reqs = http_server
    services.credentials["hm"] = "hmac-shared-secret-1234"
    services.credentials["hk"] = "header-secret-value-999"
    run_node("notify.webhook", {"in": [findings_envelope(findings, "m")]},
             {"url": f"http://{hostport}/hook", "hmac_secret": "hm", "headers": {"X-Team": "core"},
              "secret_headers": {"X-Api-Key": "hk"}}, services)
    r = reqs[-1]
    body = r["body"]
    sig = r["headers"]["X-AISW-Signature"]
    ts = r["headers"]["X-AISW-Timestamp"]
    expected = hmac.new(b"hmac-shared-secret-1234", ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert sig == f"sha256={expected}"
    assert r["headers"]["X-Team"] == "core" and r["headers"]["X-Api-Key"] == "header-secret-value-999"
    doc = json.loads(body)
    assert doc["summary"]["total"] == 15 and len(doc["findings"]) == 15
    secrets = [f for f in doc["findings"] if f["category"] == "SECRET"]
    assert secrets and all("value" not in f for f in secrets) and all("…" in (f.get("masked_value") or "…")
                                                                   for f in secrets)
    assert "links" in doc


def test_webhook_ssrf_blocked(services, findings, monkeypatch):
    monkeypatch.setenv("APP_SSRF_ALLOW_HOSTS", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(Exception, match="заблокирован|внутреннюю"):
            run_node("notify.webhook", {"in": [findings_envelope(findings, "m")]},
                     {"url": "http://169.254.169.254/latest/meta-data/"}, services)
    finally:
        get_settings.cache_clear()
